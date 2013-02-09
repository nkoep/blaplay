# -*- coding: utf-8 -*-
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

import os
import cPickle as pickle
import time
import urllib
import re

import gobject
import gtk
import gio
import cairo
import pango
import pangocairo

import blaplay
library = blaplay.bla.library
from blaplay.blacore import blaconst, blacfg
from blaplay import blautil, blagui
from blaplaylist import BlaPlaylistManager, BlaQueue
from blavisualization import BlaVisualization
from blatagedit import BlaTagedit
from blaplay.blagui import blaguiutils
from blaplay.formats._identifiers import *


class BlaCellRenderer(blaguiutils.BlaCellRendererBase):
    __gproperties__ = {
        "text": (gobject.TYPE_STRING, "text", "", "", gobject.PARAM_READWRITE)
    }

    def __init__(self):
        super(BlaCellRenderer, self).__init__()

    def get_layout(self, *args):
        if len(args) == 1: tv, text = args[0], ""
        else: tv, text = args

        context = tv.get_pango_context()
        layout = pango.Layout(context)
        fdesc = gtk.widget_get_default_style().font_desc
        layout.set_font_description(fdesc)

        if text: layout.set_text(text)
        else:
            try: text = self.get_property("text")
            except AttributeError: text = ""
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
        if blacfg.getboolean("colors", "overwrite"):
            text_color = self._text_color
            active_text_color = self._active_text_color
            selected_row_color = self._selected_row_color
            background_color = self._background_color
        else:
            style = widget.get_style()
            text_color = str(style.text[gtk.STATE_NORMAL])
            active_text_color = str(style.text[gtk.STATE_SELECTED])
            selected_row_color = str(style.base[gtk.STATE_SELECTED])
            background_color = str(style.base[gtk.STATE_NORMAL])

        # render background
        cr = window.cairo_create()
        color = gtk.gdk.color_parse(background_color)
        cr.set_source_color(color)

        pc_context = pangocairo.CairoContext(cr)
        pc_context.rectangle(*background_area)
        pc_context.fill()

        # render active resp. inactive rows
        layout = self.get_layout(widget)
        layout.set_font_description(widget.get_style().font_desc)
        width, height = layout.get_pixel_size()

        if (flags == (gtk.CELL_RENDERER_SELECTED|gtk.CELL_RENDERER_PRELIT) or
                flags == gtk.CELL_RENDERER_SELECTED):
            color = gtk.gdk.color_parse(selected_row_color)
        else: color = gtk.gdk.color_parse(background_color)
        cr.set_source_color(color)
        pc_context.rectangle(
                cell_area.x + blaguiutils.PADDING_X,
                cell_area.y + blaguiutils.PADDING_Y,
                width + blaguiutils.PADDING_WIDTH,
                cell_area.height + blaguiutils.PADDING_HEIGHT
        )
        pc_context.fill()

        # set font, font color and the text to render
        if (flags == (gtk.CELL_RENDERER_SELECTED|gtk.CELL_RENDERER_PRELIT) or
                flags == gtk.CELL_RENDERER_SELECTED):
            color = gtk.gdk.color_parse(active_text_color)
        else: color = gtk.gdk.color_parse(text_color)
        cr.set_source_color(color)
        pc_context.move_to(cell_area.x, cell_area.y)
        pc_context.show_layout(layout)

gobject.type_register(BlaCellRenderer)

