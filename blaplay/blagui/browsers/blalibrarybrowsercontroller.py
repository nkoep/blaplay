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

import gobject
import gtk

from blaplay.blacore import blaconst
from .blalibrarymodel import BlaLibraryModel


class BlaLibraryBrowserController(object):
    """
    This class serves as delegator between the library browser and the
    underlying model. It also proxies requests to send tracks to playlists,
    queue, or edit tracks by observing the library browser for the
    corresponding events, and forwarding them to the appropriate view manager
    through the view delegate.
    """

    def __init__(self, config, library, browser, view_delegate):
        self._config = config
        self._library = library
        self._browser = browser
        self._view_delegate = view_delegate
        self._callback_id = -1

        self._config.connect_object(
            "changed", BlaLibraryBrowserController._on_config_changed, self)

        library.connect_object(
            "library-updated", type(browser).request_model, browser)

        browser.connect("model-requested", self._on_model_requested)
        browser.connect_object(
            "add-to-current-playlist",
            BlaLibraryBrowserController._add_uris_to_current_playlist, self)
        browser.connect_object(
            "button-action-double-click",
            BlaLibraryBrowserController._on_button_action_double_click, self)
        browser.connect_object(
            "button-action-middle-click",
            BlaLibraryBrowserController._on_button_action_middle_click, self)
        browser.connect_object(
            "key-action", BlaLibraryBrowserController._on_key_action, self)
        browser.connect_object(
            "send-to-current-playlist",
            BlaLibraryBrowserController._send_uris_to_current_playlist, self)
        browser.connect_object(
            "send-to-new-playlist",
            BlaLibraryBrowserController._send_uris_to_new_playlist, self)

        self._update_browser_style()
        browser.set_organize_by(config.getint("library", "organize.by"))

    def _update_browser_style(self):
            self._browser.set_treeview_style(
                self._config.getboolean("library", "custom.browser"))

    def _on_config_changed(self, section, key):
        if section == "library" and key == "custom.browser":
            self._update_browser_style()

    def _on_model_requested(self, browser, filter_string):
        print_d("Updating library browser...")
        gobject.source_remove(self._callback_id)
        self._config.set_("library", "organize.by", browser.get_organize_by())

        model = BlaLibraryModel(self._config.getint("library", "organize.by"))
        def on_populated(model):
            browser.set_model(model)
            self._set_cursor(browser, None)
        model.connect("populated", on_populated)
        generator = model.populate(
            self._config, self._library, filter_string).next
        self._callback_id = gobject.idle_add(generator)
        self._set_cursor(browser, gtk.gdk.WATCH)

    def _send_uris_to_current_playlist(self, name, uris):
        self._view_delegate.send_uris_to_current_playlist(uris)

    def _add_uris_to_current_playlist(self, name, uris):
        self._view_delegate.add_uris_to_current_playlist(uris)

    def _send_uris_to_new_playlist(self, name, uris):
        self._view_delegate.send_uris_to_new_playlist(name, uris)

    def _forward_playlist_action(self, action, name, uris):
        if action == blaconst.ACTION_SEND_TO_CURRENT:
            self._send_uris_to_current_playlist(name, uris)
        elif action == blaconst.ACTION_ADD_TO_CURRENT:
            self._add_uris_to_current_playlist(name, uris)
        elif action == blaconst.ACTION_SEND_TO_NEW:
            self._send_uris_to_new_playlist(name, uris)

    def _on_key_action(self, name, uris):
        action = self._config.getint("library", "return.action")
        self._forward_playlist_action(action, name, uris)

    def _on_button_action_double_click(self, name, uris):
        action = self._config.getint("library", "doubleclick.action")
        self._forward_playlist_action(action, name, uris)

    def _on_button_action_middle_click(self, name, uris):
        action = self._config.getint("library", "middleclick.action")
        self._forward_playlist_action(action, name, uris)

    # TODO: Move this to blaguiutils.
    @staticmethod
    def _set_cursor(browser, cursor):
        if cursor is not None:
            cursor = gtk.gdk.Cursor(cursor)
        try:
            browser.window.set_cursor(cursor)
        except AttributeError:
            pass

