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

import blaplay
from blaplay.blacore import blaconst
from blaplay import blautil
from blaplay.blagui import blaguiutil
from blaplay.formats import formats, make_track
from blaplay.formats._identifiers import *

EVENT_DELETED, EVENT_MOVED, EVENT_CHANGED = range(3)


library = None # XXX: Remove this
def init(config, path):
    print_i("Initializing the database")
    global library
    library = BlaLibrary(config, path)
    return library


# TODO: Move this to its own file.
class BlaLibraryMonitor(gobject.GObject):
    __gsignals__ = {
        "initialized": blautil.signal(1)
    }

    ignore = set()

    def __init__(self, config):
        super(BlaLibraryMonitor, self).__init__()
        self._config = config

        def create_filter_function(expression):
            if expression:
                try:
                    r = re.compile(r"%s" % expression, re.UNICODE)
                except:
                    pass
                else:
                    return r.search
            return lambda *x: False

        def on_config_changed(config, section, key):
            if section == "library" and key == "ignore.pattern":
                self._file_ignored = create_filter_function(
                    config.getstring(section, key))
        config.connect("changed", on_config_changed)
        self._file_ignored = create_filter_function(
            config.getstring("library", "ignore.pattern"))

        self._monitors = {}
        self._lock = blautil.BlaLock()
        self._queue = Queue.Queue()
        self._processing = False
        self._timeout_id = 0

        self._process_events()

    def _queue_event(self, monitor, path_from, path_to, type_):
        if type_ == gio.FILE_MONITOR_EVENT_CHANGES_DONE_HINT:
            event = EVENT_CHANGED
        elif type_ == gio.FILE_MONITOR_EVENT_DELETED:
            event = EVENT_DELETED
        elif type_ == gio.FILE_MONITOR_EVENT_MOVED:
            event = EVENT_MOVED
        else:
            if type_ == gio.FILE_MONITOR_EVENT_CREATED:
                # CREATED events are always followed by a corresponding CHANGED
                # event. Therefore, it's enough to add a file monitor to any
                # subdirectories here without explicitly queuing a CREATED
                # event.
                path = path_from.get_path()
                if os.path.isdir(path):
                    self.add_directory(path)
            return

        path_from = path_from.get_path()
        try:
            path_to = path_to.get_path()
        except AttributeError:
            pass
        # Note that this is a callable attribute, not a bound method, i.e.,
        # we don't actually dispatch on self.
        if self._file_ignored(path_from):
            return
        self._queue.put((event, path_from, path_to))

    @blautil.thread
    def _process_events(self):
        EVENTS = {
            EVENT_DELETED: "EVENT_DELETED",
            EVENT_CHANGED: "EVENT_CHANGED",
            EVENT_MOVED: "EVENT_MOVED"
        }

        while True:
            event, path_from, path_to = self._queue.get()
            print_d("New event of type `%s' for file %s (%r)" %
                    (EVENTS[event], path_from, path_to))

            if self._timeout_id:
                gobject.source_remove(self._timeout_id)
                self._timeout_id = 0

            if path_from in BlaLibraryMonitor.ignore:
                BlaLibraryMonitor.ignore.remove(path_from)
                continue

            if event == EVENT_CHANGED:
                if os.path.isfile(path_from):
                    library.add_tracks([path_from])
                else:
                    library.add_tracks(blautil.discover(path_from))

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
                len_ = len(path_from)
                try:
                    # iterating over a BlaLibrary instance uses a generator so
                    # we have to make a list of tracks to remove first
                    for uri in library:
                        if uri.startswith(path_from) and uri[len_] == "/":
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

            else:  # event == EVENT_MOVED
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
                # from blaplay.blagui.blaplaylist import BlaPlaylistManager
                # BlaPlaylistManager().update_uris(uris)

            # Schedule an update for the library browser, etc. The timeout
            # might be removed immediately at the beginning of this loop if
            # there are more events in the queue.
            library.touch()
            # XXX: The timeout has to be handled elsewhere.
            self._timeout_id = gobject.timeout_add(
                3000, self._update_library)

    def _update_library(self):
        self._timeout_id = 0
        library.commit()
        return False

    def _get_subdirectories(self, directories):
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
        directories = self._get_subdirectories(directory)

        with self._lock:
            for directory in directories:
                if directory in self._monitors:
                    continue
                f = gio.File(directory)
                monitor = f.monitor_directory(
                    flags=gio.FILE_MONITOR_NONE | gio.FILE_MONITOR_SEND_MOVED)
                monitor.connect("changed", self._queue_event)
                self._monitors[directory] = monitor

    @blautil.thread
    def remove_directories(self, md):
        with self._lock:
            for directory in sorted(self._monitors.keys()):
                if directory.startswith(md):
                    self._monitors.pop(directory).cancel()

    @blautil.thread
    def update_directories(self):
        monitored_directories = self._config.getdotliststr(
            "library", "directories")
        directories = self._get_subdirectories(monitored_directories)

        with self._lock:
            cancel = gio.FileMonitor.cancel
            map(cancel, self._monitors.itervalues())
            self._monitors.clear()

            # According to the GIO C API documentation there are backends which
            # don't support gio.FILE_MONITOR_EVENT_MOVED. However, since we
            # specifically target Linux which has inotify since kernel 2.6.13
            # we should be in the clear (that is if the kernel in use was
            # compiled with inotify support).
            for directory in directories:
                f = gio.File(directory)
                monitor = f.monitor_directory(
                    flags=gio.FILE_MONITOR_NONE | gio.FILE_MONITOR_SEND_MOVED)
                monitor.connect("changed", self._queue_event)
                self._monitors[directory] = monitor
        print_d("Now monitoring %d directories under %r" %
                (len(self._monitors), monitored_directories))
        self.emit("initialized", directories)


