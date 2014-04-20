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

import abc

from .. import blaguiutil


class BlaViewManager(object):
    __metaclass__ = abc.ABCMeta

    def __init__(self, config, library, player):
        self._config = config
        self._library = library
        self._player = player
        self._observers = []
        self.views = []

    def _notify_observers(self, method, view):
        # Notify observers about changes to a view. Observers shouldn't have to
        # implement all supported methods though so we're fine with
        # AttributeError exceptions here.
        for observer in self._observers:
            try:
                callback = getattr(observer, method)
            except AttributeError:
                pass
            else:
                callback(view)

    def _notify_add(self, view):
        self._notify_observers("notify_add", view)

    def _notify_focus(self, view):
        self._notify_observers("notify_focus", view)

    def _notify_status(self, view):
        self._notify_observers("notify_status", view)

    def _notify_remove(self, view):
        self._notify_observers("notify_remove", view)

    def register_observer(self, observer):
        self._observers.append(observer)

    @abc.abstractmethod
    def create_view(self):
        pass

    def remove_view(self, view):
        """
        Remove a view from the view manager. Subclasses should always call this
        method to remove a view to guarantee that the lock state is checked
        first.
        """

        if view.locked():
            blaguiutil.error_dialog(
                "This tab is locked", "Unlock it first to remove it.")
            return False
        try:
            self.views.remove(view)
        except ValueError:
            return False
        else:
            self._notify_remove(view)
        return True

    def populate_context_menu(self, menu, view):
        if view is not None:
            if menu.get_children():
                menu.append_separator()
            menu.append_item("Unlock tab" if view.locked() else "Lock tab",
                             on_activate_callback=view.toggle_lock)
            menu.append_item("Close tab", self.remove_view, view)

