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
import multiprocessing

import gobject
import gtk

import blaplay
from blaplay import blautil
from blaplay.blacore import blaconst
from blaplay.blacore.blalibrarymonitor import BlaLibraryMonitor
from blaplay.blagui import blaguiutil
from blaplay.formats import formats, make_track
from blaplay.formats._identifiers import *


library = None  # XXX: Remove this
def init(config, path):
    print_i("Initializing the database")
    global library
    library = BlaLibrary(config, path)
    return library


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

        self._library_monitor = BlaLibraryMonitor(app.config, self)
        self._callback_id = self._library_monitor.connect_object(
            "initialized", BlaLibrary._on_library_monitor_initialized, self)
        self._library_monitor.initialize()

        def pre_shutdown_hook():
            print_i("Saving pending library changes")
            if self._out_of_date:
                self._save_library()
                self._out_of_date = False
        app.add_pre_shutdown_hook(pre_shutdown_hook)

    # TODO: Call this method in regular intervals so as to keep the library
    #       up-to-date all the time in case the filesystem monitor misses some
    #       events.
    def _on_library_monitor_initialized(self):
        if self._app.config.getboolean("library", "update.on.startup"):
            pipe1, pipe2 = multiprocessing.Pipe(duplex=False)
            p = multiprocessing.Process(target=self._detect_changes,
                                        args=(pipe2,))
            p.daemon = True
            p.start()
            @blautil.thread
            def join():
                modified_tracks, missing_tracks, new_tracks = pipe1.recv()
                p.join()
                self._update_library_contents(modified_tracks, missing_tracks,
                                              new_tracks)
            join()
        self._library_monitor.disconnect(self._callback_id)
        del self._callback_id

    @blautil.thread
    def _update_library_contents(self, modified_tracks, missing_tracks,
                                 new_tracks):
        for track in modified_tracks:
            # This updates a track either in the library or the OOL dict.
            self[track.uri] = track

        for uri in missing_tracks:
            self.remove_track(uri)

        for track in new_tracks:
            # This exclusively adds new tracks to the library and possibly
            # purges them from the OOL dict.
            self.add_track(track)

        print_i("%d files missing, %d new ones, %d updated" %
                (len(missing_tracks), len(new_tracks), len(modified_tracks)))

        library.commit()

    # TODO: Update the `_out_of_date` flag internally when tracks were
    #       added/updated/(re)moved to get rid of this method again.
    def touch(self):
        """Mark the library as out-of-date."""
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

    def _detect_changes(self, pipe):
        monitored_directories = self._app.config.getdotliststr(
            "library", "directories")
        print_i("Checking for changes in monitored directories %r" %
                monitored_directories)

        # Check out-of-library tracks. We don't remove metadata for missing OOL
        # tracks here since we still might need it in certain places.
        modified_tracks = []
        missing_tracks = []
        for uri, track in self._tracks_ool.iteritems():
            if track.exists() and track.was_modified():
                new_track = make_track(uri)
                if new_track is not None:
                    modified_tracks.append(new_track)
        # Check library tracks.
        for uri, track in self._tracks.iteritems():
            if track.exists():
                if track.was_modified():
                    new_track = make_track(uri)
                    if new_track is not None:
                        modified_tracks.append(new_track)
            else:
                missing_tracks.append(uri)

        # Check for new tracks in the monitored directories.
        new_tracks = []
        for directory in monitored_directories:
            for uri in blautil.discover(directory):
                if uri not in self:
                    track = make_track(uri)
                    if track is not None:
                        track[MONITORED_DIRECTORY] = directory
                        new_tracks.append(track)

        pipe.send((modified_tracks, missing_tracks, new_tracks))

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
            for monitored_directory in self._monitored_directories:
                if uri.startswith(monitored_directory):
                    track[MONITORED_DIRECTORY] = monitored_directory
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
        track = self[uri]
        if not track.exists():
            return None

        if track.was_modified():
            monitored_directory = track[MONITORED_DIRECTORY]
            track = make_track(uri)
            if track is None:
                return None
            track[MONITORED_DIRECTORY] = monitored_directory
            self[uri] = track
            track_updated = True
        else:
            track_updated = False
        return track_updated

    def move_track(self, path_from, path_to, monitored_directory=""):
        # When a file is moved we create an entry for the new path in the
        # _tracks dict and move the old track to _tracks_ool. This is
        # necessary because some elements like the player, scrobbler or a
        # playlist might still try to get metadata using the old URI so we have
        # to guarantee that it's still available somewhere. The redundant data
        # will be removed from _tracks_ool on shutdown when we sync entries in
        # _tracks_ool to playlist contents.

        # Get first match for a monitored directory if no specific one is
        # given.
        if not monitored_directory:
            for directory in self._monitored_directories:
                if path_to.startswith(monitored_directory):
                    monitored_directory = directory
                    break

        # Try to get the corresponding track from the library. If it's not in
        # it we might have to try and parse it cause it could just be a rename.
        # Chromium, for instance, appends a .crdownload suffix to downloads and
        # then renames them on transfer completion.
        try:
            track = self._tracks[path_from]
        except KeyError:
            track = make_track(path_to)
            if track:
                track[MONITORED_DIRECTORY] = monitored_directory
                self.add_track(track)
            return

        if path_from in self._tracks and path_from != path_to:
            self._tracks_ool[path_from] = self._tracks.pop(path_from)
        track[URI] = path_to
        track[MONITORED_DIRECTORY] = monitored_directory
        if monitored_directory:
            self._tracks[path_to] = track
        else:
            self._tracks_ool[path_to] = track

    def remove_track(self, uri):
        """
        Remove track with URI `uri` from the library. Note that this merely
        moves the track to the OOL dictionary so we still have access to the
        tracks metadata if needed. This OOL dict then gets cleaned up when
        blaplay shuts down.
        """
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

        try:
            self._monitored_directories.remove(directory)
        except ValueError:
            pass

        for uri, track in tracks:
            for monitored_directory in self._monitored_directories:
                if uri.startswith(monitored_directory):
                    self.move_track(uri, uri, monitored_directory)
                    break
            else:
                remove_track(uri)

        # If there are no more monitored directories but still tracks in the
        # library something went wrong so move them to _tracks_ool as well.
        if not self._monitored_directories:
            map(remove_track, self._tracks.iterkeys())
        self.commit()
        self._library_monitor.remove_directory(directory)
