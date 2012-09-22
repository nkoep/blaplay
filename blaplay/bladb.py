# -*- coding: utf-8 -*-
# blaplay, Copyright (C) 2012  Niklas Koep

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

import os
import locale
locale.setlocale(locale.LC_ALL, "")
import shutil
import time
import re
import Queue
import multiprocessing

import gobject
import gtk
import gio
import pango

import blaplay
from blaplay import blacfg, blaconst, blautils, formats
get_extension = blautils.get_extension
get_track = formats.get_track
from blaplay.formats._identifiers import *

EVENT_CREATED, EVENT_DELETED, EVENT_MOVED, EVENT_CHANGED = xrange(4)

library = None
extensions = None
BlaPlaylist = None

def init():
    print_i("Initializing the database")
    global library
    library = BlaLibrary()

def update_library():
    library.update_library()
    BlaPlaylist.update_contents()
    return False


class BlaProgress(gtk.Window):
    def __init__(self, title=""):
        super(BlaProgress, self).__init__()

        hbox = gtk.HBox(spacing=10)
        self.__pb = gtk.ProgressBar()
        button = gtk.Button()
        button.add(gtk.image_new_from_stock(
                gtk.STOCK_CANCEL, gtk.ICON_SIZE_BUTTON))
        button.connect("clicked", lambda *x: self.destroy())
        hbox.pack_start(self.__pb, expand=True)
        hbox.pack_start(button, expand=False)

        self.__text = gtk.Label("Working...")
        self.__text.set_alignment(0.0, 0.5)

        vbox = gtk.VBox(spacing=5)
        vbox.pack_start(self.__text, expand=False, fill=False)
        vbox.pack_start(hbox, expand=True, fill=False)

        self.set_title(title)
        self.add(vbox)
        self.set_border_width(10)
        self.set_type_hint(gtk.gdk.WINDOW_TYPE_HINT_DIALOG)
        self.set_destroy_with_parent(True)
        self.set_position(gtk.WIN_POS_CENTER)
        self.set_resizable(False)

        self.show_all()

    def pulse(self, *args):
        self.__pb.pulse()
        return True

    def switch_mode(self):
        width = 550
        self.__text.set_size_request(width, -1)
        self.__text.set_ellipsize(pango.ELLIPSIZE_MIDDLE)
        self.set_size_request(width, -1)
        self.set_position(gtk.WIN_POS_CENTER)

    def set_fraction(self, fraction):
        self.__pb.set_fraction(fraction)
        self.__pb.set_text("%d %%" % (fraction * 100))

    def set_text(self, text):
        self.__text.set_text(text)

