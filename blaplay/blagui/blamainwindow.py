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
from blawindows import BlaBaseWindow
from blatoolbar import BlaToolbar
from blabrowsers import BlaBrowsers
from blaplaylist import playlist_manager
from blavisualization import BlaVisualization
from blaview import BlaView
from blastatusbar import BlaStatusbar
from blapreferences import BlaPreferences
from blaabout import BlaAbout
from blatray import BlaTray
import blaguiutils


class BlaMainWindow(BlaBaseWindow):
    __is_fullscreen = False

    def __init__(self):
        super(BlaMainWindow, self).__init__(gtk.WINDOW_TOPLEVEL)
        self.set_resizable(True)
        self.connect("delete_event", self.__delete_event)
        self.enable_tracking(is_main_window=True)

        # Set up the fullscreen window.
        self.__fullscreen_window = gtk.Window()
        def map_(window):
            pass
        self.__fullscreen_window.connect("map", map_)
        self.__fullscreen_window.set_modal(True)
        self.__fullscreen_window.set_transient_for(self)
        self.__fullscreen_window.connect_object(
            "window_state_event", BlaMainWindow.__window_state_event, self)
        def key_press_event(window, event):
            if blagui.is_accel(event, "Escape"):
                window.child.emit("toggle_fullscreen")
            elif blagui.is_accel(event, "space"):
                player.play_pause()
            elif blagui.is_accel(event, "<Ctrl>Q"):
                blaplay.shutdown()
        self.__fullscreen_window.connect_object(
            "key_press_event", key_press_event, self.__fullscreen_window)
        # Realize the fullscreen window. If we don't do this here and reparent
        # the drawingarea to it later that in turn will get unrealized again,
        # causing bad X window errors.
        self.__fullscreen_window.realize()

        # Install a global mouse hook. If connected callbacks don't consume the
        # event by returning True this hook gets called for every widget in the
        # hierarchy that re-emits the event. We therefore cache the event's
        # timestamp to detect and ignore signal re-emissions.
        def button_press_hook(receiver, event):
            event_time = event.get_time()
            if event_time != self.__previous_event_time:
                self.__previous_event_time = event_time
                if event.button == 8:
                    player.previous()
                elif event.button == 9:
                    player.next()
            # This behaves like gobject.{timeout|idle}_add: if the callback
            # doesn't return True it's only called once. It does NOT prevent
            # signal callbacks from executing.
            return True
        self.__previous_event_time = -1
        gobject.add_emission_hook(self, "button_press_event",
                                  button_press_hook)

        # Main menu
        ui_manager = blaplay.bla.ui_manager
        self.add_accel_group(ui_manager.get_accel_group())

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
            ("Quit", gtk.STOCK_QUIT, "_Quit", "<Ctrl>Q", "",
             lambda *x: blaplay.shutdown()),
            ("Preferences", None, "Pre_ferences...", None, "", BlaPreferences),
            ("About", None, "_About...", None, "", BlaAbout)
        ]
        ui_manager.add_actions(actions)

        toggle_actions = [
            ("Browsers", None, "_Browsers", None, "", self.__toggle_browsers,
             blacfg.getboolean("general", "browsers")),
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
        ui_manager.add_toggle_actions(toggle_actions)

        radio_actions = [
            ("OrderNormal", None, "_Normal", None, "", blaconst.ORDER_NORMAL),
            ("OrderRepeat", None, "_Repeat", None, "", blaconst.ORDER_REPEAT),
            ("OrderShuffle", None, "_Shuffle", None, "",
             blaconst.ORDER_SHUFFLE)
        ]
        # TODO: Emit "order_changed" signal in the on_change handler instead
        #       and let interested widgets handle this instead.
        ui_manager.add_radio_actions(
            radio_actions, value=blacfg.getint("general", "play.order"),
            on_change=BlaStatusbar.set_order)

        # This is the topmost box that holds all the other components.
        self.add(gtk.VBox())

        # Create instances of the main parts of the GUI.
        self.__toolbar = BlaToolbar()
        self.__browsers = BlaBrowsers()
        self.__visualization = BlaVisualization()
        self.__view = BlaView()
        self.__statusbar = BlaStatusbar()

        # Group browsers and visualization widget.
        self.__vbox_left = gtk.VBox(spacing=blaconst.WIDGET_SPACING)
        self.__vbox_left.pack_start(self.__browsers, expand=True)
        self.__vbox_left.pack_start(self.__visualization, expand=False)
        self.__vbox_left.show()
        self.__vbox_left.set_visible(blacfg.getboolean("general", "browsers"))

        # Pack the browser + view-widget into a gtk.HPane instance.
        hpane = gtk.HPaned()
        hpane.pack1(self.__vbox_left, resize=False, shrink=False)
        hpane.pack2(self.__view, resize=True, shrink=True)
        hpane.show()

        # Restore pane positions.
        def notify(pane, propspec, key):
            blacfg.set("general", key, str(pane.get_position()))
        for pane, side in [(hpane, "left"), (self.__view, "right")]:
            key = "pane.pos.%s" % side
            try:
                pane.set_position(blacfg.getint("general", key))
            except TypeError:
                pass
            pane.connect("notify", notify, key)

        # Create a vbox hpane and the statusbar. This allows for setting a
        # border around those items which excludes the menubar and the toolbar.
        vbox = gtk.VBox(spacing=blaconst.BORDER_PADDING)
        vbox.set_border_width(blaconst.BORDER_PADDING)
        vbox.pack_start(hpane)
        vbox.pack_start(self.__statusbar, expand=False)
        vbox.show()

        self.child.pack_start(ui_manager.get_widget("/Menu"), expand=False)
        self.child.pack_start(self.__toolbar, expand=False)
        self.child.pack_start(vbox)
        self.child.show()

        self.__tray = BlaTray()

        def update_title(*args):
            self.__update_title()
        player.connect("state_changed", update_title)
        library.connect("library_updated", update_title)
        self.__update_title()

    def set_fullscreen(self, da, parent):
        # TODO: when minimizing to tray during fullscreen, reparent the da so
        #       that when we call raise_window() again we won't be in
        #       fullscreen anymore

        # When parent is None we want to go into fullscreen mode.
        go_to_fullscreen = parent is None
        if go_to_fullscreen:
            self.__fullscreen_window.fullscreen()
            da.reparent(self.__fullscreen_window)
            self.__fullscreen_window.show_all()
        else:
            self.__fullscreen_window.unfullscreen()
            da.reparent(parent)
            self.__fullscreen_window.hide()
        self.set_maximized(go_to_fullscreen)

    def raise_window(self):
        self.present()
        if not blacfg.getboolean("general", "always.show.tray"):
            self.__tray.set_visible(False)
        self.__visualization.flush_buffers()

    def toggle_hide(self):
        self.__hide_windows(self.get_visible())

    def destroy_(self, *args):
        self.__tray.set_visible(False)
        self.hide()
        self.__fullscreen_window.hide()

    def __update_title(self):
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
        self.__tray.set_tooltip(tooltip)
        if not blacfg.getboolean("general", "tray.show.tooltip"):
            self.__tray.set_has_tooltip(False)

    def __hide_windows(self, yes):
        blaguiutils.set_visible(not yes)
        if yes:
            self.hide()
            self.__tray.set_visible(True)
        else:
            self.raise_window()

    def __window_state_event(self, event):
        self.__is_fullscreen = bool(
            event.new_window_state & gtk.gdk.WINDOW_STATE_FULLSCREEN)

    @property
    def is_fullscreen(self):
        return self.__is_fullscreen

    def __delete_event(self, window, event):
        if blacfg.getboolean("general", "close.to.tray"):
            self.toggle_hide()
            return True
        blaplay.shutdown()
        return False

    def __toggle_browsers(self, event):
        state = event.get_active()
        self.__vbox_left.set_visible(state)
        blacfg.setboolean("general", "browsers", state)

    def __toggle_visualization(self, event):
        self.__visualization.set_visible(event.get_active())

    def __toggle_side_pane(self, event):
        self.__view.set_show_side_pane(event.get_active())

    def __toggle_statusbar(self, event):
        self.__statusbar.set_visible(event.get_active())

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
            if playlist_manager.open_playlist(path):
                self.__view.set_view(blaconst.VIEW_PLAYLISTS)
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
            playlist_manager.add_to_current_playlist(filenames, resolve=True)
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
            playlist_manager.save(path, type_, cb.get_active() == 0)
            blacfg.set("general", "filechooser.directory",
                       os.path.dirname(path))

        diag.destroy()