class BlaTreeView(blaguiutils.BlaTreeViewBase):
    def __init__(self, parent, multicol, browser_id):
        super(BlaTreeView, self).__init__(
                multicol=multicol, renderer=0, text_column=1)

        self.__parent = parent
        self.__browser_id = browser_id

        self.set_fixed_height_mode(True)
        self.set_reorderable(False)
        self.set_rubber_banding(True)
        self.set_property("rules_hint", True)

        self.connect(
                "key_press_event", self.__key_press_event)
        self.connect_object(
                "button_press_event", BlaTreeView.__button_press_event, self)
        self.connect_object("popup", BlaTreeView.__popup_menu, self)

    def __send_to_queue(self):
        count = blaconst.QUEUE_MAX_ITEMS - BlaQueue.queue_n_tracks()
        tracks = self.get_tracks(count=count)
        BlaQueue.queue_tracks(tracks, None)

    def get_tracks(self, count=-1):
        def get_children(model, iterator):
            children = []

            if model.iter_has_child(iterator):
                child = model.iter_children(iterator)
                while child:
                    if model.iter_has_child(child):
                        children += get_children(model, child)
                    else: children.append(child)

                    child = model.iter_next(child)
            else: children.append(iterator)

            return children

        selections = []
        model, paths = self.get_selection().get_selected_rows()

        for p in paths:
            iterator = model.get_iter(p)
            iterators = get_children(model, iterator)
            for it in iterators: selections.append(model.get_value(it, 0))
            if count != -1 and len(selections) > count: break

        return selections[:count] if count != -1 else selections

    def __key_press_event(self, treeview, event):
        if self.__browser_id == blaconst.BROWSER_FILESYSTEM: return False

        if blagui.is_accel(event, "Q"):
            self.__send_to_queue()

        elif blagui.is_accel(event, "<Alt>Return"):
            tracks = self.get_tracks()
            if tracks: BlaTagedit(tracks)

        elif (blagui.is_accel(event, "Return") or
                blagui.is_accel(event, "KP_Enter")):
            action = blacfg.getint("library", "return.action")

            selections = self.get_selection().get_selected_rows()[-1]
            if not selections: return True
            name = self.get_model()[selections[0]][2]
            tracks = self.get_tracks()

            if action == blaconst.ACTION_SEND_TO_CURRENT:
                f = BlaPlaylistManager.send_to_current_playlist
            elif action == blaconst.ACTION_ADD_TO_CURRENT:
                f = BlaPlaylistManager.add_to_current_playlist
            elif action == blaconst.ACTION_SEND_TO_NEW:
                f = BlaPlaylistManager.send_to_new_playlist
            f(name, tracks)

        return False

    def __button_press_event(self, event):
        if self.__browser_id == blaconst.BROWSER_FILESYSTEM: return False

        # return on events that don't warrant any special treatment
        if ((event.button == 1 and not (event.type == gtk.gdk._2BUTTON_PRESS or
                event.type == gtk.gdk._3BUTTON_PRESS)) or
                event.type == gtk.gdk._3BUTTON_PRESS or
                (event.button == 2 and event.type == gtk.gdk._2BUTTON_PRESS)):
            return False

        if event.button == 1:
            action = blacfg.getint("library", "doubleclick.action")
        elif event.button == 2:
            action = blacfg.getint("library", "middleclick.action")

        path = self.get_path_at_pos(*map(int, [event.x, event.y]))[0]

        # handle LMB events
        if event.button == 1 and action == 3:
            if self.row_expanded(path): self.collapse_row(path)
            else: self.expand_row(path, open_all=False)
            return False

        # on middle-clicks we must update the selection due to the way the DND
        # treeview is implemented
        if event.button == 2:
            selection = self.get_selection()
            selection.unselect_all()
            selection.select_path(path)

        model = self.get_model()
        name = model[path][2]
        tracks = self.get_tracks()

        if action == blaconst.ACTION_SEND_TO_CURRENT:
            f = BlaPlaylistManager.send_to_current_playlist
        elif action == blaconst.ACTION_ADD_TO_CURRENT:
            f = BlaPlaylistManager.add_to_current_playlist
        elif action == blaconst.ACTION_SEND_TO_CURRENT:
            f = BlaPlaylistManager.send_to_new_playlist
        f(name, tracks)

        return False

    def __popup_menu(self, event):
        model = self.get_model()
        try: path = self.get_path_at_pos(*map(int, [event.x, event.y]))[0]
        except TypeError: return

        if self.__browser_id == blaconst.BROWSER_FILESYSTEM:
            dirname = lambda s: s if os.path.isdir(s) else os.path.dirname(s)
            resolve = True
        else:
            dirname = os.path.dirname
            resolve = False

        name = model[path][2]
        tracks = self.get_tracks()
        directory = list(set(map(dirname, tracks)))
        if len(directory) == 1 and os.path.isdir(directory[0]):
            directory = directory[0]
        else: directory = None

        items = [
            ("Send to current playlist", None,
                    BlaPlaylistManager.send_to_current_playlist, True),
            ("Add to current playlist", None,
                    BlaPlaylistManager.add_to_current_playlist, True),
            ("Send to new playlist", None, BlaPlaylistManager.send_to_new_playlist,
                    True),
            None
        ]
        if self.__browser_id == blaconst.BROWSER_LIBRARY:
            items.extend([
                ("Add to playback queue", "Q", lambda *x:
                        self.__send_to_queue(), True),
                ("Open containing directory", None, lambda *x:
                        blautil.open_directory(directory), bool(directory)),
                None,
                ("Properties", "<Alt>Return", lambda *x:
                        BlaTagedit(tracks) if tracks else True, True)
            ])
        else:
            items.extend([("Open containing directory", None, lambda *x:
                    blautil.open_directory(directory), bool(directory))])

        menu = gtk.Menu()
        for item in items:
            if item is None: m = gtk.SeparatorMenuItem()
            else:
                label, accel, callback, sensitive = item
                m = gtk.MenuItem(label)
                if accel is not None:
                    mod, key = gtk.accelerator_parse(accel)
                    m.add_accelerator("activate",
                            blagui.accelgroup, mod, key, gtk.ACCEL_VISIBLE)
                m.connect("activate",
                        lambda x, c=callback: c(name, tracks, resolve))
                m.set_sensitive(sensitive)
            menu.append(m)

        menu.show_all()
        menu.popup(None, None, None, event.button, event.time)

