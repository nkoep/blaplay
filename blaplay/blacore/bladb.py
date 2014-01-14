# blaplay, Copyright (C) 2012-2013  Niklas Koep

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
import threading
import Queue
import multiprocessing

import gobject
import gtk
import gio
import pango

import blaplay
from blaplay.blacore import blacfg, blaconst
from blaplay import blautil, formats
get_track = formats.get_track
from blaplay.formats._identifiers import *

EVENT_CREATED, EVENT_DELETED, EVENT_MOVED, EVENT_CHANGED = xrange(4)

# TODO: Move `pending_save' or a similar variable into BlaLibrary.
pending_save = False


def init():
    library.init()
    return library

def update_library():
    global pending_save

    library.sync()
    pending_save = False

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
        "initialized": blautil.signal(1)
    }

    __monitors = {}
    __lock = blautil.BlaLock()
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
            if os.path.isdir(path):
                self.add_directory(path)
        else:
            event = None

        if event is not None:
            path_from = path_from.get_path()
            try:
                path_to = path_to.get_path()
            except AttributeError:
                pass
            self.__queue.put((event, path_from, path_to))

    @blautil.thread
    def __process_events(self):
        # TODO: give this another shot with a controlled driven loop that is
        #       triggered by a queue event

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
                elif os.path.isfile(path_from):
                    library.add_tracks([path_from])
                else:
                    # For files that are copied a CHANGED event is triggered
                    # as well. This is not the case for moved files. This is
                    # why we can't add any paths to the ignore set here as they
                    # might never be removed again. Unfortunately, we have no
                    # choice but to let the event handlers do their job even if
                    # it means checking certain files multiple times.
                    library.add_tracks(blautil.discover(path_from))

            elif event == EVENT_CHANGED:
                if path_from in BlaLibraryMonitor.ignore:
                    BlaLibraryMonitor.ignore.remove(path_from)
                    update = False
                elif os.path.isfile(path_from):
                    library.add_tracks([path_from])

            elif event == EVENT_DELETED:
                # This is a bit fiddly. We can't check if whatever was deleted
                # was a file or a directory since it's already unlinked.
                # We therefore have to check every URI in the library against
                # `path_from'. If we get an exact match we can remove the track
                # and stop since URIs are unique. If we get a partial match we
                # have to continue looking. To keep string comparison to a
                # minimum we use str.startswith to see if we should remove a
                # track. We then check if the strings have the same length as
                # this indicates an exact match so we can stop iterating.
                l = len(path_from)
                try:
                    # iterating over a BlaLibrary instance uses a generator so
                    # we have to make a list of tracks to remove first
                    for uri in library:
                        if uri.startswith(path_from) and uri[l] == "/":
                            library.remove_track(uri)
                except IndexError:
                    # IndexError will only be raised for exact matches, meaning
                    # we removed a file.
                    library.remove_track(uri)
                else:
                    # If we made it this far we didn't get an exact match so
                    # we removed a directory. In this case we remove every file
                    # monitor under the given directory.
                    self.remove_directories(path_from)

            else: # event == EVENT_MOVED
                uris = {}
                if os.path.isfile(path_to):
                    library.move_track(path_from, path_to)
                    uris[path_from] = path_to
                else:
                    for uri in library:
                        if uri.startswith(path_from):
                            new_path = os.path.join(
                                    path_to, uri[len(path_from)+1:])
                            library.move_track(uri, new_path)
                            uris[uri] = new_path

                    self.remove_directories(path_from)
                    self.add_directory(path_to)
                # TODO: Add a `library_entries_moved' signal for this so we
                #       don't need to call methods on the playlist manager.
                from blaplay.blagui.blaplaylist import BlaPlaylistManager
                BlaPlaylistManager().update_uris(uris)

            # Schedule an update for the library browser, etc. The timeout
            # might be removed immediately at the beginning of this loop if
            # there are more events in the queue.
            if update:
                global pending_save
                pending_save = True
                tid = gobject.timeout_add(3000, update_library)

    def __get_subdirectories(self, directories):
        # The heavy lifting here is actually just getting a list of all the
        # directories which need a monitor. The creation of the monitors itself
        # is rather simple. To circumvent the GIL when getting the directory
        # list we use another process, even though a generator would be more
        # memory efficient. However, on start-up we can pass the directory list
        # on to the method which scans for changed files so it doesn't have to
        # walk the entire directory tree again.
        def get_subdirectories(conn, directories):
            # KeyboardInterrupt exceptions need to be handled in child
            # processes. Since this is no crucial operation we can just return.
            try:
                discover = blautil.discover
                directories = list(
                        discover(directories, directories_only=True))
                conn.send(directories)
            except KeyboardInterrupt:
                pass

        conn1, conn2 = multiprocessing.Pipe(duplex=False)
        p = multiprocessing.Process(
                target=get_subdirectories, args=(conn2, directories))
        p.daemon = True
        p.start()
        directories = conn1.recv()
        # Processes must be joined to prevent them from turning into zombie
        # processes on unices.
        p.join()
        return directories

    @blautil.thread
    def add_directory(self, directory):
        # TODO: this is largely identical to update_directories. combine the
        #       two methods
        directories = self.__get_subdirectories(directory)

        with self.__lock:
            for directory in directories:
                if directory in self.__monitors:
                    continue
                f = gio.File(directory)
                monitor = f.monitor_directory(
                    flags=gio.FILE_MONITOR_NONE | gio.FILE_MONITOR_SEND_MOVED)
                monitor.connect("changed", self.__queue_event)
                self.__monitors[directory] = monitor

    @blautil.thread
    def remove_directories(self, md):
        with self.__lock:
            for directory in sorted(self.__monitors.keys()):
                if directory.startswith(md):
                    self.__monitors.pop(directory).cancel()

    @blautil.thread
    def update_directories(self):
        monitored_directories = blacfg.getdotliststr("library", "directories")
        directories = self.__get_subdirectories(monitored_directories)

        with self.__lock:
            cancel = gio.FileMonitor.cancel
            map(cancel, self.__monitors.itervalues())
            self.__monitors.clear()

            # According to the GIO C API documentation there are backends which
            # don't support gio.FILE_MONITOR_EVENT_MOVED. However, since we
            # specifically target Linux which has inotify since kernel 2.6.13
            # we should be in the clear (that is if the kernel in use was
            # compiled with inotify support).
            for directory in directories:
                f = gio.File(directory)
                monitor = f.monitor_directory(
                    flags=gio.FILE_MONITOR_NONE | gio.FILE_MONITOR_SEND_MOVED)
                monitor.connect("changed", self.__queue_event)
                self.__monitors[directory] = monitor
        print_d("Now monitoring %d directories in: %r" %
                (len(self.__monitors), monitored_directories))
        self.emit("initialized", directories)

