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
import re
import Queue
import multiprocessing

import gobject
import gio

from blaplay import blautil

EVENT_DELETED, EVENT_MOVED, EVENT_CHANGED = range(3)


class BlaLibraryMonitor(gobject.GObject):
    __gsignals__ = {
        "initialized": blautil.signal(1)
    }

    def __init__(self, config, library):
        super(BlaLibraryMonitor, self).__init__()
        self._config = config
        self._library = library

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
                self._should_ignore_file = create_filter_function(
                    config.getstring(section, key))
        config.connect("changed", on_config_changed)
        self._should_ignore_file = create_filter_function(
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
        if self._should_ignore_file(path_from):
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

            if event == EVENT_CHANGED:
                if os.path.isfile(path_from):
                    self._library.add_tracks([path_from])
                else:
                    self._library.add_tracks(blautil.discover(path_from))

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
                    for uri in self._library:
                        if uri.startswith(path_from) and uri[len_] == "/":
                            self._library.remove_track(uri)
                except IndexError:
                    # IndexError will only be raised for exact matches, meaning
                    # we removed a file.
                    self._library.remove_track(uri)
                else:
                    # If we made it this far we didn't get an exact match so
                    # we removed a directory. In this case we remove every file
                    # monitor under the given directory.
                    self.remove_directories(path_from)

            else:  # event == EVENT_MOVED
                uris = {}
                if os.path.isfile(path_to):
                    self._library.move_track(path_from, path_to)
                    uris[path_from] = path_to
                else:
                    for uri in self._library:
                        if uri.startswith(path_from):
                            new_path = os.path.join(
                                path_to, uri[len(path_from)+1:])
                            self._library.move_track(uri, new_path)
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
            self._library.touch()
            # XXX: The timeout has to be handled elsewhere.
            self._timeout_id = gobject.timeout_add(
                3000, self._update_library)

    def _update_library(self):
        self._timeout_id = 0
        self._library.commit()
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
                directories = list(
                    blautil.discover(directories, directories_only=True))
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
        # TODO: This is largely identical to update_directories so combine the
        #       two methods.
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
