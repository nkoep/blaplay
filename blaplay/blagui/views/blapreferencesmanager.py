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

import gtk

from blaplay.blacore import blaconst
from .blaviewmanager import BlaViewManager
from .blapreferences import BlaPreferences


class BlaPreferencesManager(BlaViewManager):
    ID = blaconst.VIEW_PREFERENCES

    def show_preferences(self):
        if not self.views:
            preferences = BlaPreferences(
                self._config, self._library, self._player, self)
            self.views.append(preferences)
        preferences = self.views[0]
        self._notify_add(preferences)
        self._notify_focus(preferences)

    def create_view(self):
        self.show_preferences()

