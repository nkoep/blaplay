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
        "initialized": blautil.signal(0)
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

        # TODO: Instead of modifying the library explicitly here, create
        #       "delta" lists much like we do in BlaLibrary's `_detect_changes`
        #       method. Then forward these updates to the library by emitting
        #       a signal.

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
                if path_from in self._monitors:  # a directory was removed
                    for uri in self._library:
                        if uri.startswith(path_from):
                            self._library.remove_track(uri)
                    self.remove_directory(path_from)
                else:
                    self._library.remove_track(path_from)

            else:  # event == EVENT_MOVED
                # TODO: Pass `moved_files` on to the library to perform the
                #       actual moves.
                moved_files = {}
                if os.path.isfile(path_to):
                    self._library.move_track(path_from, path_to)
                    moved_files[path_from] = path_to
                else:
                    for uri in self._library:
                        if uri.startswith(path_from):
                            new_path = os.path.join(
                                path_to, uri[len(path_from)+1:])
                            self._library.move_track(uri, new_path)
                            moved_files[uri] = new_path

                    self.remove_directory(path_from)
                    self.add_directory(path_to)

            # Schedule an update for the library browser, etc. The timeout
            # might be removed immediately at the beginning of this loop if
            # there are more events in the queue.
            self._library.touch()
            self._timeout_id = gobject.timeout_add(3000, self._update_library)

    def _update_library(self):
        self._timeout_id = 0
        self._library.commit()
        return False

    def _get_subdirectories(self, directories):
        # The heavy lifting here is actually just getting a list of all the
        # directories which need a monitor. The creation of the monitors itself
        # is rather simple. To circumvent the GIL when getting the directory
        # list we use another process, even though a generator would be more
        # memory efficient.
        @blautil.daemon_process
        def get_subdirectories(pipe, directories):
            # KeyboardInterrupt exceptions need to be handled in child
            # processes. Since this is no crucial operation we can just return.
            try:
                directories = list(
                    blautil.discover(directories, directories_only=True))
                pipe.send(directories)
            except KeyboardInterrupt:
                pass

        pipe1, pipe2 = multiprocessing.Pipe(duplex=False)
        process = get_subdirectories(pipe2, directories)
        directories = pipe1.recv()
        process.join()
        return directories

    def _create_monitor(self, directory):
        file_ = gio.File(directory)
        monitor = file_.monitor_directory(
            flags=(gio.FILE_MONITOR_NONE | gio.FILE_MONITOR_SEND_MOVED))
        monitor.connect("changed", self._queue_event)
        self._monitors[directory] = monitor

    @blautil.thread
    def initialize(self):
        monitored_directories = self._config.getdotliststr(
            "library", "directories")
        directories = self._get_subdirectories(monitored_directories)
        with self._lock:
            cancel = gio.FileMonitor.cancel
            map(cancel, self._monitors.itervalues())
            self._monitors.clear()
            for directory in directories:
                self._create_monitor(directory)

        print_d("Monitoring %d directories under %r" %
                (len(self._monitors), monitored_directories))
        self.emit("initialized")

    @blautil.thread
    def add_directory(self, directory):
        """Monitor `directory` and all its subdirectories."""
        directories = self._get_subdirectories(directory)
        with self._lock:
            for directory in directories:
                if directory in self._monitors:
                    continue
                self._create_monitor(directory)

    @blautil.thread
    def remove_directory(self, directory):
        """Remove monitor for `directory` and all its subdirectories."""
        with self._lock:
            for d in sorted(self._monitors):
                if d.startswith(directory):
                    monitor = self._monitors.pop(d)
                    monitor.cancel()