class BlaLibraryMonitor(gobject.GObject):
    __gsignals__ = {
        "initialized": blaplay.signal(1)
    }

    __monitors = {}
    __lock = blautils.BlaLock()
    __queue = Queue.Queue()
    __processing = False
    ignore = set()

    def __init__(self):
        super(BlaLibraryMonitor, self).__init__()
        self.__process_events()

    def __queue_event(self, monitor, path_from, path_to, type_):
        if type_ == gio.FILE_MONITOR_EVENT_CHANGES_DONE_HINT:
            event = EVENT_CHANGED
        elif type_ == gio.FILE_MONITOR_EVENT_DELETED:
            event = EVENT_DELETED
        elif type_ == gio.FILE_MONITOR_EVENT_MOVED:
            event = EVENT_MOVED
        elif type_ == gio.FILE_MONITOR_EVENT_CREATED:
            event = EVENT_CREATED
            path = path_from.get_path()
            if os.path.isdir(path): self.add_directory(path)
        else: event = None

        if event is not None:
            path_from = path_from.get_path()
            try: path_to = path_to.get_path()
            except AttributeError: pass
            self.__queue.put((event, path_from, path_to))

    @blautils.thread
    def __process_events(self):
        # FIXME: scanning a lot of files from here slows the application down
        #        quite a bit as python threads aren't suited for heavy
        #        computation. implementing a similar approach as when adding a
        #        new directory to the library fails because calling
        #        main_iteration from a thread seems to deadlock the
        #        application, not to mention the fact that this isn't the
        #        fastest approach either

        # FIXME: creating a new folder in nautilus (which is first known as
        #        `unknown folder', and then removed when it's properly named)
        #        seems to cause the removal of the library monitor for the
        #        parent directory. no events will be triggered in it anymore
        #        from then on, i.e.:
        #        *** DEBUG (bladb.py:162): New event of type `EVENT_CREATED'
        #               for file /media/Eigene/Musik/untitled folder (None)
        #        *** DEBUG (bladb.py:162): New event of type `EVENT_DELETED'
        #               for file /media/Eigene/Musik/untitled folder (None)
        #        apart from that, no EVENT_CHANGED or EVENT_MOVED is triggered
        #        meaning we don't know the actual name of the folder after it
        #        was renamed. do we have to abandon gio for pyinotify again?

        EVENTS = {
            EVENT_CREATED: "EVENT_CREATED",
            EVENT_DELETED: "EVENT_DELETED",
            EVENT_CHANGED: "EVENT_CHANGED",
            EVENT_MOVED: "EVENT_MOVED"
        }

        tid = -1
        while True:
            event, path_from, path_to = self.__queue.get(block=True)
            print_d("New event of type `%s' for file %s (%r)" %
                    (EVENTS[event], path_from, path_to))

            update_track = library.update_track
            update = True
            gobject.source_remove(tid)

            if event == EVENT_CREATED:
                if path_from in BlaLibraryMonitor.ignore:
                    BlaLibraryMonitor.ignore.remove(path_from)
                    update = False
                elif os.path.isfile(path_from): library.add_tracks([path_from])
                else:
                    # for files that are copied a CHANGED event is triggered
                    # as well. this is not the case for moved files. this is
                    # why we can't add any paths to the ignore set here as they
                    # might not be removed again. unfortunately we have no
                    # choice but to let the event handlers do their job even if
                    # it means checking certain files multiple times
                    library.add_tracks(blautils.discover(path_from))

            elif event == EVENT_CHANGED:
                if path_from in BlaLibraryMonitor.ignore:
                    BlaLibraryMonitor.ignore.remove(path_from)
                    update = False
                elif os.path.isfile(path_from): library.add_tracks([path_from])

            elif event == EVENT_DELETED:
                # this is a bit fiddly. we can't check if whatever was
                # deleted was a file or a directory since it's already
                # unlinked. we therefore have to check every URI in the
                # library against `path_from'. if we get an exact match we
                # can remove the track and stop since URIs are unique. if
                # we get a partial match we have to continue looking. to
                # keep string comparison to a minimum we use str.startswith
                # to see if we should remove a track. we then check if the
                # strings have the same length as this indicates an exact
                # match so we can stop iterating
                l = len(path_from)
                try:
                    for uri in library:
                        if uri.startswith(path_from) and uri[l] == "/":
                            library.remove_track(uri)
                except IndexError:
                    # IndexError will only be raised for exact matches, meaning
                    # we removed a file
                    library.remove_track(uri)
                else:
                    # if we made it this far we didn't get an exact match so
                    # we removed a directory. in this case we remove every file
                    # monitor under the given directory
                    self.remove_directories(path_from)

            else: # event == EVENT_MOVED
                uris = []
                if os.path.isfile(path_to):
                    library.move_track(path_from, path_to)
                    uris.append((path_from, path_to))
                else:
                    for uri in library:
                        if uri.startswith(path_from):
                            new_path = os.path.join(
                                    path_to, uri[len(path_from)+1:])
                            library.move_track(uri, new_path)
                            uris.append((uri, new_path))

                    self.remove_directories(path_from)
                    self.add_directory(path_to)
                BlaPlaylist.update_uris(uris)

            # schedule an update for the library browser, etc. if there are
            # more items in the queue the timeout will be removed in the next
            # loop iteration
            if update: tid = gobject.timeout_add(3000, update_library)

    def __get_subdirectories(self, directories):
        # the heavy lifting here is actually just getting a list of all the
        # directories which need a monitor. the creation of the monitors itself
        # is rather simple. to circumvent the GIL when getting the directory
        # list we use another process. a generator would be more memory
        # efficient, however, on first run we can pass the directory list on
        # to the method which scans for changed files so it doesn't have to
        # walk the entire directory tree again
        def get_subdirectories(conn, directories):
            discover = blautils.discover
            directories = list(discover(directories, directories_only=True))
            conn.send(directories)

        conn1, conn2 = multiprocessing.Pipe(duplex=False)
        p = multiprocessing.Process(
                target=get_subdirectories, args=(conn2, directories))
        p.daemon = True
        p.start()
        directories = conn1.recv()
        # processes must be joined to prevent them from turning into zombie
        # processes on unices
        p.join()
        return directories

    @blautils.thread
    def add_directory(self, directory):
        directories = self.__get_subdirectories(directory)

        with self.__lock:
            for directory in directories:
                if directory in self.__monitors: continue
                f = gio.File(directory)
                monitor = f.monitor_directory(flags=gio.FILE_MONITOR_NONE |
                        gio.FILE_MONITOR_SEND_MOVED)
                monitor.connect("changed", self.__queue_event)
                self.__monitors[directory] = monitor

    @blautils.thread
    def remove_directories(self, md):
        with self.__lock:
            directories = sorted(self.__monitors.keys())
            for directory in directories:
                if directory.startswith(md):
                    self.__monitors.pop(directory).cancel()

    @blautils.thread
    def update_directories(self):
        monitored_directories = blacfg.getdotliststr("library", "directories")
        directories = self.__get_subdirectories(monitored_directories)

        with self.__lock:
            cancel = gio.FileMonitor.cancel
            map(cancel, self.__monitors.itervalues())
            self.__monitors.clear()

            # according to the GIO C API documentation there are backends which
            # don't support gio.FILE_MONITOR_EVENT_MOVED. however, since we
            # specifically target Linux which has inotify since kernel 2.6.13
            # we're in the clear (that is if the kernel in use was compiled
            # with inotify support)
            for directory in directories:
                f = gio.File(directory)
                monitor = f.monitor_directory(flags=gio.FILE_MONITOR_NONE |
                        gio.FILE_MONITOR_SEND_MOVED)
                monitor.connect("changed", self.__queue_event)
                self.__monitors[directory] = monitor

        print_d("Now monitoring everything in: %r" % monitored_directories)
        self.emit("initialized", directories)

