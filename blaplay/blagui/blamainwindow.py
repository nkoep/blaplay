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

import gobject
import gtk

from blaplay.blacore import blaconst
from blaplay import blautil
from blawindows import BlaBaseWindow
from blatoolbar import BlaToolbar
from . import browsers, blastatusbar
from .blaguiutil import BlaViewport
from .views.blatabview import BlaTabView


def create_window(config, library, player):
    # Create the tab view.
    tab_view = BlaTabView()

    # Create the view managers.
    from . import views
    view_managers = views.create_managers(config, library, player)

    # Create the view delegate that abstracts interactions with the various
    # view managers.
    from .views.blaviewdelegate import BlaViewDelegate
    view_delegate = BlaViewDelegate(tab_view, view_managers)

    # Create the UI manager and register global accelerator actions.
    from .blauimanager import BlaUIManager
    ui_manager = BlaUIManager(view_delegate)

    # Create the tab controller. Note that the controller is kept alive as a
    # result of connecting some of its methods as callback functions. We don't
    # need an explicit reference to it anywhere else.
    from .views.blatabcontroller import BlaTabController
    BlaTabController(tab_view, view_managers)

    # Create the browser view.
    browser_view = browsers.create_view(config, library, view_delegate)

    # Create the statusbar.
    statusbar = blastatusbar.create_statusbar(library, player, view_managers)

    def on_view_changed(tab_view, view):
        statusbar.set_status_message(view.get_status_message())
    tab_view.connect("view-changed", on_view_changed)

    # Create the main window and inject the missing components.
    window = _BlaMainWindow(config, player)
    window.add_accel_group(ui_manager.get_accel_group())
    window.add_menubar(ui_manager.get_menubar())
    window.add_browser_view(browser_view)
    window.add_tab_view(tab_view)
    window.add_statusbar(statusbar)

    return window


class _BlaMainWindow(BlaBaseWindow):
    class StateManager(BlaBaseWindow.StateManager):
        def __init__(self, config):
            self._config = config

        def size(self, *args):
            if args:
                (size,) = args
                self._config.set_("general", "size", "%d, %d" % size)
            else:
                return self._config.getlistint("general", "size")

        def position(self, *args):
            if args:
                (position,) = args
                self._config.set_("general", "position", "%d, %d" % position)
            else:
                return self._config.getlistint("general", "position")

        def maximized(self, *args):
            if args:
                (state,) = args
                self._config.setboolean("general", "maximized", state)
            else:
                return self._config.getboolean("general", "maximized")

    def _create_lyrics_container(self, player):
        # TODO: Rename BlaFetcher to BlaMetadataFetcher.
        from blaplay.blautil.blametadata import BlaFetcher as BlaMetadataFetcher
        from blalyricsviewer import BlaLyricsViewer
        from blatrackinfo import BlaTrackInfo

        vbox = gtk.VBox(spacing=blaconst.WIDGET_SPACING)
        metadata_fetcher = BlaMetadataFetcher()
        vbox.pack_start(BlaLyricsViewer(player, metadata_fetcher))
        vbox.pack_start(BlaTrackInfo(player, metadata_fetcher), expand=False)
        return vbox

    def _create_pane(self, widget1, widget2, key):
        key = "pane.pos.%s" % key
        pane = gtk.HPaned()
        pane.pack1(widget1, shrink=False)
        pane.pack2(widget2, resize=False, shrink=False)
        try:
            pane.set_position(self._config.getint("general", key))
        except TypeError:
            pass
        def on_notify_position(pane, propspec):
            position = pane.get_property(propspec.name)
            self._config.set_("general", key, str(position))
        pane.connect("notify::position", on_notify_position)
        return pane

    def _install_global_mouse_hook(self, player):
        # If connected callbacks don't consume the event by returning True,
        # this hook gets called for every connected handler. We therefore cache
        # the event's timestamp to detect and ignore successive invocations.
        def on_button_press_event_hook(receiver, event):
            event_time = event.get_time()
            if event_time != self._last_event_time:
                self._last_event_time = event_time
                if event.button == 8:
                    player.previous()
                elif event.button == 9:
                    player.next()
            # This behaves like gobject.{timeout,idle}_add, i.e., if the
            # callback returns True the hook will be invoked every time a new
            # event arrives.
            return True
        self._last_event_time = -1
        gobject.add_emission_hook(
            self, "button-press-event", on_button_press_event_hook)

    def __init__(self, config, player):
        super(_BlaMainWindow, self).__init__(
            _BlaMainWindow.StateManager(config), gtk.WINDOW_TOPLEVEL)

        self._config = config

        self.add(gtk.VBox())

        # Create placeholders for widgets we want to inject later.
        self._tab_view_slot = BlaViewport()
        self._browser_view_slot = BlaViewport()
        self._menubar_slot = BlaViewport()
        self._statusbar_slot = BlaViewport()

        # Create the main view outlet and place it in a pane with the lyrics
        # and track info side pane.
        lyrics_container = self._create_lyrics_container(player)
        pane_right = self._create_pane(
            self._tab_view_slot, lyrics_container, "right")

        # FIXME: The pane settings aren't ideal, i.e., the pane position won't
        #        shrink by window resizing after having grown due to a resize.
        # Pack the browser + view-widget into a paned widget.
        pane_left = self._create_pane(self._browser_view_slot, pane_right,
                                      "left")

        # Create a vbox for the middle pane and the statusbar. This allows for
        # using a border around those items which excludes the menubar and the
        # toolbar.
        vbox = gtk.VBox(spacing=blaconst.BORDER_PADDING)
        vbox.set_border_width(blaconst.BORDER_PADDING)
        vbox.pack_start(pane_left)
        vbox.pack_start(self._statusbar_slot, expand=False)

        # Pack everything up together in the main window's vbox.
        self.child.pack_start(self._menubar_slot, expand=False)
        self._toolbar = BlaToolbar(config, player)
        self.child.pack_start(self._toolbar, expand=False)
        self.child.pack_start(vbox)

        self.connect_object(
            "delete-event", _BlaMainWindow._on_delete_event, self)

        self._install_global_mouse_hook(player)

        self.show_all()

    def _hide_windows(self, yes):
        if yes:
            self.hide()
        else:
            self.raise_window()

    def _on_delete_event(self, event):
        if self._config.getboolean("general", "close.to.tray"):
            self.toggle_hide()
            return True
        blaplay.shutdown()
        return False

    def raise_window(self):
        self.present()

    def toggle_hide(self):
        self._hide_windows(self.get_visible())

    def add_menubar(self, menubar):
        assert self._menubar_slot.child is None
        self._menubar_slot.add(menubar)

    def add_browser_view(self, browser_view):
        assert self._browser_view_slot.child is None
        self._browser_view_slot.add(browser_view)

    def add_tab_view(self, tab_view):
        assert self._tab_view_slot.child is None
        self._tab_view_slot.add(tab_view)

    def add_statusbar(self, statusbar):
        assert self._statusbar_slot.child is None
        self._statusbar_slot.add(statusbar)
        self._toolbar.link_statusbar(statusbar)
