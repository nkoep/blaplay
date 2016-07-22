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

from blaplay import blautil
from blaplay.blacore import blaconst


class BlaTabController(object):
    def __init__(self, tab_view, view_managers):
        assert len(view_managers) > 0, "no view managers registered"

        self._tab_view = tab_view
        self._view_managers = view_managers

        for manager in view_managers.values():
            manager.register_observer(self)

        tab_view.connect_object(
            "remove-view-request",
            BlaTabController._on_remove_view_request, self)
        tab_view.connect_object(
            "view-requested", BlaTabController._create_default_view, self)

        self._load_views()

    def _on_remove_view_request(self, view):
        view.remove()

    def _create_default_view(self):
        self._view_managers[blaconst.VIEW_PLAYLIST].create_view()

    def _dump_views(self):
        pass

    def _load_views(self):
        if self._tab_view.get_num_views() == 0:
            self._create_default_view()

    def notify_add(self, view):
        if view not in self._tab_view:
            self._tab_view.append_view(view)

    def notify_remove(self, view):
        self._tab_view.remove_view(view)
        if self._tab_view.get_num_views() == 0:
            self._create_default_view()

    # XXX: The semantics of this method are inconsistent compared to the other
    #      notify_* methods. The other ones are called to notify observers that
    #      something already changed whereas `notify_focus' is called when a
    #      view wants to receive focus, relying on the controller to
    #      communicate the request to the tab view.
    def notify_focus(self, view):
        self._tab_view.focus_view(view)
