# blaplay, Copyright (C) 2012  Niklas Koep

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

from collections import OrderedDict
import cPickle as pickle
import os
import re
import time

import cairo
import gobject
import gtk
import pango
import pangocairo

from blaplay import blautil, blagui
from blaplay.blacore import blaconst
from blaplay.blagui import blaguiutil
from blaplay.blagui.blawindows import BlaScrolledWindow
from .blabrowser import BlaBrowser, BlaBrowserTreeView
from .blalibrarymodel import BlaLibraryModel
from .blalibrarycontroller import BlaLibraryController

PADDING_X, PADDING_Y, PADDING_WIDTH, PADDING_HEIGHT = -2, 0, 4, 0


def create_browser(config, library, view):
    browser = BlaLibraryBrowser(config)
    BlaLibraryController(config, library, browser, view)
    return browser


class _BlaCellRenderer(blaguiutil.BlaCellRendererBase):
    __gproperties__ = {
        "text": (gobject.TYPE_STRING, "text", "", "", gobject.PARAM_READWRITE)
    }

    def get_layout(self, *args):
        if len(args) == 1:
            treeview, text = args[0], ""
        else:
            treeview, text = args

        context = treeview.get_pango_context()
        layout = pango.Layout(context)
        fdesc = gtk.widget_get_default_style().font_desc
        layout.set_font_description(fdesc)

        if not text:
            try:
                text = self.get_property("text")
            except AttributeError:
                text = ""
        layout.set_text(text)
        return layout

    def on_get_size(self, widget, cell_area):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 0, 0)
        cr = cairo.Context(surface)
        pc_context = pangocairo.CairoContext(cr)
        layout = self.get_layout(widget)
        width, height = layout.get_pixel_size()
        return (0, 0, width, height)

    def on_render(self, window, widget, background_area, cell_area,
                  expose_area, flags):
        style = widget.get_style()
        text_color = str(style.text[gtk.STATE_NORMAL])
        active_text_color = str(style.text[gtk.STATE_SELECTED])
        selected_row_color = str(style.base[gtk.STATE_SELECTED])
        background_color = str(style.base[gtk.STATE_NORMAL])

        # Render the background.
        cr = window.cairo_create()
        color = gtk.gdk.color_parse(background_color)
        cr.set_source_color(color)

        pc_context = pangocairo.CairoContext(cr)
        pc_context.rectangle(*background_area)
        pc_context.fill()

        # Render active resp. inactive rows
        layout = self.get_layout(widget)
        layout.set_font_description(widget.get_style().font_desc)
        width, height = layout.get_pixel_size()

        use_highlight_color = flags & gtk.CELL_RENDERER_SELECTED
        if use_highlight_color:
            color = gtk.gdk.color_parse(selected_row_color)
        else:
            color = gtk.gdk.color_parse(background_color)
        cr.set_source_color(color)
        pc_context.rectangle(
             cell_area.x + PADDING_X, cell_area.y + PADDING_Y,
             width + PADDING_WIDTH, cell_area.height + PADDING_HEIGHT)
        pc_context.fill()

        # Set font, font color and the text to render
        if use_highlight_color:
            color = gtk.gdk.color_parse(active_text_color)
        else:
            color = gtk.gdk.color_parse(text_color)
        cr.set_source_color(color)
        pc_context.move_to(cell_area.x, cell_area.y)
        pc_context.show_layout(layout)