class BlaLibraryModel(object):
    # FIXME: for a library of 9000~ tracks creating an instance of the model
    #        increases the interpreter's memory use by roughly 4 MB every time.
    #        would this be better with a "lazy" model, i.e. synthesizing nodes
    #        on row expansion?

    __layout = [
        gobject.TYPE_STRING,    # uri
        gobject.TYPE_STRING,    # label (with child count if present)
        gobject.TYPE_STRING,    # label
        gobject.TYPE_BOOLEAN    # visibility value for filtering
    ]

    def __new__(cls, view, tracks, filt):
        def get_iterator(model, iterators, comps):
            d = iterators
            iterator = None
            for comp in comps:
                try: iterator, d = d[comp]
                except KeyError:
                    d[comp] = [model.append(
                            iterator, ["", comp, comp, True]), {}]
                    iterator, d = d[comp]
            return iterator

        model = gtk.TreeStore(*cls.__layout)

        if view == blaconst.ORGANIZE_BY_DIRECTORY:
            cb = cls.__organize_by_directory
        elif view == blaconst.ORGANIZE_BY_ARTIST:
            cb = cls.__organize_by_artist
        elif view == blaconst.ORGANIZE_BY_ARTIST_ALBUM:
            cb = cls.__organize_by_artist_album
        elif view == blaconst.ORGANIZE_BY_ALBUM:
            cb = cls.__organize_by_album
        elif view in [blaconst.ORGANIZE_BY_GENRE, blaconst.ORGANIZE_BY_YEAR]:
            cb = (lambda uri, comps:
                    cls.__organize_by_genre_year(uri, comps, view=view))
        else: raise NotImplementedError

        iterators = {}
        old_iterator, old_comps = None, None
        append = model.append

        for uri, track in tracks.iteritems():
            if not filt(os.path.basename(uri)): continue

            comps, leaf = cb(uri, track)

            if old_comps is not None and comps == old_comps:
                iterator = old_iterator
            else: iterator = get_iterator(model, iterators, comps)

            append(iterator, [uri, leaf, leaf, True])

            old_iterator = iterator
            old_comps = comps

        filt = model.filter_new()
        filt.set_visible_column(3)
        sort = gtk.TreeModelSort(filt)
        sort.set_sort_column_id(2, gtk.SORT_ASCENDING)
        return sort

    @classmethod
    def __get_track_label(cls, track):
        try: label = "%d." % int(track[DISC].split("/")[0])
        except ValueError: label = ""
        try: label += "%02d. " % int(track[TRACK].split("/")[0])
        except ValueError: pass
        artist = (track[ALBUM_ARTIST] or track[ARTIST] or track[PERFORMER] or
                track[COMPOSER])
        if track[ARTIST] and artist != track[ARTIST]:
            label += "%s - " % track[ARTIST]
        return "%s%s" % (label, track[TITLE] or track.basename)

    @classmethod
    def __organize_by_directory(cls, uri, track):
        if not track[MONITORED_DIRECTORY]:
            raise ValueError("Trying to include track in the library browser "
                    "that has no monitored directory")
        directory = os.path.dirname(
                track.path)[len(track[MONITORED_DIRECTORY])+1:]
        comps = directory.split("/")
        if comps == [""]: comps = ["bla"]
        else: comps.insert(0, "bla")
        return comps, os.path.basename(track.path)

    @classmethod
    def __organize_by_artist(cls, uri, track):
        return ([track[ARTIST] or "?", track[ALBUM] or "?"],
                cls.__get_track_label(track))

    @classmethod
    def __organize_by_artist_album(cls, uri, track):
        artist = (track[ALBUM_ARTIST] or track[PERFORMER] or track[ARTIST] or
                "?")
        return (["%s - %s" % (artist, track[ALBUM] or "?")],
                cls.__get_track_label(track))

    @classmethod
    def __organize_by_album(cls, uri, track):
        return [track[ALBUM] or "?"], cls.__get_track_label(track)

    @classmethod
    def __organize_by_genre_year(cls, uri, track, view):
        if view == blaconst.ORGANIZE_BY_GENRE: key = GENRE
        else: key = DATE
        organizer = track[key].capitalize() or "?"
        if key == DATE: organizer = organizer.split("-")[0]
        label = "%s - %s" % (
                track[ALBUM_ARTIST] or track[ARTIST], track[ALBUM] or "?")
        return [organizer, label], cls.__get_track_label(track)

