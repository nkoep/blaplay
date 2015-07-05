# blaplay, Copyright (C) 2014  Niklas Koep

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

import gtk

import blaplay
from blaplay.blacore import blaconst


class BlaUIManager(gtk.UIManager):
    _MENU = """
    <ui>
      <menubar name="Menu">
        <menu action="%s">
          <menuitem action="AddNewPlaylist"/>
          <menuitem action="OpenPlaylist"/>
          <menuitem action="SavePlaylist"/>
          <menuitem action="AddFiles"/>
          <menuitem action="AddDirectories"/>
          <separator/>
          <menuitem action="JumpToPlayingTrack"/>
          <menuitem action="Search"/>
          <menuitem action="LockUnlockView"/>
          <menuitem action="CloseView"/>
          <separator/>
          <menuitem action="Preferences"/>
          <menuitem action="About"/>
          <separator/>
          <menuitem action="Quit"/>
        </menu>
      </menubar>
    </ui>
    """ % blaconst.APPNAME

    def __init__(self, view_delegate):
        super(BlaUIManager, self).__init__()

        self._view_delegate = view_delegate

        self.add_ui_from_string(self._MENU)
        action_group = gtk.ActionGroup("blaplay-actions")
        self.insert_action_group(action_group)

        actions = [
            # Menu root
            (blaconst.APPNAME, None, "_%s" % blaconst.APPNAME),

            # Playlist actions
            ("AddNewPlaylist", gtk.STOCK_NEW, "New playlist", "<Ctrl>T",
             None, self._add_new_playlist),
            ("OpenPlaylist", gtk.STOCK_OPEN, "Open playlist...", "<Ctrl>O",
             None, self._open_playlist),

            # Conditional playlist actions depending on whether the current
            # view is a playlist view or not.
            ("SavePlaylist", gtk.STOCK_SAVE, "_Save playlist...", "<Ctrl>S",
             None, self._save_playlist),
            ("AddFiles", gtk.STOCK_ADD, "_Add files...", None, None,
             self._add_files),
            ("AddDirectories", None, "Add _directories...", None, None,
             self._add_directories),

            # Generic tracklist actions (only useful for playlists and the
            # queue)
            ("Search", gtk.STOCK_FIND, "Search track list...", "<Ctrl>F", None,
             self._search),

            # View-agnostic actions
            ("JumpToPlayingTrack", gtk.STOCK_JUMP_TO, "Jump to playing track",
             "<Ctrl>J", None, self._jump_to_playing_track),
            ("LockUnlockView", None, "Lock/Unlock tab", "<Ctrl>L", None,
             self._lock_unlock_current_tab),
            ("CloseView", gtk.STOCK_CLOSE, "Close tab", "<Ctrl>W", None,
             self._close_current_tab),

            # Views
            ("Preferences", gtk.STOCK_PREFERENCES, "_Preferences...", None,
             None, self._preferences),
            ("About", gtk.STOCK_ABOUT, "_About...", None, None, self._about),

            # Quit
            ("Quit", gtk.STOCK_QUIT, "_Quit", "<Ctrl>Q", "", self._quit)
        ]
        action_group.add_actions(actions)

        # Register a handler to be called before the menu is shown so we can
        # update the sensitivity of certain options.
        menu_items = self.get_menubar().get_children()
        assert len(menu_items) == 1
        menu_items[0].connect_object(
            "activate", BlaUIManager._update_menu, self)

    def _get_item(self, item):
        return self.get_widget("/Menu/%s/%s" % (blaconst.APPNAME, item))

    def _update_menu(self):
        # Update playlist actions.
        items = [self._get_item(item) for item in ("SavePlaylist", "AddFiles",
                                                   "AddDirectories")]
        tab_is_playlist = self._view_delegate.current_tab_is_playlist()
        for item in items:
            item.set_sensitive(tab_is_playlist)

        # Update the "Search" option sensitivity.
        self._get_item("Search").set_sensitive(
            self._view_delegate.current_tab_is_tracklist())

        # Update the lock/unlock label.
        lock_item = self._get_item("LockUnlockView")
        tab_locked = self._view_delegate.current_tab_is_locked()
        if tab_locked:
            text = "Unlock"
        else:
            text = "Lock"
        lock_item.set_label("%s tab" % text)
        self._get_item("CloseView").set_sensitive(not tab_locked)

        self.ensure_update()

    def get_menubar(self):
        return self.get_widget("/Menu")

    def _add_new_playlist(self, *args):
        self._view_delegate.add_new_playlist()

    def _open_playlist(self, *args):
        self._view_delegate.open_playlist()

    def _save_playlist(self, *args):
        self._view_delegate.save_current_playlist()

    def _add_files(self, *args):
        self._view_delegate.add_files_to_current_playlist()

    def _add_directories(self, *args):
        self._view_delegate.add_directories_to_current_playlist()

    def _jump_to_playing_track(self, *args):
        self._view_delegate.jump_to_playing_track()

    def _search(self, *args):
        self._view_delegate.enter_search_mode()

    def _lock_unlock_current_tab(self, *args):
        self._view_delegate.current_tab_toggle_lock()

    def _close_current_tab(self, *args):
        self._view_delegate.close_current_tab()

    def _preferences(self, *args):
        self._view_delegate.show_preferences()

    def _about(self, *args):
        # XXX: Use a view manager for this.
        from blaabout import BlaAbout
        BlaAbout()

    def _quit(self, *args):
        blaplay.shutdown()

