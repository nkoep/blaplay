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
# from .blafilesystemmodel import BlaFilesystemModel


class BlaFilesystemBrowserController(object):
    """
    This class proxies requests to send filesystem entries to playlists
    by forwarding them to the appropriate view manager through the view
    delegate.
    """

    def __init__(self, config, browser, view_delegate):
        self._config = config
        self._browser = browser
        self._view_delegate = view_delegate
        self._timeout_id = 0

        # browser.connect("model-requested", self._on_model_requested)
        browser.connect_object(
            "add-to-current-playlist",
            BlaFilesystemBrowserController._add_uris_to_current_playlist, self)
        browser.connect_object(
            "button-action-double-click",
            BlaFilesystemBrowserController._on_button_action_double_click, self)
        browser.connect_object(
            "button-action-middle-click",
            BlaFilesystemBrowserController._on_button_action_middle_click, self)
        browser.connect_object(
            "send-to-current-playlist",
            BlaFilesystemBrowserController._send_uris_to_current_playlist, self)
        browser.connect_object(
            "send-to-new-playlist",
            BlaFilesystemBrowserController._send_uris_to_new_playlist, self)

    # XXX: We should be able to pull this out into the browsercontroller base
    #      class.
    def _on_model_requested(self, browser, filter_string):
        def source_remove():
            if self._timeout_id:
                gobject.source_remove(self._timeout_id)
                self._timeout_id = 0

        print_d("Updating filesystem browser...")
        self._config.set_("general", "filesystem.directory",
                          browser.get_directory())

        model = BlaFilesystemModel(
            self._config.getstring("general", "filesystem.directory"))
        def on_populated(model):
            browser.set_model(model)
            source_remove()
            self._set_cursor(browser, None)
        model.connect("populated", on_populated)
        generator = model.populate(
            self._config, self._library, filter_string).next
        source_remove()
        self._callback_id = gobject.idle_add(generator)
        self._set_cursor(browser, gtk.gdk.WATCH)

    def _send_uris_to_current_playlist(self, name, uris):
        self._view_delegate.send_uris_to_current_playlist(uris)

    def _add_uris_to_current_playlist(self, name, uris):
        self._view_delegate.add_uris_to_current_playlist(uris)

    def _send_uris_to_new_playlist(self, name, uris):
        self._view_delegate.send_uris_to_new_playlist(name, uris)

    def _forward_playlist_action(self, action, name, uris):
        # TODO: URIs from the filesystem browser have to be handed to the
        #       library first so it can analyze new files' metadata.
        if action == blaconst.ACTION_SEND_TO_CURRENT:
            self._send_uris_to_current_playlist(name, uris)
        elif action == blaconst.ACTION_ADD_TO_CURRENT:
            self._add_uris_to_current_playlist(name, uris)
        elif action == blaconst.ACTION_SEND_TO_NEW:
            self._send_uris_to_new_playlist(name, uris)

    def _on_button_action_double_click(self, name, uris):
        action = self._config.getint("library", "doubleclick.action")
        self._forward_playlist_action(action, name, uris)

    def _on_button_action_middle_click(self, name, uris):
        action = self._config.getint("library", "middleclick.action")
        self._forward_playlist_action(action, name, uris)

    # TODO: Move this to blaguiutil and accept a different argument than
    #       cursor. We only need two types of cursors anyway -- gtk.gdk.WATCH
    #       and None so we can simply use a flag instead.
    @staticmethod
    def _set_cursor(widget, cursor):
        if cursor is not None:
            cursor = gtk.gdk.Cursor(cursor)
        try:
            widget.window.set_cursor(cursor)
        except AttributeError:
            pass