class BlaLibrary(gobject.GObject):
    __gsignals__ = {
        "progress": blaplay.signal(1),
        "update_library_browser": blaplay.signal(1)
    }

    __monitored_directories = []
    __scan_queue = []
    __currently_scanning = None
    __tracks = {}
    __tracks_ool = {}
    __playlists = []
    __queue = []
    __lock = blautils.BlaLock(strict=True)
    __pending_save = False

    def __init__(self):
        super(BlaLibrary, self).__init__()
        formats.init()
        global extensions
        extensions = formats.formats.keys()
        self.__extension_filter = re.compile("(%s)" % ")|(".join([r".*\.%s$"
                % ext for ext in extensions])).match

        # restore the library
        tracks = blautils.deserialize_from_file(blaconst.LIBRARY_PATH)
        if tracks is not None: self.__tracks = tracks
        else: blacfg.set("library", "directories", "")

        self.__monitored_directories = map(os.path.realpath,
                blacfg.getdotliststr("library", "directories"))

        # restore playlists and OOL tracks
        try:
            self.__tracks_ool, self.__playlists, self.__queue = \
                    blautils.deserialize_from_file(blaconst.PLAYLISTS_PATH)
        except TypeError: pass

        print_d("Restoring library: %d tracks in the library, %d additional "
                "tracks" % (len(self.__tracks), len(self.__tracks_ool)))

        def initialized(library_monitor, directories):
            p = self.__detect_changes(directories)
            gobject.idle_add(p.next)
            self.__library_monitor.disconnect(cid)
        self.__library_monitor = BlaLibraryMonitor()
        if blacfg.getboolean("library", "update.on.startup"):
            cid = self.__library_monitor.connect("initialized", initialized)
        self.__library_monitor.update_directories()

    def __getitem__(self, key):
        try: return self.__tracks[key]
        except KeyError: return self.__tracks_ool[key]

    def __setitem__(self, key, item):
        if self.__tracks.has_key(key): self.__tracks[key] = item
        else: self.__tracks_ool[key] = item

    def __contains__(self, item):
        return item in self.__tracks

    def __iter__(self):
        return self.next()

    def next(self):
        for uri in self.__tracks.iterkeys(): yield uri

    def __detect_changes(self, directories):
        # this function does not perform any write operations on files. it
        # merely updates our metadata of tracks in directories we're monitoring
        yield_interval = 25

        print_i("Checking for changed library contents in: %r"
                % blacfg.getdotliststr("library", "directories"))

        # update __tracks_ool dict first
        exists = os.path.exists
        update_track = self.update_track
        for idx, uri in enumerate(filter(exists, self.__tracks_ool.keys())):
            update_track(uri)
            if idx % yield_interval == 0: yield True

        # check for new tracks or tracks in need of updating in monitored
        # directories
        updated = 0
        for idx, uri in enumerate(self):
            updated += int(update_track(uri))
            if idx % yield_interval == 0: yield True

        files = set()
        add = files.add
        discover = blautils.discover
        new_files = 0
        idx = 0
        for directory in set(directories):
            for f in discover(directory):
                if f not in self: add(f)
                if len(files) == yield_interval:
                    new_files += self.add_tracks(files)
                    files.clear()
                if idx % yield_interval == 0: yield True
                idx += 1
            if files: new_files += self.add_tracks(files)

        # check for missing tracks and remove them (they're actually moved to
        # __tracks_ool so playlists referencing a URI will have the last known
        # metadata to use)
        remove_track = self.remove_track
        missing = 0
        for idx, f in enumerate(self.__tracks.keys()):
            if not exists(f):
                missing += 1
                remove_track(f)
            if idx % yield_interval == 0: yield True

        print_i("%d files missing, %d possibly new ones, %d updated"
                % (missing, new_files, updated))

        # finally update the model for the library browser and playlists. the
        # GUI might not be fully initialized yet, so wait for that to happen
        # before requesting an update. interesting tidbit: if instead of
        # `import blagui' we would have used `from blaplay import blagui'
        # python would have marked the name `blaplay' as variable local to this
        # generator function and thus masking the fact that it's actually an
        # already imported module that resides in the globals dict, making it
        # unusable as a module in this method's context
        import blagui
        while blagui.bla is None: yield True
        if missing or new_files or updated: update_library()
        yield False

    def __get_filter(self):
        def get_regexp(string):
            tokens = [t.replace(".", "\.").replace("*", ".*")
                    for t in map(str.strip, string.split(","))]
            return re.compile("(%s)" % ")|(".join([r"%s" % t for t in tokens]))

        restrict_re = get_regexp(
                blacfg.getstring("library", "restrict.to").strip())
        exclude_string = blacfg.getstring("library", "exclude").strip()
        if exclude_string:
            exclude_re = get_regexp(exclude_string)
            filt = lambda s: restrict_re.match(s) and not exclude_re.match(s)
        else: filt = restrict_re.match
        return filt

    def add_tracks(self, uris):
        count = 0
        filt = self.__extension_filter
        add = self.add
        for uri in filter(filt, uris):
            track = get_track(uri)
            if not track: continue
            for md in self.__monitored_directories:
                if uri.startswith(md):
                    track[MONITORED_DIRECTORY] = md
                    add(track)
                    break
            count += 1
        return count

    def update_track(self, uri, return_track=False):
        # this returns whether track was updated or not or alternatively the
        # (possibly) updated track. in case a track was actually missing we
        # return None no matter what
        track = self[uri]
        updated = False

        try: mtime = os.path.getmtime(uri)
        except OSError: pass
        else:
            if track[MTIME] != mtime:
                md = track[MONITORED_DIRECTORY]
                track = get_track(uri)
                if track:
                    track[MONITORED_DIRECTORY] = md
                    library[uri] = track
                    updated = True
        return track if return_track else updated

    def add(self, track):
        self.__tracks[track.path] = track
        try: del self.__tracks_ool[track.path]
        except KeyError: pass

    def move_track(self, path_from, path_to, md=""):
        # when a file is moved we create an entry for the new path in the
        # __tracks dict and move the old track to __tracks_ool. this is
        # necessary because some elements like the player, scrobbler or a
        # playlist might still try to get metadata using the old URI so we
        # have to guarantee that it's still available somewhere. the redundant
        # data will be removed from __tracks_ool on shutdown when we sync
        # entries in __tracks_ool to playlist contents

        # get first match for a monitored directory if none is given
        if not md:
            for md in self.__monitored_directories:
                if path_to.startswith(md): break
            else: md = ""

        # try to get the corresponding track from the library. if it's not in
        # it we might have to try and parse it cause it could just be a rename.
        # chrome, for instance, appends a .crdownload to downloads and then
        # renames them properly on completion
        try: track = self.__tracks[path_from]
        except KeyError:
            track = get_track(path_to)
            if track:
                track[MONITORED_DIRECTORY] = md
                self.add(track)
            return

        if path_from in self.__tracks and path_from != path_to:
            self.__tracks_ool[path_from] = self.__tracks.pop(path_from)
        track[PATH] = path_to
        track[MONITORED_DIRECTORY] = md
        if md: self.__tracks[path_to] = track
        else: self.__tracks_ool[path_to] = track

    def remove_track(self, uri):
        try: track = self.__tracks[uri]
        except KeyError: pass
        else:
            track[MONITORED_DIRECTORY] = ""
            self.__tracks_ool[uri] = track
            del self.__tracks[uri]

    def request_model(self, view):
        def f():
            model = BlaLibraryModel(view, self.__tracks, self.__get_filter())
            self.emit("update_library_browser", model)
            return False
        try: gobject.source_remove(self.__cid)
        except AttributeError: pass
        self.__cid = gobject.idle_add(f)

    def update_library(self):
        model = BlaLibraryModel(blacfg.getint("library", "organize.by"),
                self.__tracks, self.__get_filter())
        self.emit("update_library_browser", model)
        # pickling a large dict causes quite an increase in memory use as the
        # module basically creates an exact copy of the object in RAM. to
        # combat the problem we hold off on any serialization until blaplay
        # shuts down, at the risk of losing metadata during a crash
        self.__pending_save = True
        self.__monitored_directories = map(os.path.realpath,
                blacfg.getdotliststr("library", "directories"))
        return False

    def save_library(self):
        if self.__pending_save:
            print_i("Updating library on disk")
            blautils.serialize_to_file(self.__tracks, blaconst.LIBRARY_PATH)
        return 0

    def get_playlists(self):
        # we need BlaPlaylist throughout this module, but we can't import it on
        # module initialization as the class object isn't created at that time.
        # when this method is called we can be sure the class exists
        from blagui import blaplaylist
        global BlaPlaylist
        BlaPlaylist = blaplaylist.BlaPlaylist

        return self.__playlists, self.__queue

    def save_playlists(self, playlists, queue):
        def remove_track_ool(uri): self.__tracks_ool.pop(uri, None)

        # create a set of all OOL uris. then we build the difference between
        # this set and the set of URIs for each playlist. the remainder will be
        # a set of URIs that weren't referenced in any playlist so we just
        # remove them
        ool_uris = set(self.__tracks_ool.keys())
        for playlist in playlists:
            ool_uris.difference_update(set(playlist[-1]))
        map(remove_track_ool, ool_uris)

        blautils.serialize_to_file(
                (self.__tracks_ool, playlists, queue), blaconst.PLAYLISTS_PATH)

    def parse_ool_uris(self, uris):
        # FIXME: the performance of the application suffers quite a bit from
        #        these controlled mainloops. it would be nice if parsing could
        #        be done in a separate process. the problem is that moving
        #        contents in the library won't work as a process only gets a
        #        copy of the library. we would have to replace self once the
        #        process returns or we could retrieve the updated track dicts

        def process(ns, uris, pb):
            # update every 40 ms (25 fps)
            tid = gobject.timeout_add(40, pb.pulse)

            files = []
            filt = self.__extension_filter
            for uri in uris:
                uri = os.path.realpath(uri)
                if os.path.isdir(uri):
                    for f in blautils.discover(uri):
                        filt(f) and files.append(f)
                        yield True
                else:
                    files.append(uri)
                    yield True

            gobject.source_remove(tid)

            pb.switch_mode()
            uris = sorted(files, cmp=locale.strcoll)
            try: c = 1.0 / len(uris)
            except ZeroDivisionError: pass

            for idx, uri in enumerate(uris):
                pb.set_text(uri)
                pb.set_fraction(c * (idx+1))
                yield True

                try: track = self[uri]
                except KeyError:
                    track = get_track(uri)
                    self.__tracks_ool[uri] = track
                if track: ns["uris"].append(uri)

            pb.set_fraction(1.0)
            pb.hide()
            pb.destroy()
            ns["wait"] = False
            ns["done"] = True
            yield False

        def cancel(ns): ns["wait"] = False
        pb = BlaProgress(title="Scanning files...")
        pb.connect("destroy", lambda *x: cancel(ns))
        ns = {"uris": [], "wait": True, "done": False}
        p = process(ns, uris, pb)
        gobject.idle_add(p.next)

        # FIXME: gtk.main_iteration() always returns True when it's called
        #        before we entered a mainloop. this prevents the following loop
        #        from properly processing all files passed to the CL on startup

        # this guarantees that we don't return before all URIs have been
        # checked, but normal event-processing still commences
        while ns["wait"]:
            if gtk.events_pending() and gtk.main_iteration(): return
        return ns["uris"] if ns["done"] else None

    def scan_directory(self, directory):
        def scan(directory):
            t = time.time()
            print_d("Scanning `%s' and its subdirectories..." % directory)

            self.emit("progress", "pulse")
            self.__aborted = False

            checked_directories = []
            files = []

            filt = self.__extension_filter
            for f in blautils.discover(directory):
                filt(f) and files.append(f)
                if self.__aborted:
                    self.emit("progress", "abort")
                    self.__currently_scanning = None
                    ns["wait"] = False
                    yield False
                yield True

            try: c = 1.0 / len(files)
            except ZeroDivisionError: pass

            for idx, path in enumerate(files):
                self.emit("progress", c * (idx+1))

                if self.__aborted:
                    self.emit("progress", "abort")
                    self.__currently_scanning = None
                    ns["wait"] = False
                    yield False

                try: track = self.__tracks[path]
                except KeyError:
                    # if track wasn't in the library check if it was in
                    # __tracks_ool (it might require an update then)
                    try: track = self.__tracks_ool[path]
                    except KeyError: track = get_track(path)
                    else: track = self.update_track(path, return_track=True)

                if track and not track[MONITORED_DIRECTORY]:
                    track[MONITORED_DIRECTORY] = directory
                    self.add(track)
                yield True

            self.update_library()
            self.__library_monitor.add_directory(directory)
            self.emit("progress", 1.0)

            print_d("Finished parsing of %d files after %.2f seconds"
                    % (len(files), (time.time() - t)))

            ns["wait"] = False
            self.__currently_scanning = None
            yield False

        self.__scan_queue.append(directory)
        if not self.__currently_scanning:
            while True:
                try: directory = self.__scan_queue.pop(0)
                except IndexError: break

                ns = {"wait": True}
                directory = os.path.realpath(directory)
                self.__currently_scanning = directory
                p = scan(directory)
                gobject.idle_add(p.next)
                while ns["wait"]:
                    if gtk.events_pending() and gtk.main_iteration(): return

    @blautils.thread
    def remove_directory(self, directory):
        directory = os.path.realpath(directory)
        while True:
            try: self.__scan_queue.remove(directory)
            except ValueError: break
        if self.__currently_scanning == directory: self.__aborted = True

        remove_track = self.remove_track
        tracks = [(uri, track) for uri, track in self.__tracks.iteritems()
                if track[MONITORED_DIRECTORY] == directory]
        mds = self.__monitored_directories

        try: mds.remove(directory)
        except ValueError: pass

        for uri, track in tracks:
            for md in mds:
                if uri.startswith(md):
                    self.move_track(uri, uri, md)
                    break
            else: remove_track(uri)

        # if there are no more monitored directories but still tracks in the
        # library something went wrong so move them to __tracks_ool as well
        if not mds: map(remove_track, self.__tracks.iterkeys())
        self.update_library()
        self.__library_monitor.remove_directories(directory)