class BlaQuery(object):
    def __init__(self, tokens):
        if tokens:
            self.__res = [re.compile(t.decode("utf-8"),
                    re.UNICODE | re.IGNORECASE) for t in map(re.escape, tokens)]
            self.query = self.__query
        else: self.query = lambda *x: True

    def __query(self, track):
        strings = [track[identifier] for identifier in [ARTIST, TITLE, ALBUM]]

        if (blacfg.getint("library", "organize.by") ==
                blaconst.ORGANIZE_BY_DIRECTORY):
            strings.append(track.basename)

        for r in self.__res:
            search = r.search
            for string in strings:
                if search(string): break
            else: return False
        return True

class BlaLibraryBrowser(gtk.VBox):
    __fid = -1
    __filter_parameters = []
    __expanded_rows = []
    __model = None

    def __init__(self, parent):
        super(BlaLibraryBrowser, self).__init__()

        self.__treeview = BlaTreeView(parent=parent, multicol=False,
                browser_id=blaconst.BROWSER_LIBRARY)
        self.__treeview.set_headers_visible(False)
        column = gtk.TreeViewColumn("Library")
        column.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        self.__treeview.append_column(column)
        self.__treeview.connect("row_collapsed", self.__row_collapsed)
        self.__treeview.connect("row_expanded", self.__row_expanded)

        self.__treeview.enable_model_drag_source(gtk.gdk.BUTTON1_MASK,
                [("tracks/library", gtk.TARGET_SAME_APP, 0)],
                gtk.gdk.ACTION_COPY
        )
        self.__treeview.connect_object(
                "drag_data_get", BlaLibraryBrowser.__drag_data_get, self)

        sw = blaguiutils.BlaScrolledWindow()
        sw.add(self.__treeview)

        hbox = gtk.HBox()

        cb = gtk.combo_box_new_text()
        for label in ["directory", "artist", "artist - album", "album",
                "genre", "year"]:
            cb.append_text(label)
        cb.set_active(blacfg.getint("library", "organize.by"))
        cb.connect("changed", self.__organize_by_changed)

        alignment = gtk.Alignment()
        alignment.add(gtk.Label("Organize by:"))
        table = gtk.Table(rows=2, columns=1, homogeneous=False)
        table.attach(alignment, 0, 1, 0, 1, xpadding=2, ypadding=2)
        table.attach(cb, 0, 1, 1, 2)
        hbox.pack_start(table, expand=False)

        entry = gtk.Entry()
        entry.set_icon_from_stock(
                gtk.ENTRY_ICON_SECONDARY, gtk.STOCK_CLEAR)
        entry.connect("icon_release", lambda *x: x[0].delete_text(0, -1))
        entry.connect("changed", self.__update_filter_parameters)
        entry.connect("activate", self.__update_treeview)

        button = gtk.Button()
        button.add(gtk.image_new_from_stock(
                gtk.STOCK_FIND, gtk.ICON_SIZE_BUTTON))
        button.connect("clicked", self.__update_treeview)

        alignment = gtk.Alignment()
        alignment.add(gtk.Label("Filter:"))
        table = gtk.Table(rows=2, columns=1, homogeneous=False)
        table.attach(alignment, 0, 1, 0, 1, xpadding=2, ypadding=2)
        hbox2 = gtk.HBox()
        hbox2.pack_start(entry, expand=True)
        hbox2.pack_start(button, expand=False)
        table.attach(hbox2, 0, 1, 1, 2)
        hbox.pack_start(table)

        self.pack_start(sw, expand=True)
        self.pack_start(hbox, expand=False)

        self.update_colors()

        library.connect(
                "update_library_browser", self.__update_library_contents)
        library.request_model(blacfg.getint("library", "organize.by"))

    def __update_filter_parameters(self, entry):
        self.__filter_parameters = entry.get_text().strip().split()
        if (blacfg.getboolean("playlist", "search.after.timeout") or
                not self.__filter_parameters):
            try: gobject.source_remove(self.__fid)
            except AttributeError: pass
            def activate():
                entry.activate()
                return False
            self.__fid = gobject.timeout_add(500, activate)

    def __drag_data_get(self, drag_context, selection_data, info, timestamp):
        data = self.__treeview.get_tracks()
        data = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
        selection_data.set("", 8, data)

    def __row_collapsed(self, treeview, iterator, path):
        try: self.__expanded_rows.remove(path)
        except ValueError: return

    def __row_expanded(self, treeview, iterator, path):
        def expand_row(model, path, iterator):
            if path in self.__expanded_rows:
                treeview.expand_row(path, open_all=False)

        if self.__expanded_rows: treeview.get_model().foreach(expand_row)
        if not path in self.__expanded_rows: self.__expanded_rows.append(path)

    def __update_library_contents(self, library, model):
        print_d("Updating library browser")
        self.__expanded_rows = []
        self.__model = model
        self.__update_treeview()

    def __update_treeview(self, *args):
        def check_children(model, iterator, query):
            iter_has_child = model.iter_has_child
            iter_children = model.iter_children
            iter_next = model.iter_next
            get_path = model.get_path

            count_local = 0
            count_sub = 0

            while iterator:
                if iter_has_child(iterator):
                    child = iter_children(iterator)
                    count = check_children(model, child, query)
                    if count == 0:
                        path = get_path(iterator)
                        self.__row_collapsed(None, None, path)
                        model[iterator][3] = False
                    else:
                        count_sub += 1
                        model[iterator][3] = True
                        model[iterator][1] = "%s (%d)" % (
                                model[iterator][2], count)
                else:
                    state = query(library[model[iterator][0]])
                    model[iterator][3] = state
                    count_local += int(state)

                iterator = iter_next(iterator)
            return count_local + count_sub

        filt = self.__model.get_model()
        model = filt.get_model()
        iterator = model.get_iter_first()
        query = BlaQuery(self.__filter_parameters).query
        check_children(model, iterator, query)

        self.__treeview.freeze_notify()
        self.__treeview.freeze_child_notify()
        self.__treeview.set_model(None)
        self.__treeview.set_model(self.__model)
        organize_by = blacfg.getint("library", "organize.by")
        if (organize_by == blaconst.ORGANIZE_BY_DIRECTORY and
                model.get_iter_first()):
            self.__treeview.expand_row((0,), open_all=False)
        self.__treeview.thaw_child_notify()
        self.__treeview.thaw_notify()

    def __organize_by_changed(self, combobox):
        view = combobox.get_active()
        blacfg.set("library", "organize.by", view)
        library.request_model(view)

    def update_colors(self):
        column = self.__treeview.get_column(0)
        column.clear()

        if blacfg.getboolean("library", "custom.browser"):
            renderer = BlaCellRenderer()
            renderer.update_colors()
        else: renderer = gtk.CellRendererText()

        column.pack_start(renderer, expand=True)
        column.add_attribute(renderer, "text", 1)

    def update_tree_lines(self):
        self.__treeview.set_enable_tree_lines(
                blacfg.getboolean("general", "draw.tree.lines"))