# TODO: Make this a singleton.
class BlaLibrary(gobject.GObject):
    __gsignals__ = {
        "progress": blautil.signal(1),
        "library_updated": blautil.signal(0)
    }

    __monitored_directories = []
    __scan_queue = []
    __currently_scanning = None
    __tracks = {}
    __tracks_ool = {}
    __playlists = []
    __lock = blautil.BlaLock(strict=True)

    def __init__(self):
        super(BlaLibrary, self).__init__()

        self.__extension_filter = re.compile(
            r".*\.(%s)$" % "|".join(formats.formats.keys())).match

    def __call__(self):
        print_i("Saving pending library changes")

        if pending_save:
            self.__save_library()

    def __getitem__(self, key):
        try:
            return self.__tracks[key]
        except KeyError:
            return self.__tracks_ool[key]

    def __setitem__(self, key, item):
        if self.__tracks.has_key(key):
            self.__tracks[key] = item
        else:
            self.__tracks_ool[key] = item

    def __contains__(self, item):
        return item in self.__tracks

    def __iter__(self):
        return self.next()

    def next(self):
        for uri in self.__tracks.keys():
            yield uri

    def __save_library(self):
        # Pickling a large dict causes quite an increase in memory use as the
        # module basically creates an exact copy of the object in memory. To
        # combat the problem we offload the serialization of the library to
        # another process. We join the process in a separate thread to avoid
        # that the process turns into a zombie process after it terminates.
        # If the process itself is spawned from a thread this seems to deadlock
        # occasionally.
        p = multiprocessing.Process(
            target=blautil.serialize_to_file,
            args=(self.__tracks, blaconst.LIBRARY_PATH))
        p.start()

        @blautil.thread_nondaemonic
        def join():
            p.join()
        join()

    def __detect_changes(self, directories):
        # FIXME: this is insanely slow

        # TODO: looks like it's faster to just rescan all monitored directories

        # This method does not perform any write operations on files. It
        # merely updates our metadata of tracks in directories we're
        # monitoring.
        yield_interval = 25

        print_i("Checking for changed library contents in: %r" %
                blacfg.getdotliststr("library", "directories"))

        # update __tracks_ool dict first
        exists = os.path.exists
        update_track = self.update_track
        for idx, uri in enumerate(
            filter(exists, self.__tracks_ool.iterkeys())):
            update_track(uri)
            if idx % yield_interval == 0:
                yield True

        # Check for new tracks or tracks in need of updating in monitored
        # directories.
        updated = 0
        for idx, uri in enumerate(self):
            updated += int(update_track(uri))
            if idx % yield_interval == 0:
                yield True

        files = set()
        add = files.add
        discover = blautil.discover
        new_files = 0
        idx = 0
        for directory in set(directories):
            for f in discover(directory):
                if f not in self:
                    add(f)
                if len(files) == yield_interval:
                    new_files += self.add_tracks(files)
                    files.clear()
                if idx % yield_interval == 0:
                    yield True
                idx += 1
            if files:
                new_files += self.add_tracks(files)

        # Check for missing tracks and remove them. (They're actually moved to
        # __tracks_ool so playlists referencing a URI will have the last known
        # metadata to use.)
        remove_track = self.remove_track
        missing = 0
        for idx, f in enumerate(self.__tracks.keys()):
            if not exists(f):
                missing += 1
                remove_track(f)
            if idx % yield_interval == 0:
                yield True

        print_i("%d files missing, %d new ones, %d updated" %
                (missing, new_files, updated))

        # Finally update the model for the library browser and playlists. The
        # GUI might not be fully initialized yet, so wait for that to happen
        # before requesting an update.
        while blaplay.bla.window is None:
            yield True
        if missing or new_files or updated:
            update_library()
        yield False

    def init(self):
        print_i("Initializing the database")

        # Restore the library.
        tracks = blautil.deserialize_from_file(blaconst.LIBRARY_PATH)
        if tracks is None:
            blacfg.set("library", "directories", "")
        else:
            self.__tracks = tracks

        # Restore out-of-library tracks.
        tracks = blautil.deserialize_from_file(blaconst.OOL_PATH)
        if tracks is not None:
            self.__tracks_ool = tracks

        print_d("Restoring library: %d tracks in the library, %d additional "
                "tracks" % (len(self.__tracks), len(self.__tracks_ool)))

        self.__monitored_directories = map(os.path.realpath,
                blacfg.getdotliststr("library", "directories"))

        @blautil.idle
        def initialized(library_monitor, directories):
            if blacfg.getboolean("library", "update.on.startup"):
                p = self.__detect_changes(directories)
                gobject.idle_add(p.next)
                # TODO: this seems more efficient