class BlaLibraryBrowser(BlaBrowser):
    ID = blaconst.BROWSER_LIBRARY

    _ORGANIZE_BY_MAPPING = OrderedDict([
        ("directory", blaconst.ORGANIZE_BY_DIRECTORY),
        ("artist", blaconst.ORGANIZE_BY_ARTIST),
        ("artist - album", blaconst.ORGANIZE_BY_ARTIST_ALBUM),
        ("album", blaconst.ORGANIZE_BY_ALBUM),
        ("genre", blaconst.ORGANIZE_BY_GENRE),
        ("year", blaconst.ORGANIZE_BY_YEAR)
    ])

    __gsignals__ = {
        "model-requested": blautil.signal(1),
        "queue-uris": blautil.signal(1)
    }

    def _create_treeview(self):
        treeview = BlaBrowserTreeView()
        # Fixed-height mode is faster, but it messes up our horizontal
        # scrollbars in the library browser treeview.
        treeview.set_fixed_height_mode(False)
        column = gtk.TreeViewColumn()
        column.set_sizing(gtk.TREE_VIEW_COLUMN_AUTOSIZE)
        treeview.append_column(column)

        treeview.enable_model_drag_source(
            gtk.gdk.BUTTON1_MASK,
            [blagui.DND_TARGETS[blagui.DND_LIBRARY]],
            gtk.gdk.ACTION_COPY)

        treeview.connect(
            "button-press-event", self._on_button_press_event)
        treeview.connect("drag-data-get", self._on_drag_data_get)
        treeview.connect("key-press-event", self._on_key_press_event)
        treeview.connect("popup", self._on_popup)
        treeview.connect_object(
            "row-collapsed", BlaLibraryBrowser._on_row_collapsed, self)
        treeview.connect("row-expanded", self._on_row_expanded)

        return treeview

    def __init__(self, config, *args, **kwargs):
        super(BlaLibraryBrowser, self).__init__("Library", *args, **kwargs)
        self._config = config
        config.connect_object(
            "changed", BlaLibraryBrowser._on_config_changed, self)

        self._expanded_rows = []
        self._treeview = self._create_treeview()
        sw = BlaScrolledWindow()
        sw.add(self._treeview)

        hbox = gtk.HBox()

        self._combobox = gtk.combo_box_new_text()
        model = gtk.ListStore(gobject.TYPE_STRING, gobject.TYPE_INT)
        for label, id_ in self._ORGANIZE_BY_MAPPING.items():
            model.append([label, id_])
        self._combobox.set_model(model)
        self._combobox.connect("changed", self._on_organize_by_changed)

        alignment = gtk.Alignment()
        alignment.add(gtk.Label("Organize by:"))
        table = gtk.Table(rows=2, columns=1, homogeneous=False)
        table.attach(alignment, 0, 1, 0, 1, xpadding=2, ypadding=2)
        table.attach(self._combobox, 0, 1, 1, 2)
        hbox.pack_start(table, expand=False)

        self._entry = gtk.Entry()
        self._entry.set_icon_from_stock(
            gtk.ENTRY_ICON_SECONDARY, gtk.STOCK_CLEAR)
        self._entry.connect(
            "icon-release", lambda *x: x[0].delete_text(0, -1))
        self._entry.connect("changed", self._on_filter_entry_changed)
        self._entry.connect_object(
            "activate", BlaLibraryBrowser.request_model, self)

        button = gtk.Button()
        button.add(
            gtk.image_new_from_stock(gtk.STOCK_FIND,
                                     gtk.ICON_SIZE_SMALL_TOOLBAR))
        button.connect(
            "clicked", BlaLibraryBrowser.request_model, self)

        alignment = gtk.Alignment()
        alignment.add(gtk.Label("Filter:"))
        table = gtk.Table(rows=2, columns=1, homogeneous=False)
        table.attach(alignment, 0, 1, 0, 1, xpadding=2, ypadding=2)
        hbox2 = gtk.HBox()
        hbox2.pack_start(self._entry, expand=True)
        hbox2.pack_start(button, expand=False)
        table.attach(hbox2, 0, 1, 1, 2)
        hbox.pack_start(table)

        self.pack_start(sw, expand=True)
        self.pack_start(hbox, expand=False)

        self._update_browser_style()

    def _on_config_changed(self, section, key):
        if section == "library" and key == "custom.browser":
            self._update_browser_style()

    def _update_browser_style(self):
            self._set_treeview_style(
                self._config.getboolean("library", "custom.browser"))

    def _set_treeview_style(self, use_custom_browser):
        column = self._treeview.get_column(0)
        column.clear()

        if use_custom_browser:
            renderer = _BlaCellRenderer()
        else:
            renderer = gtk.CellRendererText()
        column.pack_start(renderer)
        def cdf(column, renderer, model, iterator):
            n_children = model.iter_n_children(iterator)
            text = model[iterator][1]
            if n_children > 0:
                text = "%s (%d)" % (text, n_children)
            renderer.set_property("text", text)
        column.set_cell_data_func(renderer, cdf)

    def _on_key_press_event(self, treeview, event):
        if blagui.is_accel(event, "Q"):
            self._send_selection_to_queue()

        elif (blagui.is_accel(event, "Return") or
              blagui.is_accel(event, "KP_Enter")):
            # TODO: Factor this into a method.
            name = treeview.get_name_from_path()
            uris = treeview.get_uris()
            self.emit("key-action", name, uris)
        return False

    def _on_button_press_event(self, treeview, event):
        is_double_click = (event.button == 1 and
                           event.type == gtk.gdk._2BUTTON_PRESS)
        is_middle_click = (event.button == 2 and
                           event.type == gtk.gdk.BUTTON_PRESS)
        # Return on events that don't require any special treatment.
        if not is_double_click and not is_middle_click:
            return False

        path = treeview.get_path_at_pos(*map(int, [event.x, event.y]))[0]

        # XXX: On middle-clicks we must update the selection due to the way DND
        #      is implemented. This really ought to be fixed...
        if event.button == 2:
            selection = treeview.get_selection()
            selection.unselect_all()
            selection.select_path(path)

        name = treeview.get_name_from_path(path)
        uris = treeview.get_uris()
        if is_double_click:
            signal = "button-action-double-click"
        else:
            signal = "button-action-middle-click"
        self.emit(signal, name, uris)
        return False

    def _add_context_menu_options(self, menu):
        # TODO
        return
        # XXX: Append with "Q" accelerator.
        menu.append_item_with_accelerator(
            "Q", "Add to playback queue", self._send_selection_to_queue)

    def _send_selection_to_queue(self):
        uris = self._treeview.get_uris(n_max=blaconst.QUEUE_MAX_ITEMS)
        self.emit("queue-uris", uris)

    def _on_filter_entry_changed(self, entry):
        filter_string = entry.get_text()
        if not filter_string:
            entry.activate()

    def _on_drag_data_get(self, treeview, drag_context, selection_data, info,
                          timestamp):
        # TODO: Send a name with the DND data for when we drop on the playlist
        #       tab strip.
        name = treeview.get_name_from_path()
        uris = treeview.get_uris()
        # TODO: We could use set_uris() here as well which would allow DND
        #       from the library to external applications like file managers.
        data = pickle.dumps(uris, protocol=pickle.HIGHEST_PROTOCOL)
        selection_data.set("", 8, data)

    def _on_row_collapsed(self, iterator, path):
        try:
            self._expanded_rows.remove(path)
        except ValueError:
            pass

    def _on_row_expanded(self, treeview, iterator, path):
        def expand_row(model, path, iterator):
            if path in self._expanded_rows:
                treeview.expand_row(path, open_all=False)

        if self._expanded_rows:
            treeview.get_model().foreach(expand_row)
        if not path in self._expanded_rows:
            self._expanded_rows.append(path)

    def _on_organize_by_changed(self, combobox):
        view = combobox.get_active()
        self.request_model()

    def request_model(self):
        self.emit("model-requested", self._entry.get_text().strip())

    def set_organize_by(self, organize_by):
        # TODO: Subclass gtk.ComboBox to provide a more convenient API for this
        #       kind of operation. We could re-use it for the play order
        #       combobox, as well as for several comboboxes in the settings
        #       page. See
        #       http://www.pygtk.org/pygtk2reference/class-gtkcombobox.html#method-gtkcombobox--set-model
        active = 0
        for idx, row in enumerate(self._combobox.get_model()):
            if row[1] == organize_by:
                active = idx
                break
        self._combobox.set_active(active)

    def get_organize_by(self):
        return self._ORGANIZE_BY_MAPPING[self._combobox.get_active_text()]

    def set_model(self, model):
        self._expanded_rows = []
        self._treeview.set_model(model)
        # XXX: This is just a silly special case that we need because  we use a
        #      "bla" root node for shits and giggles when we organize by
        #      directory. It might go away in the future.
        if (model.organize_by == blaconst.ORGANIZE_BY_DIRECTORY and
            model.get_iter_first()):
            self._treeview.expand_row((0,), open_all=False)

