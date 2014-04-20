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

from blaplay import blagui, blautil
from .. import blaguiutils


class BlaTabView(gtk.Notebook):
    __gsignals__ = {
        "remove-view-request": blautil.signal(1),
        "view-changed": blautil.signal(1),
        "view-requested": blautil.signal(0)
    }

    def __init__(self):
        super(BlaTabView, self).__init__()

        # Set up DND support for the tab strip.
        self.drag_dest_set(gtk.DEST_DEFAULT_MOTION | gtk.DEST_DEFAULT_DROP,
                           blagui.DND_TARGETS.values(),
                           gtk.gdk.ACTION_COPY)

        self.connect_object(
            "button-press-event", BlaTabView._on_button_press_event, self)
        self.connect_object("drag-data-received",
                            BlaTabView._on_drag_data_received, self)
        self.connect_object(
            "switch-page", BlaTabView._on_switch_page, self)

        self.show_all()

    def _find_view_at(self, x_root, y_root):
        for view in self:
            label = self.get_tab_label(view)
            x0, y0 = self.window.get_origin()
            x, y, w, h = label.get_allocation()
            xp = self.get_property("tab_hborder")
            yp = self.get_property("tab_vborder")
            x_min = x0 + x - 2 * xp
            x_max = x0 + x + w + 2 * xp
            y_min = y0 + y - 2 * yp
            y_max = y0 + y + h + 2 * yp
            if (x_root >= x_min and x_root <= x_max and
                y_root >= y_min and y_root <= y_max):
                return view
        return None

    def _on_button_press_event(self, event):
        view = self._find_view_at(event.x_root, event.y_root)
        if view is not None:
            if event.button == 2 and event.type == gtk.gdk.BUTTON_PRESS:
                self.emit("remove-view-request", view)
            elif event.button == 3:
                self._show_context_menu(event, view)
                # Consume the event to avoid switching the page on right click
                # events.
                return True

        # No tab hit.
        elif (event.button == 2 and event.type == gtk.gdk.BUTTON_PRESS or
              (event.button == 1 and event.type == gtk.gdk._2BUTTON_PRESS)):
            self.emit("view-requested")

        elif event.button == 3:
            self._show_context_menu(event)

        return False

    def _on_drag_data_received(
        self, drag_context, x, y, selection_data, info, time):
        print_w("TODO")

    def _on_switch_page(self, page, page_num):
        self.emit("view-changed", self.get_nth_page(page_num))
        return False

    def _show_context_menu(self, event, view=None):
        menu = blaguiutils.BlaPopupMenu(event)
        if view is None:
            menu.append_item("New playlist", self.emit, "view-requested")
        else:
            view.add_context_menu_options(menu)
        menu.run()

    def get_num_views(self):
        return self.get_n_pages()

    def remove_view(self, view):
        page_num = self.page_num(view)
        if page_num != -1:
            self.remove_page(page_num)

    def focus_view(self, view):
        page_num = self.page_num(view)
        self.set_current_page(page_num)

    def append_view(self, view):
        self.append_page(view, view.get_header())
        self.set_tab_reorderable(view, True)

    def get_current_view(self):
        return self.get_nth_page(self.get_current_page())