class BlaFileBrowser(gtk.VBox):
    __layout = [
        gobject.TYPE_STRING,    # uri
        gtk.gdk.Pixbuf,         # pixbuf
        gobject.TYPE_STRING,    # label
    ]

    __fid = -1
    __uid = -1
    __filter_parameters = []

    class History(object):
        """
        History class which stores paths to previously visited directories.
        """

        def __init__(self):
            super(BlaFileBrowser.History, self).__init__()
            self.__model = gtk.ListStore(gobject.TYPE_PYOBJECT)
            self.__iterator = None

        def add(self, item):
            insert_func = self.__model.insert_after
            self.__iterator = insert_func(self.__iterator, [item])

        def get(self, next):
            if next: f = self.__model.iter_next
            else: f = self.__iter_previous

            try: iterator = f(self.__iterator)
            except TypeError: iterator = None

            if not iterator: item = None
            else:
                item = self.__model[iterator][0]
                self.__iterator = iterator
            return item

        def __iter_previous(self, iterator):
            path = self.__model.get_path(iterator)
            if path[0] > 0: return self.__model.get_iter((path[0]-1,))
            return None

    def __init__(self, parent):
        super(BlaFileBrowser, self).__init__()

        self.__pixbufs = {
            "directory": self.__get_pixbuf(gtk.STOCK_DIRECTORY),
            "file": self.__get_pixbuf(gtk.STOCK_FILE)
        }

        self.__history = BlaFileBrowser.History()

        vbox = gtk.VBox()

        # the toolbar
        table = gtk.Table(rows=1, columns=6, homogeneous=False)

        back = gtk.Button()
        back.add(gtk.image_new_from_stock(
                gtk.STOCK_GO_BACK, gtk.ICON_SIZE_BUTTON))
        back.set_relief(gtk.RELIEF_NONE)
        back.connect("clicked",
                lambda *x: self.__update_from_history(backwards=True))
        table.attach(back, 0, 1, 0, 1, xoptions=not gtk.EXPAND)

        up = gtk.Button()
        up.add(gtk.image_new_from_stock(
                gtk.STOCK_GO_UP, gtk.ICON_SIZE_BUTTON))
        up.set_relief(gtk.RELIEF_NONE)
        up.connect("clicked", lambda *x:
                self.__update_model(os.path.dirname(self.__directory)))
        table.attach(up, 1, 2, 0, 1, xoptions=not gtk.EXPAND)

        forward = gtk.Button()
        forward.add(gtk.image_new_from_stock(
                gtk.STOCK_GO_FORWARD, gtk.ICON_SIZE_BUTTON))
        forward.set_relief(gtk.RELIEF_NONE)
        forward.connect("clicked",
                lambda *x: self.__update_from_history(backwards=False))
        table.attach(forward, 2, 3, 0, 1, xoptions=not gtk.EXPAND)

        self.__entry = gtk.Entry()
        self.__entry.connect("activate",
                lambda *x: self.__update_model(self.__entry.get_text()))
        table.attach(self.__entry, 3, 4, 0, 1)

        refresh = gtk.Button()
        refresh.add(gtk.image_new_from_stock(
                gtk.STOCK_REFRESH, gtk.ICON_SIZE_BUTTON))
        refresh.set_relief(gtk.RELIEF_NONE)
        refresh.connect("clicked",
                lambda *x: self.__update_model(refresh=True))
        table.attach(refresh, 4, 5, 0, 1, xoptions=not gtk.EXPAND)
        vbox.pack_start(table, expand=False, fill=False)

        # the treeview
        self.__treeview = BlaTreeView(parent=parent, multicol=True,
                browser_id=blaconst.BROWSER_FILESYSTEM)
        self.__treeview.set_enable_search(True)
        self.__treeview.set_search_column(2)
        self.__treeview.enable_model_drag_source(gtk.gdk.BUTTON1_MASK,
                [("tracks/filesystem", gtk.TARGET_SAME_APP, 1)],
                gtk.gdk.ACTION_COPY
        )
        self.__treeview.connect_object(
                "drag_data_get", BlaFileBrowser.__drag_data_get, self)
        model = gtk.ListStore(*self.__layout)
        self.__filt = model.filter_new()
        self.__filt.set_visible_func(self.__visible_func)
        self.__treeview.set_model(self.__filt)
        self.__directory = blacfg.getstring("general", "filesystem.directory")

        # name column
        c = gtk.TreeViewColumn("Name")
        c.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        c.set_resizable(True)
        c.set_expand(True)
        c.set_fixed_width(1)

        r = gtk.CellRendererPixbuf()
        r.set_property("xalign", 0.0)
        c.pack_start(r, expand=False)
        c.add_attribute(r, "pixbuf", 1)

        r = gtk.CellRendererText()
        r.set_property("xalign", 0.0)
        c.pack_start(r)
        c.add_attribute(r, "text", 2)
        r.set_property("ellipsize", pango.ELLIPSIZE_END)

        self.__treeview.append_column(c)

        # last modified column
        c = gtk.TreeViewColumn()
        c.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        c.set_resizable(True)

        title = "Last modified"
        label = gtk.Label(title)
        width = label.create_pango_layout(title).get_pixel_size()[0]
        c.set_title(title)

        r = gtk.CellRendererText()
        r.set_property("ellipsize", pango.ELLIPSIZE_END)
        c.pack_start(r)
        c.set_cell_data_func(r, self.__last_modified_cb)
        c.set_min_width(width + 12 + r.get_property("xpad"))

        self.__treeview.append_column(c)
        self.__treeview.connect("row_activated", self.__open)
        self.__update_model(self.__directory)
        self.__treeview.columns_autosize()

        sw = blaguiutils.BlaScrolledWindow()
        sw.add(self.__treeview)
        vbox.pack_start(sw, expand=True)

        # the search bar
        hbox = gtk.HBox()
        hbox.pack_start(gtk.Label("Filter:"), expand=False, padding=2)

        entry = gtk.Entry()
        entry.set_icon_from_stock(
                gtk.ENTRY_ICON_SECONDARY, gtk.STOCK_CLEAR)
        entry.connect("icon_release", lambda *x: x[0].delete_text(0, -1))
        entry.connect("changed", self.__filter_parameters_changed)
        entry.connect("activate", lambda *x: self.__filt.refilter())
        hbox.pack_start(entry, expand=True)

        button = gtk.Button()
        button.add(gtk.image_new_from_stock(
                gtk.STOCK_FIND, gtk.ICON_SIZE_BUTTON))
        button.connect("clicked", lambda *x: self.__filt.refilter())
        hbox.pack_start(button, expand=False)
        vbox.pack_start(hbox, expand=False)

        self.pack_start(vbox)

    def __get_pixbuf(self, icon_name):
        icon_theme = gtk.icon_theme_get_default()
        icon_info = icon_theme.lookup_icon(
                icon_name, gtk.ICON_SIZE_MENU, gtk.ICON_LOOKUP_USE_BUILTIN)
        if not icon_info: return None
        pb = icon_info.get_filename()
        try: pb = gtk.gdk.pixbuf_new_from_file(pb)
        except gobject.GError: pb = icon_info.get_builtin_pixbuf()
        if pb:
            w, h = gtk.icon_size_lookup(gtk.ICON_SIZE_MENU)
            pb = pb.scale_simple(w, h, gtk.gdk.INTERP_HYPER)
        return pb

    def __visible_func(self, model, iterator):
        if self.__filter_parameters:
            try: label = model[iterator][2].lower()
            except AttributeError: return True
            for p in self.__filter_parameters:
                if p not in label: return False
        return True

    def __filter_parameters_changed(self, entry):
        self.__filter_parameters = entry.get_text().strip().split()
        if (blacfg.getboolean("general", "search.after.timeout") or
                not self.__filter_parameters):
            try: gobject.source_remove(self.__fid)
            except AttributeError: pass
            def activate():
                self.__filt.refilter()
                return False
            self.__fid = gobject.timeout_add(500, activate)

    def __update_model(self, directory=None, refresh=False,
            add_to_history=True):
        if not refresh:
            if directory and not directory.startswith("/"):
                directory = os.path.join(self.__directory, directory)
            if directory and not os.path.exists(directory):
                blaguiutils.error_dialog("Could not find \"%s\"." % directory,
                        "Please check the spelling and try again.")
                return False

            if not directory or not os.path.exists(directory):
                self.__directory = os.path.expanduser("~")
            else: self.__directory = os.path.abspath(directory)

            self.__entry.set_text(self.__directory)
            blacfg.set("general", "filesystem.directory", self.__directory)
            if add_to_history: self.__history.add(self.__directory)

        model = self.__filt.get_model()
        self.__treeview.freeze_child_notify()
        model.clear()

        for dirpath, dirnames, filenames in os.walk(self.__directory):
            for d in sorted(dirnames, key=str.lower):
                if d.startswith("."): continue
                path = os.path.join(self.__directory, d)
                model.append([path, self.__pixbufs["directory"], d])

            for f in sorted(filenames, key=str.lower):
                if f.startswith("."): continue
                path = os.path.join(self.__directory, f)
                mimetype = gio.content_type_guess(path)
                try: pb = self.__pixbufs[mimetype]
                except KeyError:
                    icon_names = gio.content_type_get_icon(mimetype)
                    pb = self.__pixbufs["file"]
                    if icon_names:
                        for icon_name in icon_names.get_names():
                            pb_new = self.__get_pixbuf(icon_name)
                            if pb_new:
                                self.__pixbufs[mimetype] = pb_new
                                pb = pb_new
                model.append([path, pb, f])
            break

        try: self.__monitor.cancel()
        except AttributeError: pass

        self.__monitor = gio.File(self.__directory).monitor_directory(
                flags=gio.FILE_MONITOR_NONE)
        self.__monitor.connect("changed", self.__process_event)

        self.__treeview.thaw_child_notify()
        return False

    def __process_event(self, monitor, filepath, other_filepath, type_):
        gobject.source_remove(self.__uid)
        self.__uid = gobject.timeout_add(2000, lambda *x:
                self.__update_model(refresh=True, add_to_history=False))

    def __update_from_history(self, backwards):
        if backwards: path = self.__history.get(next=False)
        else: path = self.__history.get(next=True)
        if path: self.__update_model(directory=path, add_to_history=False)

    def __open(self, treeview, path, column):
        model = treeview.get_model()
        entry = model[path][0]
        if os.path.isdir(entry):
            model = self.__update_model(entry)
            return True
        return False

    def __last_modified_cb(self, column, renderer, model, iterator):
        path = model[iterator][0]
        try: text = time.ctime(os.path.getmtime(path))
        except OSError: text = ""
        renderer.set_property("text", text)

    def __drag_data_get(self, drag_context, selection_data, info, timestamp):
        model = self.__treeview.get_model()
        paths = self.__treeview.get_selection().get_selected_rows()[-1]
        data = unicode("\n".join(map(lambda p: "file://%s"
                % urllib.quote(model[p][0]), paths)))
        selection_data.set("tracks", 8, data)

