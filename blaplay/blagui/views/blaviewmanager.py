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

from blaplay import blautil
from .. import blaguiutil


class BlaViewManager(gobject.GObject):
    __gsignals__ = {
        "view-added": blautil.signal(1),
        "view-focused": blautil.signal(1),
        "view-updated": blautil.signal(1),
        "view-removed": blautil.signal(1)
    }

    def __init__(self, config, library, player):
        self._config = config
        self._library = library
        self._player = player
        self._observers = []
        self.views = []

    def _notify_observers(self, action, view):
        # Notify observers about changes to a view. Observers shouldn't have to
        # implement all supported methods though so we're fine with
        # AttributeError exceptions here.
        for observer in self._observers:
            # TODO: Rename methods to "on_notify_*" to make the semantics
            #       clearer. Methods on the observer will be called by the
            #       observee.
            method = "notify_" + action
            if hasattr(observer, method):
                getattr(observer, method)(view)

    def _notify_add(self, view):
        self._notify_observers("add", view)

    def _notify_focus(self, view):
        self._notify_observers("focus", view)

    def _notify_status(self, view):
        self._notify_observers("status", view)

    def _notify_remove(self, view):
        self._notify_observers("remove", view)

    def register_observer(self, observer):
        self._observers.append(observer)

    def create_view(self):
        raise NotImplementedError

    def request_focus_for_view(self, view):
        assert view in self.views, "invalid view for manager"
        self._notify_focus(view)

    def remove_view(self, view):
        """
        Remove a view from the view manager. Subclasses should always call this
        method to remove a view to guarantee that the lock state is checked
        first.
        """
        assert view in self.views, "invalid view for manager"

        if view.locked():
            blaguiutil.error_dialog(
                "This tab is locked", "Unlock it first to remove it.")
        else:
            self.views.remove(view)
            self._notify_remove(view)

    def populate_context_menu(self, menu, view):
        if view is not None:
            if menu.get_children():
                menu.append_separator()
            menu.append_item("Unlock tab" if view.locked() else "Lock tab",
                             on_activate_callback=view.toggle_lock)
            menu.append_item("Close tab", self.remove_view, view)
