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

import gobject
import gtk

from blaplay import blaconst, blacfg, blautils, blaplayer, bladb, blagui
player = blaplayer.player
library = bladb.library
from blaplay.formats._identifiers import *
from blaplay.blagui import blaguiutils, blapreferences
from blakeys import BlaKeys
from blatoolbar import BlaToolbar
from blabrowsers import BlaBrowsers
from blaplaylist import BlaPlaylist
from blavisualization import BlaVisualization
from blaview import BlaView
from blastatusbar import BlaStatusbar
from blapreferences import BlaPreferences
from blaabout import BlaAbout


class BlaWindow(gtk.Window):
    __hidden = False

    def __init__(self):
        super(BlaWindow, self).__init__(gtk.WINDOW_TOPLEVEL)
        gtk.window_set_default_icon_name(blaconst.APPNAME)

        self.set_resizable(True)
        self.set_title("%s %s" % (blaconst.APPNAME, blaconst.VERSION))
        self.set_size_request(*blaconst.MINSIZE)

        # connect window signals
        self.connect("delete_event", self.__delete_event)
        self.connect("window_state_event", self.__window_state_event)
        self.connect("configure_event", self.__save_geometry)

        # mainmenu
        blagui.uimanager = uimanager = gtk.UIManager()
        blagui.accelgroup = uimanager.get_accel_group()
        self.add_accel_group(blagui.accelgroup)
        actiongroup = gtk.ActionGroup("blagui-actions")

        actions = [
            # menus and submenus
            ("File", None, "_File"),
            ("Edit", None, "_Edit"),
            ("Select", None, "S_elect"),
            ("Selection", None, "Se_lection"),
            ("NewPlaylistFrom", None, "_New playlist from"),
            ("PlayOrder", None, "_Order"),
            ("View", None, "_View"),
            ("Visualization", None, "_Visualization"),
            ("Help", None, "_Help"),

            # menuitems
            ("OpenPlaylist", None, "Open playlist...", None, "",
                    self.__open_playlist),
            ("AddFiles", None, "Add _files...", None, "",
                    lambda *x: self.__add_tracks()),
            ("AddDirectories", None, "_Add directories...", None, "",
                    lambda *x: self.__add_tracks(files=False)),
            ("SavePlaylist", None, "_Save playlist...", None, "",
                    self.__save_playlist),
            ("Quit", gtk.STOCK_QUIT, "_Quit", "<Ctrl>Q", "", self.quit),
            ("Paste", None, "Paste", None, "", BlaView.paste),
            ("Clear", None, "_Clear", None, "", BlaView.clear),
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
            ("PlaylistFromSelection", None, "Selection", None, "",
                    lambda *x: BlaPlaylist.new_playlist(
                    blaconst.PLAYLIST_FROM_SELECTION)
            ),
            ("PlaylistFromArtists", None, "Selected artist(s)", None, "",
                    lambda *x: BlaPlaylist.new_playlist(
                    blaconst.PLAYLIST_FROM_ARTISTS)
            ),
            ("PlaylistFromAlbums", None, "Selected album(s)", None, "",
                    lambda *x: BlaPlaylist.new_playlist(
                    blaconst.PLAYLIST_FROM_ALBUMS)
            ),
            ("PlaylistFromAlbumArtists", None, "Selected album artist(s)",
                    None, "", lambda *x: BlaPlaylist.new_playlist(
                    blaconst.PLAYLIST_FROM_ALBUM_ARTISTS)
            ),
            ("PlaylistFromGenre", None, "Selected genre(s)", None, "",
                    lambda *x: BlaPlaylist.new_playlist(
                    blaconst.PLAYLIST_FROM_GENRE)
            ),
            ("RemoveDuplicates", None, "Remove _duplicates", None, "",
             lambda *x: BlaPlaylist.remove_duplicates()),
            ("RemoveInvalidTracks", None, "Remove _invalid tracks", None, "",
             lambda *x: BlaPlaylist.remove_invalid_tracks()),
            ("Search", None, "_Search...", "<Ctrl>F", "",
             lambda *x: BlaPlaylist.enable_search()),
            ("Preferences", None, "Pre_ferences...", None, "", BlaPreferences),
            ("JumpToPlayingTrack", None, "_Jump to playing track", "<Ctrl>J",
                    "", lambda *x: BlaPlaylist.jump_to_playing_track()),
            ("About", None, "_About...", None, "", BlaAbout)
        ]
        toggle_actions = [
            ("Browsers", None, "_Browsers", None, "", self.__toggle_browsers,
                    blacfg.getboolean("general", "browsers")),
            ("PlaylistTabs", None, "Playlist _tabs", None, "",
                    self.__toggle_tabs,
                    blacfg.getboolean("general", "playlist.tabs")
            ),
            ("SidePane", None, "_Side pane", None, "",
                    self.__toggle_side_pane, blacfg.getboolean(
                    "general", "side.pane")
            ),
            ("Statusbar", None, "St_atusbar", None, "",
                    self.__toggle_statusbar,
                    blacfg.getboolean("general", "statusbar")
            )
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
        radio_actions2 = [
            ("Off", None, "Off", None, "", blaconst.VISUALIZATION_OFF),
            ("Spectrum", None, "Spectrum", None, "",
             blaconst.VISUALIZATION_SPECTRUM)
        ]
        actiongroup.add_actions(actions)
        actiongroup.add_toggle_actions(toggle_actions)
        actiongroup.add_radio_actions(radio_actions0,
                value=blacfg.getint("general", "play.order"),
                on_change=BlaStatusbar.set_order
        )
        actiongroup.add_radio_actions(radio_actions1, value=blacfg.getint(
                "general", "view"), on_change=lambda *x: BlaView.update_view(
                x[-1].get_current_value())
        )
        actiongroup.add_radio_actions(radio_actions2,
                value=blacfg.getint("general", "visualization"),
                on_change=BlaVisualization.update_element
        )
        uimanager.insert_action_group(actiongroup, 0)
        uimanager.add_ui_from_string(blaconst.MENU)

        # this is the topmost box that holds all the other objects
        self.add(gtk.VBox())

        # create instances of the main parts of the gui
        self.__statusbar = BlaStatusbar()
        self.__toolbar = BlaToolbar()
        self.__browsers = BlaBrowsers()
        self.__view = BlaView()

        player.connect("state_changed", self.__update_title)

        # pack the browser + view-widget into a gtk.HPane instance
        hpane = gtk.HPaned()
        hpane.pack1(self.__browsers, resize=False, shrink=False)
        hpane.pack2(self.__view, resize=True, shrink=True)
        hpane.show()

        # restore left pane handle position
        pane_pos = blacfg.getint("general", "pane.pos.left")
        if pane_pos is not None: hpane.set_position(pane_pos)
        hpane.connect("notify", lambda pane, propspec:
                blacfg.set("general", "pane.pos.left",
                "%d" % pane.get_position())
        )

        # restore right pane handle position (of the view)
        pane_pos = blacfg.getint("general", "pane.pos.right")
        if pane_pos is not None: self.__view.set_position(pane_pos)
        self.__view.connect("notify", lambda pane, propspec:
                blacfg.set("general", "pane.pos.right",
                "%d" % pane.get_position())
        )

        # create a vbox for the toolbar, browser and playlist view. this allows
        # for setting a border around those items, excluding the menubar
        vbox = gtk.VBox(spacing=2)
        vbox.set_border_width(2)
        vbox.pack_start(self.__toolbar, expand=False)
        vbox.pack_start(hpane)
        vbox.pack_start(self.__statusbar, expand=False)
        vbox.show()

        # the topmost vbox wraps all other widgets
        self.child.pack_start(uimanager.get_widget("/Menu"), expand=False)
        self.child.pack_start(vbox)

        # position main window, set colors and show everything
        self.__set_geometry()
        blagui.update_colors()
        self.child.show()
        self.show()
        self.__keys = BlaKeys()

    def raise_window(self):
        self.show()
        self.deiconify()
        self.__hidden = False
        if not blacfg.getboolean("general", "always.show.tray"):
            blagui.tray.set_visible(False)
        BlaVisualization.flush_buffers()

    def toggle_hide(self, window, event=None):
        blaguiutils.set_visible(self.__hidden)
        if self.__hidden: self.raise_window()
        else:
            self.hide()
            self.__hidden = True
            blagui.tray.set_visible(True)
        return True

    def quit(self, *args):
        # hide all windows for the illusion of a faster shutdown. once the main
        # loop quits the signal handlers to save the state to disk are run
        self.hide()
        blaguiutils.set_visible(False)
        blagui.tray.set_visible(False)
        gtk.main_quit()
        return False

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

    def __delete_event(self, window, event):
        if blacfg.getboolean("general", "close.to.tray"):
            return self.toggle_hide(window, event)
        return self.quit()

    def __window_state_event(self, window, event):
        if (event.changed_mask & gtk.gdk.WINDOW_STATE_ICONIFIED and
                event.new_window_state & gtk.gdk.WINDOW_STATE_ICONIFIED and
                blacfg.getboolean("general", "minimize.to.tray")):
            self.toggle_hide(window, event)
        if event.new_window_state == gtk.gdk.WINDOW_STATE_MAXIMIZED:
            blacfg.setboolean("general", "maximized", True)
        elif not (event.new_window_state & gtk.gdk.WINDOW_STATE_MAXIMIZED):
            blacfg.setboolean("general", "maximized", False)
            self.__set_geometry()
        return True

    def __set_geometry(self, *args):
        size = blacfg.getlistint("general", "size")
        position = blacfg.getlistint("general", "position")

        if size is None:
            screen = self.get_screen()
            x, y, w, h = screen.get_monitor_geometry(0)
            size = map(int, [w / 2.0, h / 2.0])
            self.resize(*size)
            self.set_position(gtk.WIN_POS_CENTER)
        else:
            self.resize(*size)
            self.move(*position)

        if blacfg.getboolean("general", "maximized"): self.maximize()

    def __save_geometry(self, window, event):
        size = self.get_size()
        position = self.get_position()

        if not blacfg.getboolean("general", "maximized"):
            blacfg.set("general", "size", "%d, %d" % size)
            blacfg.set("general", "position", "%d, %d" % position)

    def __update_title(self, *args):
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
                if artist and title: title = "%s - %s" % (artist, title)
                else: title = track.basename

            tooltip = title

        self.set_title(title)
        blagui.tray.set_tooltip(tooltip)
        if not blacfg.getboolean("general", "tray.tooltip"):
            blagui.tray.set_has_tooltip(False)

    def __open_playlist(self, window):
        diag = gtk.FileChooserDialog("Select playlist",
                buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                gtk.STOCK_OPEN, gtk.RESPONSE_OK)
        )
        diag.set_local_only(True)
        response = diag.run()
        path = diag.get_filename()
        diag.destroy()

        if response == gtk.RESPONSE_OK and path:
            if BlaPlaylist.open_playlist(path.strip()):
                BlaView.update_view(blaconst.VIEW_PLAYLISTS)

    def __add_tracks(self, files=True):
        if files: action = gtk.FILE_CHOOSER_ACTION_OPEN
        else: action = gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER
        diag = gtk.FileChooserDialog("Select files", action=action,
                buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                gtk.STOCK_OPEN, gtk.RESPONSE_OK)
        )
        diag.set_select_multiple(True)
        diag.set_local_only(True)
        response = diag.run()
        filenames = diag.get_filenames()
        diag.destroy()

        if response == gtk.RESPONSE_OK and filenames:
             filenames = map(str.strip, filenames)
             BlaPlaylist.add_to_current_playlist("", filenames, resolve=True)

    def __save_playlist(self, window):
        def filter_func(filter_info, extension):
            if extension is None: return True
            path, uri, filename, mimetype = filter_info
            if blautils.get_extension(filename).strip().lower() == extension:
                return True
            return False

        diag = gtk.FileChooserDialog("Save playlist",
                action=gtk.FILE_CHOOSER_ACTION_SAVE, buttons=(gtk.STOCK_CANCEL,
                gtk.RESPONSE_CANCEL, gtk.STOCK_SAVE, gtk.RESPONSE_OK)
        )
        diag.set_do_overwrite_confirmation(True)

        items = [
            ("M3U", "m3u"), ("PlS", "pls"), ("XSPF", "xspf"),
            ("By extension", None)
        ]
        for label, extension in items:
            filt = gtk.FileFilter()
            filt.set_name(label)
            filt.add_custom(
                    gtk.FILE_FILTER_DISPLAY_NAME, filter_func, extension)
            diag.add_filter(filt)

        response = diag.run()
        path = diag.get_filename()

        if response == gtk.RESPONSE_OK and path:
            filt = diag.get_filter()
            type_ = items[diag.list_filters().index(filt)][-1]
            path = path.strip()
            if type_ is None: type_ = blautils.get_extension(path)
            BlaPlaylist.save(path, type_)

        diag.destroy()