class BlaBrowsers(gtk.VBox):
    def __init__(self):
        super(BlaBrowsers, self).__init__(spacing=5)

        type(self).__library_browser = BlaLibraryBrowser(self)
        self.__file_browser = BlaFileBrowser(self)
        notebook = gtk.Notebook()
        notebook.append_page(self.__library_browser, gtk.Label("Library"))
        notebook.append_page(self.__file_browser, gtk.Label("Filesystem"))

        self.pack_start(notebook, expand=True)
        viewport = gtk.Viewport()
        viewport.set_shadow_type(gtk.SHADOW_IN)
        viewport.add(BlaVisualization(viewport))
        self.pack_start(viewport, expand=False)

        notebook.show_all()
        self.show()

        self.update_tree_lines()
        self.set_visibility(blacfg.getboolean("general", "browsers"))

        page_num = blacfg.getint("general", "browser.view")
        if page_num not in [0, 1]: page_num = 0
        notebook.set_current_page(page_num)
        notebook.connect("switch_page",
                lambda *x: blacfg.set("general", "browser.view", x[-1]))

    def set_visibility(self, state):
        self.set_visible(state)
        blacfg.setboolean("general", "browsers", state)

    @classmethod
    def update_tree_lines(cls):
        cls.__library_browser.update_tree_lines()

    @classmethod
    def update_colors(cls):
        cls.__library_browser.update_colors()