#                for md in self.__monitored_directories:
#                    self.scan_directory(md)
            self.__library_monitor.disconnect(cid)
        self.__library_monitor = BlaLibraryMonitor()
        cid = self.__library_monitor.connect("initialized", initialized)
        self.__library_monitor.update_directories()

        blaplay.bla.register_for_cleanup(self)

    def add_tracks(self, uris):
        count = 0
        filt = self.__extension_filter
        add = self.add
        for uri in filter(filt, uris):
            track = get_track(uri)
            if not track:
                continue
            for md in self.__monitored_directories:
                if uri.startswith(md):
                    track[MONITORED_DIRECTORY] = md
                    add(track)
                    break
            count += 1
        return count

    def update_track(self, uri):
        track = self[uri]

        try:
            mtime = os.path.getmtime(uri)
        except OSError:
            return None
        else:
            if track[MTIME] == mtime:
                track_updated = False
            else:
                md = track[MONITORED_DIRECTORY]
                track = get_track(uri)
                if track is None:
                    return None
                track[MONITORED_DIRECTORY] = md
                self[uri] = track
                track_updated = True
        return track_updated

    # This method exclusively inserts tracks into the library. The form
    # `self[uri] = track', on the other hand, inserts it into the library only
    # if the key is already present and otherwise adds it to the ool dict.
    def add(self, track):
        uri = track.uri
        self.__tracks[uri] = track
        try:
            del self.__tracks_ool[uri]
        except KeyError:
            pass

    def move_track(self, path_from, path_to, md=""):
        # When a file is moved we create an entry for the new path in the
        # __tracks dict and move the old track to __tracks_ool. This is
        # necessary because some elements like the player, scrobbler or a
        # playlist might still try to get metadata using the old URI so we have
        # to guarantee that it's still available somewhere. The redundant data
        # will be removed from __tracks_ool on shutdown when we sync entries in
        # __tracks_ool to playlist contents.

        # Get first match for a monitored directory if no specific one is
        # given.
        if not md:
            for md in self.__monitored_directories:
                if path_to.startswith(md):
                    break
            else:
                md = ""

        # Try to get the corresponding track from the library. If it's not in
        # it we might have to try and parse it cause it could just be a rename.
        # Chromium, for instance, appends a .crdownload suffix to downloads and
        # then renames them on transfer completion.
        try:
            track = self.__tracks[path_from]
        except KeyError:
            track = get_track(path_to)
            if track:
                track[MONITORED_DIRECTORY] = md
                self.add(track)
            return

        if path_from in self.__tracks and path_from != path_to:
            self.__tracks_ool[path_from] = self.__tracks.pop(path_from)
        track[URI] = path_to
        track[MONITORED_DIRECTORY] = md
        if md:
            self.__tracks[path_to] = track
        else:
            self.__tracks_ool[path_to] = track

    def remove_track(self, uri):
        try:
            track = self.__tracks[uri]
        except KeyError:
            pass
        else:
            track[MONITORED_DIRECTORY] = ""
            self.__tracks_ool[uri] = track
            del self.__tracks[uri]

    def sync(self):
        self.__save_library()
        self.__monitored_directories = map(
            os.path.realpath, blacfg.getdotliststr("library", "directories"))
        self.emit("library_updated")
        return False

    def save_ool_tracks(self, uris):
        print_d("Saving out-of-library tracks")

        # We create a set of all OOL uris. Then we take the difference between
        # this set and the set of URIs for each playlist. The remainder will be
        # a set of URIs that weren't referenced by any playlist so we just get
        # rid of them.
        ool_uris = set(self.__tracks_ool.keys())
        for uri in ool_uris.difference(uris):
            self.__tracks_ool.pop(uri)

        p = multiprocessing.Process(
            target=blautil.serialize_to_file,
            args=(self.__tracks_ool, blaconst.OOL_PATH))
        p.start()

        @blautil.thread_nondaemonic
        def join():
            p.join()
        join()

    def parse_ool_uris(self, uris):
        # FIXME: move this to a separate process maybe?

        def process(namespace, uris, pb):
            # Update every 40 ms (25 fps).
            tid = gobject.timeout_add(40, pb.pulse)

            files = []
            filt = self.__extension_filter
            for uri in uris:
                uri = os.path.realpath(uri)
                if os.path.isdir(uri):
                    for f in blautil.discover(uri):
                        filt(f) and files.append(f)
                        yield True
                else:
                    files.append(uri)
                    yield True

            gobject.source_remove(tid)

            pb.switch_mode()
            uris = sorted(files, cmp=locale.strcoll)
            try:
                c = 1.0 / len(uris)
            except ZeroDivisionError:
                pass

            for idx, uri in enumerate(uris):
                pb.set_text(uri)
                pb.set_fraction(c * (idx+1))
                yield True

                try:
                    track = self[uri]
                except KeyError:
                    track = get_track(uri)
                    self.__tracks_ool[uri] = track
                if track:
                    namespace["uris"].append(uri)

            pb.set_fraction(1.0)
            pb.hide()
            pb.destroy()
            namespace["wait"] = False
            namespace["done"] = True
            yield False

        # FIXME: get rid of `namespace'
        def cancel(namespace):
            namespace["wait"] = False
        pb = BlaProgress(title="Scanning files...")
        pb.connect("destroy", lambda *x: cancel(namespace))
        namespace = {"uris": [], "wait": True, "done": False}
        p = process(namespace, uris, pb)
        gobject.idle_add(p.next)

        # FIXME: gtk.main_iteration() always returns True when it's called
        #        before we entered a mainloop. this prevents the following loop
        #        from properly processing all files passed to the CL on startup

        # This guarantees that we don't return before all URIs have been
        # checked, but normal event-processing still commences.
        while namespace["wait"]:
            if gtk.events_pending() and gtk.main_iteration():
                return
        return namespace["uris"] if namespace["done"] else None

    def scan_directory(self, directory):
        def scan(directory):
            t = time.time()
            print_d("Scanning `%s' and its subdirectories..." % directory)

            self.emit("progress", "pulse")
            self.__aborted = False

            checked_directories = []
            files = []

            filt = self.__extension_filter
            for f in blautil.discover(directory):
                filt(f) and files.append(f)
                if self.__aborted:
                    self.emit("progress", "abort")
                    self.__currently_scanning = None
                    namespace["wait"] = False
                    yield False
                yield True

            try:
                c = 1.0 / len(files)
            except ZeroDivisionError:
                pass

            update_track = self.update_track
            add = self.add
            for idx, path in enumerate(files):
                self.emit("progress", c * (idx+1))

                if self.__aborted:
                    self.emit("progress", "abort")
                    self.__currently_scanning = None
                    namespace["wait"] = False
                    yield False

                try:
                    track = self.__tracks[path]
                except KeyError:
                    # If track wasn't in the library check if it was in
                    # __tracks_ool (in that case it might require an update).
                    try:
                        track = self.__tracks_ool[path]
                    except KeyError:
                        track = get_track(path)
                    else:
                        if update_track(path):
                            track = self[path]

                if track and not track[MONITORED_DIRECTORY]:
                    track[MONITORED_DIRECTORY] = directory
                    add(track)
                yield True

            self.sync()
            self.__library_monitor.add_directory(directory)
            self.emit("progress", 1.0)

            print_d("Finished parsing of %d files after %.2f seconds" %
                    (len(files), (time.time() - t)))

            namespace["wait"] = False
            self.__currently_scanning = None
            yield False

        # FIXME: get rid of `namespace'
        self.__scan_queue.append(directory)
        if not self.__currently_scanning:
            while True:
                try:
                    directory = self.__scan_queue.pop(0)
                except IndexError:
                    break

                namespace = {"wait": True}
                directory = os.path.realpath(directory)
                self.__currently_scanning = directory
                p = scan(directory)
                gobject.idle_add(p.next)
                while namespace["wait"]:
                    if gtk.events_pending() and gtk.main_iteration():
                        return

    @blautil.thread
    def remove_directory(self, directory):
        directory = os.path.realpath(directory)
        while True:
            try:
                self.__scan_queue.remove(directory)
            except ValueError:
                break
        if self.__currently_scanning == directory:
            self.__aborted = True

        remove_track = self.remove_track
        tracks = [(uri, track) for uri, track in self.__tracks.iteritems()
                if track[MONITORED_DIRECTORY] == directory]
        mds = self.__monitored_directories

        try:
            mds.remove(directory)
        except ValueError:
            pass

        for uri, track in tracks:
            for md in mds:
                if uri.startswith(md):
                    self.move_track(uri, uri, md)
                    break
            else:
                remove_track(uri)

        # If there are no more monitored directories but still tracks in the
        # library something went wrong so move them to __tracks_ool as well.
        if not mds:
            map(remove_track, self.__tracks.iterkeys())
        self.sync()
        self.__library_monitor.remove_directories(directory)

library = BlaLibrary()

