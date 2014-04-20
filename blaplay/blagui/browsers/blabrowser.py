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

import os

import gtk

from blaplay import blagui, blautil
from .. import blaguiutils


class BlaBrowserTreeView(blaguiutils.BlaTreeViewBase):
    def __init__(self):
        super(BlaBrowserTreeView, self).__init__()

        self._renderer = 0
        self._text_column = 1

        self.set_headers_visible(False)
        self.set_enable_tree_lines(True)
        self.set_fixed_height_mode(True)
        self.set_reorderable(False)
        self.set_rubber_banding(True)
        self.set_property("rules_hint", True)

    def _accept_button_event(self, column, path, event, check_expander):
        # TODO: Add a stub for this in BlaTreeViewBase and call it in the
        #       default button handler.
        # if (not blacfg.getboolean("library", "custom.browser") or
        #     self._multicol or self._renderer is None):
        #     return True
        return True

        renderer = column.get_cell_renderers()[self._renderer]
        model = self.get_model()
        iterator = model.get_iter(path)

        layout = renderer.get_layout(
            self, model.get_value(iterator, self._text_column))
        width = layout.get_pixel_size()[0]
        cell_area = self.get_cell_area(path, column)
        expander_size = self.style_get_property("expander_size")

        # Check the vertical coordinates of click event.
        if not (event.y >= cell_area.y+PADDING_Y and
                event.y <= cell_area.y+cell_area.height):
            return False

        # Check for a click on the expander and if the row has children.
        if (check_expander and
            event.x >= cell_area.x+PADDING_X-expander_size and
            event.x <= cell_area.x+PADDING_X and
            model.iter_has_child(iterator) and
            event.type == gtk.gdk.BUTTON_PRESS):
            return True

        # check for click in the highlighted area
        if (event.x >= cell_area.x+PADDING_X and
            event.x <= cell_area.x+width):
            return True

        return False

    def get_uris(self, n_max=None):
        def get_children(model, iterator):
            children = []
            extend = children.extend
            append = children.append

            if model.iter_has_child(iterator):
                child = model.iter_children(iterator)
                while child:
                    if model.iter_has_child(child):
                        extend(get_children(model, child))
                    else:
                        append(child)
                    child = model.iter_next(child)
            else:
                append(iterator)
            return children

        uris = []
        model, paths = self.get_selection().get_selected_rows()
        get_iter = model.get_iter
        for path in paths:
            iterator = get_iter(path)
            iterators = get_children(model, iterator)
            uris.extend([model[iterator][0] for iterator in iterators])
            if n_max is not None and len(uris) > n_max:
                break

        return uris[slice(0, n_max)]

class BlaBrowser(gtk.VBox):
    __gsignals__ = {
        "add-to-current-playlist": blautil.signal(2),
        "button-action-double-click": blautil.signal(2),
        "button-action-middle-click": blautil.signal(2),
        "key-action": blautil.signal(2),
        "send-to-current-playlist": blautil.signal(2),
        "send-to-new-playlist": blautil.signal(2)
    }

    def __init__(self, name):
        super(BlaBrowser, self).__init__()
        self._name = name

    def _add_context_menu_options(self, menu):
        pass

    def _on_popup(self, treeview, event):
        try:
            path = treeview.get_path_at_pos(*map(int, [event.x, event.y]))[0]
        except TypeError:
            return None

        def transfer_uris_to_playlist(signal, name):
            self.emit(signal, name, treeview.get_uris())
        name = treeview.get_model()[path][-1]
        items = [
            ("Send to current playlist", "send-to-current-playlist"),
            ("Add to current playlist", "add-to-current-playlist"),
            ("Send to new playlist", "send-to-new-playlist")
        ]
        menu = blaguiutils.BlaMenu(event)
        for label, signal in items:
            menu.append_item(label, transfer_uris_to_playlist, signal, name)
        menu.append_separator()

        # Let subclasses add their specific context menu options.
        self._add_context_menu_options(menu)
        if not menu.is_last_item_separator():
            menu.append_separator()

        def open_directory():
            def dirname(path):
                return path if os.path.isdir(path) else os.path.dirname(path)
            uris = treeview.get_uris()
            directory = list(set(map(dirname, uris)))
            if len(directory) == 1 and os.path.isdir(directory[0]):
                blautil.open_directory(directory[0])
        menu.append_item("Open directory", open_directory)
        menu.run()

    @property
    def name(self):
        return self._name

