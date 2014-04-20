# blaplay, Copyright (C) 2012-2014  Niklas Koep

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

import functools
import os
import re

import gtk

from blaplay import blautil
from blaplay.blacore import blaconst
from .blaviewmanager import BlaViewManager
from .blaplaylist import BlaPlaylist
from . import blaplaylistutils
from .. import blaguiutils


class BlaPlaylistManager(BlaViewManager):
    ID = blaconst.VIEW_PLAYLIST

    def __init__(self, *args, **kwargs):
        super(BlaPlaylistManager, self).__init__(*args, **kwargs)

        self.current_item = None # Reference to the currently playing track
        # TODO: Implement this properly on top of gtk.Clipboard. At the very
        #       least, move it up the dependency chain so that we can share the
        #       clipboard on application level. For instance, it should be
        #       possible to cut tracks from a playlist and paste them directly
        #       into the queue.
        self.clipboard = [] # List of items after a cut/copy operation

        self._player.connect_object(
            "state-changed", BlaPlaylistManager._on_state_changed, self)
        self._player.connect_object(
            "get-track", BlaPlaylistManager.get_track, self)

        # XXX: Move this somewhere else.
        def library_updated(*args):
            for playlist in self.views:
                playlist.invalidate_visible_rows()
        self._library.connect("library_updated", library_updated)

    def _on_state_changed(self):
        playlist = self._get_active_playlist()
        if playlist is not None:
            state = self._player.get_state()
            if state == blaconst.STATE_PLAYING:
                stock_id = gtk.STOCK_MEDIA_PLAY
            elif state == blaconst.STATE_PAUSED:
                stock_id = gtk.STOCK_MEDIA_PAUSE
            else:
                stock_id = gtk.STOCK_MEDIA_STOP
            playlist.set_state_icons(stock_id)

    def _prompt_for_name(self, title, default=""):
        diag = blaguiutils.BlaDialog(title=title)
        vbox = gtk.VBox(spacing=5)
        vbox.set_border_width(10)
        entry = gtk.Entry()
        entry.set_text(default)
        entry.connect("activate", lambda *x: diag.response(gtk.RESPONSE_OK))
        label = gtk.Label("Title:")
        label.set_alignment(xalign=0.0, yalign=0.5)
        vbox.pack_start(label)
        vbox.pack_start(entry)
        diag.vbox.pack_start(vbox)
        diag.show_all()

        # Run the dialog until we got a valid name or the user aborted.
        name = ""
        while not name.strip():
            response = diag.run()
            if response != gtk.RESPONSE_OK:
                break
            name = entry.get_text()
            if not name.strip():
                # FIXME: If this dialog is present when we quit we get a
                #        weird assertion which doesn't seem to have
                #        anything to do with this line, followed by a
                #        segfault.
                blaguiutils.error_dialog(
                    text="Invalid playlist name",
                    secondary_text="A playlist name must not consist "
                                    "exclusively of whitespace "
                                    "characters.")
        diag.destroy()
        return name

    def _build_generic_name(self):
        indices = set()
        r = re.compile(r"(^bla\s\()([0-9]+)\)")
        for playlist in self.views:
            name = playlist.name

            if name == "bla":
                indices.add(0)
            else:
                try:
                    num = r.match(name).group(2)
                except AttributeError:
                    continue
                num = int(num)
                if num > 0:
                    indices.add(num)

        name = "bla"
        if indices and 0 in indices:
            indices = list(indices)
            candidates = range(min(indices), max(indices) + 2)
            candidates = list(set(candidates).difference(indices))
            if candidates:
                idx = candidates[0]
            else:
                idx = indices[-1]
            name += " (%d)" % idx
        return name

    def _rename_playlist(self, playlist):
        name = self._prompt_for_name("Rename playlist", default=playlist.name)
        if name:
            playlist.set_name(name)

    def add_playlist(self, name=None, prompt_for_name=False,
                     request_focus=False):
        if prompt_for_name:
            name = self._prompt_for_name("Playlist name")
            if not name:
                return None
        elif not name:
            name = self._build_generic_name()
        assert not not name, "Playlist name missing"

        playlist = BlaPlaylist(name, self)
        self.views.append(playlist)
        self._notify_add(playlist)
        if request_focus:
            self._notify_focus(playlist)
        return playlist

    def create_view(self):
        self.add_playlist(request_focus=True)

    def populate_context_menu(self, menu, playlist):
        def new_playlist(*args):
            self.add_playlist(prompt_for_name=True, request_focus=True)
        menu.append_item("New playlist...", new_playlist)

        if playlist is not None:
            menu.append_item("Rename...", self._rename_playlist, playlist)

        super(BlaPlaylistManager, self).populate_context_menu(menu, playlist)

    def update_statusbar(self, playlist):
        self._notify_status(playlist)

    def update_playlist_layout(self):
        for playlist in self.views:
            playlist.refresh_column_layout()

    def _set_file_chooser_directory(self, diag):
        directory = self._config.getstring("general", "filechooser.directory")
        if not directory or not os.path.isdir:
            directory = os.path.expanduser("~")
        diag.set_current_folder(directory)

    def open_playlist(self):
        diag = gtk.FileChooserDialog(
            "Select playlist", buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                        gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        diag.set_local_only(True)
        self._set_file_chooser_directory(diag)

        response = diag.run()
        path = diag.get_filename()
        self._config.set_("general", "filechooser.directory",
                          diag.get_current_folder())
        diag.destroy()

        if response != gtk.RESPONSE_OK or not path:
            return

        name = os.path.basename(blautil.toss_extension(path))
        ext = blautil.get_extension(path).lower()
        if ext == "m3u":
            uris = blaplaylistutils.m3u_parse(path)
        elif ext == "pls":
            uris = blaplaylistutils.pls_parse(path)
        elif ext == "xspf":
            name, uris = blaplaylistutils.xspf_parse(path)
        else:
            blaguiutils.error_dialog(
                "Failed to open playlist \"%s\"" % path,
                "Only M3U, PLS, and XSPF playlists are supported.")
            return
        if uris is None:
            return

        uris = self._library.parse_ool_uris(blautil.resolve_uris(uris))
        if uris is None:
            return
        playlist = self.add_playlist(name=name, request_focus=True)
        playlist.add_items(self.create_items_from_uris(uris))

    def _run_file_chooser_dialog(self, action, playlist):
        diag = gtk.FileChooserDialog(
            "Select files", action=action,
            buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN,
                     gtk.RESPONSE_OK))
        diag.set_select_multiple(True)
        diag.set_local_only(True)
        self._set_file_chooser_directory(diag)
        response = diag.run()
        filenames = diag.get_filenames()
        self._config.set_("general", "filechooser.directory",
                          diag.get_current_folder())
        diag.destroy()

        if response == gtk.RESPONSE_OK and filenames:
            filenames = map(str.strip, filenames)
            uris = self._library.parse_ool_uris(filenames)
            self.add_uris_to_playlist(playlist, uris)

    def add_files_to_playlist(self, playlist):
        self._run_file_chooser_dialog(gtk.FILE_CHOOSER_ACTION_OPEN, playlist)

    def add_directories_to_playlist(self, playlist):
        self._run_file_chooser_dialog(
            gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER, playlist)

    def save_playlist(self, playlist):
        @blautil.thread
        def write_to_file(path, type_, store_relative_paths):
            name = playlist.name
            tracks = playlist.get_all_tracks()

            ext = blautil.get_extension(path)
            if ext.lower() != type_:
                path = "%s.%s" % (path, type_)

            if type_.lower() == "pls":
                writefunc = blaplaylistutils.pls_write
            elif type_.lower() == "xspf":
                writefunc = blaplaylistutils.xspf_write
            else:
                writefunc = blaplaylistutils.m3u_write
            writefunc(path, name, tracks, store_relative_paths)

        diag = gtk.FileChooserDialog(
            "Save playlist", action=gtk.FILE_CHOOSER_ACTION_SAVE,
            buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_SAVE,
                     gtk.RESPONSE_OK))
        diag.set_do_overwrite_confirmation(True)
        self._set_file_chooser_directory(diag)

        items = [
            ("M3U", "audio/x-mpegurl", "m3u"),
            ("PLS", "audio/x-scpls", "pls", ),
            ("XSPF", "application/xspf+xml", "xspf"),
            ("Choose by extension", None, None)
        ]
        for label, mime_type, extension in items:
            filt = gtk.FileFilter()
            filt.set_name(label)
            filt.add_pattern("*.%s" % extension)
            if mime_type:
                filt.add_mime_type(mime_type)
            diag.add_filter(filt)

        # Add combobox to the dialog to choose whether to save relative or
        # absolute paths in the playlist.
        box = diag.child
        hbox = gtk.HBox()
        cb = gtk.combo_box_new_text()
        hbox.pack_end(cb, expand=False, fill=False)
        box.pack_start(hbox, expand=False, fill=False)
        box.show_all()
        for option in ["Absolute paths", "Relative paths"]:
            cb.append_text(option)
        cb.set_active(0)

        response = diag.run()
        path = diag.get_filename()

        if response == gtk.RESPONSE_OK and path:
            filt = diag.get_filter()
            type_ = items[diag.list_filters().index(filt)][-1]
            path = path.strip()
            if type_ is None:
                type_ = blautil.get_extension(path)
            store_relative_paths = cb.get_active() == 1
            write_to_file(path, type_, store_relative_paths)
            self._config.set_("general", "filechooser.directory",
                              os.path.dirname(path))
        diag.destroy()

    def _scroll_to_current_item(self):
        playlist = self._get_active_playlist()
        if playlist is not None:
            playlist.set_row(playlist.get_path_from_item(self.current_item))

    def _unset_current_item(self):
        playlist = self._get_active_playlist()
        if playlist is not None:
            playlist.set_state_icons(None)
        self.current_item = None

    def _get_active_playlist(self):
        """
        Returns the playlist containing the currently playing track or None if
        the track is not part of a playlist or the player is stopped.
        """

        current_item = self.current_item
        if current_item is not None:
            for playlist in self.views:
                if current_item in playlist:
                    return playlist
        return None

    def save(self, path=None, type_="m3u", relative=False):
        if path is None:
            # TODO: Save the queue individually.
            print_i("Saving playlists")
            playlists = self.get_playlists()

            active_playlist = self._get_active_playlist()
            if active_playlist:
                current = active_playlist.get_path_from_item(self.current)
                active_playlist = self.page_num(active_playlist)
            else:
                active_playlist = current = None

            uris = set()
            for playlist in playlists:
                uris.update(playlist.get_all_uris())
            self._library.save_ool_tracks(uris)
            blautil.serialize_to_file(
                (playlists, active_playlist, current, queue.get_queue()),
                blaconst.PLAYLISTS_PATH)
        else:
            save(path, type_)

    # def init(self):
    #     print_i("Restoring playlists")

    #     try:
    #         playlists, active_playlist, current, queued_items = (
    #             blautil.deserialize_from_file(blaconst.PLAYLISTS_PATH))
    #     except (TypeError, ValueError):
    #         playlists = []

    #     if playlists:
    #         for playlist in playlists:
    #             self.append_page(playlist, playlist.get_label())

    #         if active_playlist is not None:
    #             self.set_current_page(active_playlist)
    #             playlist = self.get_nth_page(active_playlist)
    #             playlist.set_active(True)
    #         if current is not None:
    #             self.current = playlist.get_item_from_path(current)
    #             self._scroll_to_current_item()
    #         queue.restore(queued_items)
    #     else:
    #         self.add_playlist()

    def remove_view(self, playlist):
        # Chain up first and see if the playlist was removed.
        if not super(BlaPlaylistManager, self).remove_view(playlist):
            return

        if self._get_active_playlist() == playlist:
            try:
                self.current_item.playlist = None
            except AttributeError:
                pass
        playlist.clear()

    def send_uris_to_playlist(self, playlist, uris):
        if not uris:
            return
        if not playlist.can_modify():
            return
        # We want to start playing from this playlist immediately so mark the
        # the playlist holding the currently playing track as inactive.
        self._unset_current_item()
        playlist.clear()
        playlist.add_items(self.create_items_from_uris(uris))
        self.get_track(blaconst.TRACK_NEXT, force_advance=False,
                       playlist=playlist)
        self._notify_focus(playlist)

    def add_uris_to_playlist(self, playlist, uris):
        if not uris:
            return
        if not playlist.can_modify():
            return
        playlist.add_items(self.create_items_from_uris(uris), select_rows=True)
        self._notify_focus(playlist)

    def send_uris_to_new_playlist(self, uris, name=None, select_rows=False):
        if not uris:
            return
        items = self.create_items_from_uris(uris)
        playlist = self.add_playlist(name=name, request_focus=True)
        playlist.add_items(items, select_rows=select_rows)

    # XXX: Remove this once we use unique IDs instead of URIs to identify
    #      tracks inside the library.
    def update_uris(self, uris):
        for playlist in self.views:
            playlist.update_uris(uris)

    def get_track(self, choice, force_advance, playlist=None):
        # XXX: The `playlist' kwarg is a temporary hack to allow
        #      `send_uris_to_playlist()' to play tracks from an explicit
        #      playlist. What we actually want is to ask the tab view for the
        #      currently visible playlist and get a new track from there. This
        #      is particularly desired when `get_track' gets called after a
        #      STATE_STOPPED -> STATE_PLAYING transition. Right now, we always
        #      choose the first playlist when this happens.

        if playlist is None:
            playlist = self._get_active_playlist()
            if playlist is None:
                assert len(self.views) > 0
                playlist = self.views[0]
        item = playlist.get_item(choice, force_advance)
        self.play_item(item)

    def play_item(self, item):
        self._unset_current_item()

        self.current_item = item
        try:
            uri = item.uri
        except AttributeError:
            uri = None
        else:
            if self._config.getboolean("general", "cursor.follows.playback"):
                self._scroll_to_current_item()
        self._player.play_track(uri)

    def focus_playlist(self, playlist):
        self._notify_focus(playlist)

    def jump_to_playing_track(self):
        if self.current_item is None:
            return
        playlist = self._get_active_playlist()
        playlist.jump_to_track(self.current_item)
        self.focus_playlist(playlist)

    def create_items_from_uris(self, uris):
        # XXX: Ugly, the playlist manager shouldn't have to know about the
        #      existence of BlaTrackListItem.
        from .blatracklist import BlaTrackListItem as cls
        library = self._library
        return [cls(library[uri]) for uri in uris]

