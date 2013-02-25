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

import gobject
import gtk

import blaplay
player = blaplay.bla.player
library = blaplay.bla.library
from blaplay.blacore import blaconst, blacfg
from blaplay import blautil, blagui
from blaplay.formats._identifiers import *
from blaplay.blagui import blaguiutils, blapreferences
from blakeys import BlaKeys
from blatoolbar import BlaToolbar
from blabrowsers import BlaBrowsers
from blaplaylist import BlaPlaylistManager
from blavisualization import BlaVisualization
from blaview import BlaView
from blastatusbar import BlaStatusbar
from blapreferences import BlaPreferences
from blaabout import BlaAbout


class BlaMainWindow(blaguiutils.BlaBaseWindow):
    def __init__(self):
        super(BlaMainWindow, self).__init__(gtk.WINDOW_TOPLEVEL)

        gtk.window_set_default_icon_name(blaconst.APPNAME)
        self.set_resizable(True)
        self.connect("delete_event", self.__delete_event)
        self.enable_tracking(is_main_window=True)

        # Install global mouse hook.
        def button_press_hook(receiver, event):
            if event.button == 8:
                player.previous()
            elif event.button == 9:
                player.next()
            return True
        gobject.add_emission_hook(self, "button_press_event",
                                  button_press_hook)

        # Main menu
        blagui.uimanager = uimanager = gtk.UIManager()
        blagui.accelgroup = uimanager.get_accel_group()
        self.add_accel_group(blagui.accelgroup)
        actiongroup = gtk.ActionGroup("blagui-actions")

        actions = [
            # Menus and submenus
            ("File", None, "_File"),
            ("Edit", None, "_Edit"),
            ("Select", None, "S_elect"),
            ("Selection", None, "Se_lection"),
            ("NewPlaylistFrom", None, "_New playlist from"),
            ("PlayOrder", None, "_Order"),
            ("View", None, "_View"),
            ("Help", None, "_Help"),

            # Menu items
            ("OpenPlaylist", None, "Open playlist...", None, "",
             self.__open_playlist),
            ("AddFiles", None, "Add _files...", None, "",
             lambda *x: self.__add_tracks()),
            ("AddDirectories", None, "_Add directories...", None, "",
             lambda *x: self.__add_tracks(files=False)),
            ("SavePlaylist", None, "_Save playlist...", None, "",
             self.__save_playlist),
            ("AddNewPlaylist", None, "Add new playlist", "<Ctrl>T", "",
             lambda *x: BlaPlaylistManager.add_playlist(focus=True)),
            ("RemovePlaylist", None, "Remove playlist", "<Ctrl>W", "",
             lambda *x: BlaPlaylistManager.remove_playlist()),
            ("Quit", gtk.STOCK_QUIT, "_Quit", "<Ctrl>Q", "", self.quit),
            ("Clear", None, "_Clear", None, "", BlaView.clear),
            ("LockUnlockPlaylist", None, "Lock/Unlock playlist", None, "",
             BlaPlaylistManager.toggle_lock_playlist),
            ("SelectAll", None, "All", None, "",
             lambda *x: BlaView.select(blaconst.SELECT_ALL)),
            ("SelectComplement", None, "Complement", None, "",
             lambda *x: BlaView.select(blaconst.SELECT_COMPLEMENT)),
            ("SelectByArtist", None, "By artist", None, "",
             lambda *x: BlaView.select(blaconst.SELECT_BY_ARTISTS)),
            ("SelectByAlbum", None, "By album", None, "",
             lambda *x: BlaView.select(blaconst.SELECT_BY_ALBUMS)),
            ("SelectByAlbumArtist", None, "By album artist", None, "",
             lambda *x: BlaView.select(blaconst.SELECT_BY_ALBUM_ARTISTS)),
            ("SelectByGenre", None, "By genre", None, "",
             lambda *x: BlaView.select(blaconst.SELECT_BY_GENRES)),
            ("Cut", None, "Cut", None, "", BlaView.cut),
            ("Copy", None, "Copy", None, "", BlaView.copy),
            ("Remove", None, "Remove", None, "", BlaView.remove),
            ("Paste", None, "Paste", None, "", BlaView.paste),
            ("PlaylistFromSelection", None, "Selection", None, "",
             lambda *x: BlaPlaylistManager.new_playlist(
             blaconst.PLAYLIST_FROM_SELECTION)),
            ("PlaylistFromArtists", None, "Selected artist(s)", None, "",
             lambda *x: BlaPlaylistManager.new_playlist(
             blaconst.PLAYLIST_FROM_ARTISTS)),
            ("PlaylistFromAlbums", None, "Selected album(s)", None, "",
             lambda *x: BlaPlaylistManager.new_playlist(
             blaconst.PLAYLIST_FROM_ALBUMS)),
            ("PlaylistFromAlbumArtists", None, "Selected album artist(s)",
             None, "", lambda *x: BlaPlaylistManager.new_playlist(
             blaconst.PLAYLIST_FROM_ALBUM_ARTISTS)),
            ("PlaylistFromGenre", None, "Selected genre(s)", None, "",
             lambda *x: BlaPlaylistManager.new_playlist(
             blaconst.PLAYLIST_FROM_GENRE)),
            ("RemoveDuplicates", None, "Remove _duplicates", None, "",
             BlaView.remove_duplicates),
            ("RemoveInvalidTracks", None, "Remove _invalid tracks", None, "",
             BlaView.remove_invalid_tracks),
            ("Search", None, "_Search...", "<Ctrl>F", "",
             lambda *x: BlaPlaylistManager.enable_search()),
            ("Preferences", None, "Pre_ferences...", None, "", BlaPreferences),
            ("JumpToPlayingTrack", None, "_Jump to playing track", "<Ctrl>J",
             "", lambda *x: BlaPlaylistManager.jump_to_playing_track()),
            ("About", None, "_About...", None, "", BlaAbout)
        ]
        toggle_actions = [
            ("Browsers", None, "_Browsers", None, "", self.__toggle_browsers,
             blacfg.getboolean("general", "browsers")),
            ("PlaylistTabs", None, "Playlist _tabs", None, "",
             self.__toggle_tabs, blacfg.getboolean("general",
                                                   "playlist.tabs")),
            ("SidePane", None, "_Side pane", None, "",
             self.__toggle_side_pane, blacfg.getboolean("general",
                                                        "side.pane")),
            ("Statusbar", None, "St_atusbar", None, "",
             self.__toggle_statusbar, blacfg.getboolean("general",
                                                        "statusbar")),
            ("Visualization", None, "Visualization", None, "",
             self.__toggle_visualization,
             blacfg.getboolean("general", "show.visualization"))
        ]
        radio_actions0 = [
            ("OrderNormal", None, "_Normal", None, "", blaconst.ORDER_NORMAL),
            ("OrderRepeat", None, "_Repeat", None, "", blaconst.ORDER_REPEAT),
            ("OrderShuffle", None, "_Shuffle", None, "",
             blaconst.ORDER_SHUFFLE)
        ]
        radio_actions1 = [
            ("Playlists", None, "_Playlists", None, "",
             blaconst.VIEW_PLAYLISTS),
            ("Queue", None, "_Queue", None, "", blaconst.VIEW_QUEUE),
            ("Radio", None, "R_adio", None, "", blaconst.VIEW_RADIO),
            ("RecommendedEvents", None, "_Recommended events", None, "",
             blaconst.VIEW_EVENTS),
            ("NewReleases", None, "_New releases", None, "",
             blaconst.VIEW_RELEASES),
        ]
        actiongroup.add_actions(actions)
        actiongroup.add_toggle_actions(toggle_actions)
        actiongroup.add_radio_actions(
            radio_actions0, value=blacfg.getint("general", "play.order"),
            on_change=BlaStatusbar.set_order)
        actiongroup.add_radio_actions(
            radio_actions1, value=blacfg.getint("general", "view"),
            on_change=lambda *x: BlaView.update_view(
            x[-1].get_current_value()))
        uimanager.insert_action_group(actiongroup, 0)
        uimanager.add_ui_from_string(blaconst.MENU)

        # This is the topmost box that holds all the other components.
        self.add(gtk.VBox())

        # Create instances of the main parts of the GUI.
        self.__toolbar = BlaToolbar()
        self.__browsers = BlaBrowsers()
        self.__view = BlaView()
        self.__statusbar = BlaStatusbar()

        player.connect("state_changed", self.update_title)

        # Pack the browser + view-widget into a gtk.HPane instance.
        hpane = gtk.HPaned()
        hpane.pack1(self.__browsers, resize=False, shrink=False)
        hpane.pack2(self.__view, resize=True, shrink=True)
        hpane.show()

        # Restore left pane handle position.
        try:
            hpane.set_position(blacfg.getint("general", "pane.pos.left"))
        except TypeError:
            pass
        hpane.connect(
            "notify",
            lambda pane, propspec: blacfg.set("general", "pane.pos.left",
                                              "%d" % pane.get_position()))

        # Restore right pane handle position.
        try:
            self.__view.set_position(
                blacfg.getint("general", "pane.pos.right"))
        except TypeError:
            pass
        self.__view.connect(
            "notify",
            lambda pane, propspec: blacfg.set("general", "pane.pos.right",
                                              "%d" % pane.get_position()))

        # Create a vbox for the toolbar, browser and playlist view. This allows
        # for setting a border around those items which excludes the menubar.
        vbox = gtk.VBox(spacing=2)
        vbox.set_border_width(2)
        vbox.pack_start(self.__toolbar, expand=False)
        vbox.pack_start(hpane)
        vbox.pack_start(self.__statusbar, expand=False)
        vbox.show()

        self.child.pack_start(uimanager.get_widget("/Menu"), expand=False)
        self.child.pack_start(vbox)
        blagui.update_colors()
        self.child.show()

        self.__keys = BlaKeys()

    def update_title(self, *args):
        track = player.get_track()
        state = player.get_state()

        if state == blaconst.STATE_STOPPED or not track:
            title = "%s %s" % (blaconst.APPNAME, blaconst.VERSION)
            tooltip = "Stopped"

        else:
            if player.radio:
                title = track[TITLE] or "%s - %s" % (
                    blaconst.APPNAME, track["organization"])
            else:
                artist = track[ARTIST]
                title = track[TITLE] or "?"
                if artist and title:
                    title = "%s - %s" % (artist, title)
                else:
                    title = track.basename

            tooltip = title

        self.set_title(title)
        blagui.tray.set_tooltip(tooltip)
        if not blacfg.getboolean("general", "tray.tooltip"):
            blagui.tray.set_has_tooltip(False)

    def raise_window(self):
        self.present()
        if not blacfg.getboolean("general", "always.show.tray"):
            blagui.tray.set_visible(False)
        BlaVisualization.flush_buffers()

    def toggle_hide(self, *args):
        visible = self.get_visible()
        blaguiutils.set_visible(not visible)
        if visible:
            self.hide()
            blagui.tray.set_visible(True)
        else:
            self.raise_window()

    def quit(self, *args):
        # Hide the main window, the tray icon, and every other tracked window.
        # Then destroy the main window which in turn initiates the actual
        # shutdown sequence.
        self.hide()
        blaguiutils.set_visible(False)
        blagui.tray.set_visible(False)
        self.destroy()
        return False

    def __delete_event(self, window, event):
        if blacfg.getboolean("general", "close.to.tray"):
            self.toggle_hide()
            return True
        return self.quit()

    def __toggle_browsers(self, event):
        state = event.get_active()
        self.__browsers.set_visibility(state)

    def __toggle_tabs(self, event):
        self.__view.views[blaconst.VIEW_PLAYLISTS].show_tabs(
            event.get_active())

    def __toggle_side_pane(self, event):
        self.__view.set_show_side_pane(event.get_active())

    def __toggle_statusbar(self, event):
        self.__statusbar.set_visibility(event.get_active())

    def __toggle_visualization(self, event):
        BlaVisualization.set_visibility(event.get_active())

    def __set_file_chooser_directory(self, diag):
        directory = blacfg.getstring("general", "filechooser.directory")
        if not directory or not os.path.isdir:
            directory = os.path.expanduser("~")
        diag.set_current_folder(directory)

    def __open_playlist(self, window):
        diag = gtk.FileChooserDialog(
            "Select playlist", buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                        gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        diag.set_local_only(True)
        self.__set_file_chooser_directory(diag)

        response = diag.run()
        path = diag.get_filename()
        diag.destroy()

        if response == gtk.RESPONSE_OK and path:
            path = path.strip()
            if BlaPlaylistManager.open_playlist(path):
                BlaView.update_view(blaconst.VIEW_PLAYLISTS)
                blacfg.set("general", "filechooser.directory",
                           os.path.dirname(path))

    def __add_tracks(self, files=True):
        if files:
            action = gtk.FILE_CHOOSER_ACTION_OPEN
        else:
            action = gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER
        diag = gtk.FileChooserDialog(
            "Select files", action=action,
            buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN,
                     gtk.RESPONSE_OK))
        diag.set_select_multiple(True)
        diag.set_local_only(True)
        self.__set_file_chooser_directory(diag)

        response = diag.run()
        filenames = diag.get_filenames()
        diag.destroy()

        if response == gtk.RESPONSE_OK and filenames:
            filenames = map(str.strip, filenames)
            BlaPlaylistManager.add_to_current_playlist(filenames, resolve=True)
            blacfg.set("general", "filechooser.directory",
                       os.path.dirname(filenames[0]))

    def __save_playlist(self, window):
        diag = gtk.FileChooserDialog(
            "Save playlist", action=gtk.FILE_CHOOSER_ACTION_SAVE,
            buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_SAVE,
                     gtk.RESPONSE_OK))
        diag.set_do_overwrite_confirmation(True)
        self.__set_file_chooser_directory(diag)

        items = [
            ("M3U", "audio/x-mpegurl", "m3u"),
            ("PlS", "audio/x-scpls", "pls", ),
            ("XSPF", "application/xspf+xml", "xspf"),
            ("Decide by extension", None, None)
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
        map(cb.append_text, ["Relative paths", "Absolute paths"])
        cb.set_active(0)

        def filter_changed(diag, filt):
            filt = diag.get_filter()
            if diag.list_filters().index(filt) == 2:
                sensitive = False
            else:
                sensitive = True
            cb.set_sensitive(sensitive)
        diag.connect("notify::filter", filter_changed)

        response = diag.run()
        path = diag.get_filename()

        if response == gtk.RESPONSE_OK and path:
            filt = diag.get_filter()
            type_ = items[diag.list_filters().index(filt)][-1]
            path = path.strip()
            if type_ is None:
                type_ = blautil.get_extension(path)
            BlaPlaylistManager.save(path, type_, cb.get_active() == 0)
            blacfg.set("general", "filechooser.directory",
                       os.path.dirname(path))

        diag.destroy()

