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

from blaplay.blacore import blaconst
from blaplay import blautil


class BlaUIManager(gtk.UIManager):
    __metaclass__ = blautil.BlaSingletonMeta

    def __init__(self):
        super(BlaUIManager, self).__init__()
        self.__actiongroup = gtk.ActionGroup("blaplay-actions")
        self.insert_action_group(self.__actiongroup)
        self.add_ui_from_string(blaconst.MENU)

    def add_actions(self, actions):
        self.__actiongroup.add_actions(actions)

    def add_toggle_actions(self, toggle_actions):
        self.__actiongroup.add_toggle_actions(toggle_actions)

    def add_radio_actions(self, radio_actions, value, on_change):
        self.__actiongroup.add_radio_actions(
            radio_actions, value=value, on_change=on_change)

    def update_menu(self, view):
        from blaplaylist import BlaPlaylistManager
        from blaqueue import BlaQueue

        state = False
        if view == blaconst.VIEW_PLAYLISTS:
            state = True

        # TODO: Update the "Clear" label for the playlist or queue.
        for entry in blaconst.MENU_PLAYLISTS:
            self.get_widget(entry).set_visible(state)

        if view in [blaconst.VIEW_PLAYLISTS, blaconst.VIEW_QUEUE]:
            clipboard = (BlaPlaylistManager.clipboard
                         if view == blaconst.VIEW_PLAYLISTS
                         else BlaQueue.clipboard)
            self.get_widget("/Menu/Edit/Paste").set_sensitive(bool(clipboard))
            state = True
        else:
            state = False

        for entry in blaconst.MENU_EDIT:
            self.get_widget(entry).set_visible(state)