class BlaLibrary(gobject.GObject):
    __gsignals__ = {
        "progress": blautil.signal(1),
        "library_updated": blautil.signal(0)
    }

    def __init__(self, app, path):
        super(BlaLibrary, self).__init__()
        self._app = app
        self._path = path

        self._monitored_directories = []
        self._scan_queue = []
        self._currently_scanning = None
        self._out_of_date = False
        self._tracks = {}
        self._tracks_ool = {}
        self._playlists = []
        self._lock = blautil.BlaLock(strict=True)
        self._timeout_id = 0
        self._extension_filter = re.compile(
            r".*\.(%s)$" % "|".join(formats.keys())).match

        def on_config_changed(config, section, key):
            # TODO: It seems illogical to do this here since BlaLibrary doesn't
            #       use the restrict.to or exclude patterns. It only signals to
            #       the library browser that something changed and the model
            #       should be regenerated. Instead, let the library browser
            #       listen for changes.
            if (section == "library" and
                (key == "restrict.to.pattern" or key == "exclude.pattern")):
                if self._timeout_id:
                    gobject.source_remove(self._timeout_id)
                self._timeout_id = gobject.timeout_add(2500, self.commit)
        app.config.connect("changed", on_config_changed)

        # Restore the library.
        tracks = blautil.deserialize_from_file(self._path)
        if tracks is None:
            app.config.set("library", "directories", "")
        else:
            self._tracks = tracks

        # Restore out-of-library tracks.
        # TODO: Store the entire library under self._path.
        tracks = blautil.deserialize_from_file(blaconst.OOL_PATH)
        if tracks is not None:
            self._tracks_ool = tracks

        print_d("Restoring library: %d tracks in the library, %d additional "
                "tracks" % (len(self._tracks), len(self._tracks_ool)))

        self._monitored_directories = map(
            os.path.realpath,
            app.config.getdotliststr("library", "directories"))

        def initialized(library_monitor, directories):
            if app.config.getboolean("library", "update.on.startup"):
                p = self._detect_changes(directories)
                gobject.idle_add(p.next, priority=gobject.PRIORITY_LOW)
                # TODO: This is more efficient than the method above. However,
                #       it does not clean up missing tracks.
                # for md in self._monitored_directories:
                #     self.scan_directory(md)
            self._library_monitor.disconnect(callback_id)
        self._library_monitor = BlaLibraryMonitor(app.config)
        callback_id = self._library_monitor.connect(
            "initialized", initialized)
        # FIXME: Pass in `initialized' as a callback function instead of using
        #        a single-purpose-single-use signal.
        self._library_monitor.update_directories()

        def pre_shutdown_hook():
            print_i("Saving pending library changes")
            if self._out_of_date:
                self._save_library()
                self._out_of_date = False
        app.add_pre_shutdown_hook(pre_shutdown_hook)

    # TODO: Update the `_out_of_date` flag internally when tracks were
    #       added/updated/(re)moved to get rid of this method again.
    def touch(self):
        """Mark the library as out-of-date"""
        self._out_of_date = True

    def __getitem__(self, key):
        try:
            return self._tracks[key]
        except KeyError:
            return self._tracks_ool[key]

    def __setitem__(self, key, item):
        if self._tracks.has_key(key):
            self._tracks[key] = item
        else:
            self._tracks_ool[key] = item

    def __contains__(self, item):
        return item in self._tracks

    def __iter__(self):
        return self.next()

    def next(self):
        for uri in self._tracks.keys():
            yield uri

    def _save_library(self):
        # Pickling a large dict causes quite an increase in memory use as the
        # module basically creates an exact copy of the object in memory. To
        # combat the problem we offload the serialization of the library to
        # another process. We join the process in a separate thread to avoid
        # that the process turns into a zombie process after it terminates.
        # If the process itself is spawned from a thread this seems to deadlock
        # occasionally.
        p = multiprocessing.Process(
            target=blautil.serialize_to_file,
            args=(self._tracks, self._path))
        p.start()

        @blautil.thread_nondaemonic
        def join():
            p.join()
        join()

    def _detect_changes(self, directories):
        # XXX: We should be able to update the contents of _tracks in one go.

        # TODO: Generate three lists of tracks here: missing, new, updated
        #       ones. Then pass this list to the main process (more exactly, a
        #       waiting thread in the main process) by means of a pipe from
        #       where changes are performed on the library. The advantage of
        #       this approach is that we can off-load the heavy lifting to a
        #       secondary process and handle the "simple" stuff from a thread.

        print_i("Checking for changes in monitored directories %r" %
                self._app.config.getdotliststr("library", "directories"))

        yield_interval = 25

        # Update out-of-library tracks.
        update_track = self.update_track
        for idx, uri in enumerate(self._tracks_ool.keys()):
            update_track(uri)
            if idx % yield_interval == 0:
                yield True

        # Check for new tracks or tracks in need of updating in monitored
        # directories.
        remove_track = self.remove_track
        updated = 0
        missing = 0
        for idx, uri in enumerate(self):
            try:
                updated += int(update_track(uri))
            except TypeError:
                remove_track(uri)
                missing += 1
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

        print_i("%d files missing, %d new ones, %d updated" %
                (missing, new_files, updated))

        # FIXME: This is really ugly, as the library shouldn't even have to
        #        know about the existence of a window.
        # Finally update the model for the library browser and playlists. The
        # GUI might not be fully initialized yet, so wait for that to happen
        # before requesting an update.
        while self._app.window is None:
            yield True
        library.commit()
        yield False

    # This method exclusively inserts tracks into the library. The form
    # `self[uri] = track', on the other hand, inserts it into the library only
    # if the key is already present and otherwise adds it to the ool dict.
    def add_track(self, track):
        uri = track.uri
        self._tracks[uri] = track
        try:
            del self._tracks_ool[uri]
        except KeyError:
            pass

    def add_tracks(self, uris):
        count = 0
        filt = self._extension_filter
        add_track = self.add_track
        for uri in filter(filt, uris):
            track = make_track(uri)
            if not track:
                continue
            for md in self._monitored_directories:
                if uri.startswith(md):
                    track[MONITORED_DIRECTORY] = md
                    add_track(track)
                    break
            count += 1
        return count

    def update_track(self, uri):
        """
        Updates a track in the library if necessary and returns a boolean value
        to indicate whether the track was updated or not. Returns None if `uri'
        refers to a non-existent resource or the resource's format is not
        supported.
        """
        try:
            mtime = os.path.getmtime(uri)
        except OSError:
            return None

        track = self[uri]
        if track[MTIME] == mtime:
            track_updated = False
        else:
            md = track[MONITORED_DIRECTORY]
            track = make_track(uri) # Get a new BlaTrack from `uri'.
            if track is None:
                return None
            track[MONITORED_DIRECTORY] = md
            self[uri] = track
            track_updated = True
        return track_updated

    def move_track(self, path_from, path_to, md=""):
        # When a file is moved we create an entry for the new path in the
        # _tracks dict and move the old track to _tracks_ool. This is
        # necessary because some elements like the player, scrobbler or a
        # playlist might still try to get metadata using the old URI so we have
        # to guarantee that it's still available somewhere. The redundant data
        # will be removed from _tracks_ool on shutdown when we sync entries in
        # _tracks_ool to playlist contents.

        # Get first match for a monitored directory if no specific one is
        # given.
        if not md:
            for md in self._monitored_directories:
                if path_to.startswith(md):
                    break
            else:
                md = ""

        # Try to get the corresponding track from the library. If it's not in
        # it we might have to try and parse it cause it could just be a rename.
        # Chromium, for instance, appends a .crdownload suffix to downloads and
        # then renames them on transfer completion.
        try:
            track = self._tracks[path_from]
        except KeyError:
            track = make_track(path_to)
            if track:
                track[MONITORED_DIRECTORY] = md
                self.add_track(track)
            return

        if path_from in self._tracks and path_from != path_to:
            self._tracks_ool[path_from] = self._tracks.pop(path_from)
        track[URI] = path_to
        track[MONITORED_DIRECTORY] = md
        if md:
            self._tracks[path_to] = track
        else:
            self._tracks_ool[path_to] = track

    def remove_track(self, uri):
        try:
            track = self._tracks[uri]
        except KeyError:
            pass
        else:
            track[MONITORED_DIRECTORY] = ""
            self._tracks_ool[uri] = track
            del self._tracks[uri]

    def commit(self):
        self._save_library()
        self._monitored_directories = map(
            os.path.realpath,
            self._app.config.getdotliststr("library", "directories"))
        self.emit("library_updated")
        self._timeout_id = 0
        return False

    def save_ool_tracks(self, uris):
        print_d("Saving out-of-library tracks")

        # We create a set of all OOL uris. Then we take the difference between
        # this set and the set of URIs for each playlist. The remainder will be
        # a set of URIs that weren't referenced by any playlist so we just get
        # rid of them.
        ool_uris = set(self._tracks_ool.keys())
        for uri in ool_uris.difference(uris):
            self._tracks_ool.pop(uri)

        p = multiprocessing.Process(
            target=blautil.serialize_to_file,
            args=(self._tracks_ool, blaconst.OOL_PATH))
        p.start()

        @blautil.thread_nondaemonic
        def join():
            p.join()
        join()

    def parse_ool_uris(self, uris):
        # TODO: Test if it is faster to move this to a separate process.

        def process(namespace, uris, pb):
            # Update every 40 ms (25 fps).
            timeout_id = gobject.timeout_add(40, pb.pulse)

            files = []
            filt = self._extension_filter
            for uri in uris:
                uri = os.path.realpath(uri)
                if os.path.isdir(uri):
                    for f in blautil.discover(uri):
                        filt(f) and files.append(f)
                        yield True
                else:
                    files.append(uri)
                    yield True

            gobject.source_remove(timeout_id)

            pb.switch_mode()
            uris = sorted(files, cmp=locale.strcoll)
            try:
                step_size = 1.0 / len(uris)
            except ZeroDivisionError:
                pass

            for idx, uri in enumerate(uris):
                pb.set_text(uri)
                pb.set_fraction(step_size * (idx+1))
                yield True

                try:
                    track = self[uri]
                except KeyError:
                    track = make_track(uri)
                    self._tracks_ool[uri] = track
                if track:
                    namespace["uris"].append(uri)

            pb.set_fraction(1.0)
            pb.hide()
            pb.destroy()
            namespace["wait"] = False
            namespace["done"] = True
            yield False

        # FIXME: Get rid of `namespace'
        def cancel(namespace):
            namespace["wait"] = False
        pb = blaguiutil.BlaProgressBar(title="Scanning files...")
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
            self._aborted = False

            checked_directories = []
            files = []

            filt = self._extension_filter
            for f in blautil.discover(directory):
                filt(f) and files.append(f)
                if self._aborted:
                    self.emit("progress", "abort")
                    self._currently_scanning = None
                    namespace["wait"] = False
                    yield False
                yield True

            try:
                step_size = 1.0 / len(files)
            except ZeroDivisionError:
                pass

            update_track = self.update_track
            add_track = self.add_track
            for idx, path in enumerate(files):
                self.emit("progress", step_size * (idx+1))

                if self._aborted:
                    self.emit("progress", "abort")
                    self._currently_scanning = None
                    namespace["wait"] = False
                    yield False

                try:
                    track = self._tracks[path]
                except KeyError:
                    # If track wasn't in the library check if it was in
                    # _tracks_ool. In that case it might require an update as
                    # we don't monitor such tracks.
                    try:
                        track = self._tracks_ool[path]
                    except KeyError:
                        track = make_track(path)
                    else:
                        if update_track(path):
                            track = self[path]

                if track and not track[MONITORED_DIRECTORY]:
                    track[MONITORED_DIRECTORY] = directory
                    add_track(track)
                yield True

            self.commit()
            self._library_monitor.add_directory(directory)
            self.emit("progress", 1.0)

            print_d("Finished parsing of %d files after %.2f seconds" %
                    (len(files), (time.time() - t)))

            namespace["wait"] = False
            self._currently_scanning = None
            yield False

        # FIXME: get rid of `namespace'
        self._scan_queue.append(directory)
        if not self._currently_scanning:
            while True:
                try:
                    directory = self._scan_queue.pop(0)
                except IndexError:
                    break

                namespace = {"wait": True}
                directory = os.path.realpath(directory)
                self._currently_scanning = directory
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
                self._scan_queue.remove(directory)
            except ValueError:
                break
        if self._currently_scanning == directory:
            self._aborted = True

        remove_track = self.remove_track
        tracks = [(uri, track) for uri, track in self._tracks.iteritems()
                if track[MONITORED_DIRECTORY] == directory]
        mds = self._monitored_directories

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
        # library something went wrong so move them to _tracks_ool as well.
        if not mds:
            map(remove_track, self._tracks.iterkeys())
        self.commit()
        self._library_monitor.remove_directories(directory)
