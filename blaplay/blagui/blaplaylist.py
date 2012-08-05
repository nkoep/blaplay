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
from random import randint
import urllib
import re

import gobject
import gtk
import cairo
import pango
import pangocairo

import blaplay
from blaplay import (blaconst, blacfg, blautils, blaplayer, bladb, blafm,
        blagui)
player = blaplayer.player
library = bladb.library
from blatagedit import BlaTagedit
from blastatusbar import BlaStatusbar
from blaplay.blagui import blaguiutils
from blaplay.formats._identifiers import *

(COLUMN_QUEUE_POSITION, COLUMN_PLAYING, COLUMN_TRACK, COLUMN_ARTIST,
 COLUMN_TITLE, COLUMN_ALBUM, COLUMN_DURATION, COLUMN_ALBUM_ARTIST, COLUMN_YEAR,
 COLUMN_GENRE, COLUMN_FORMAT, COLUMN_BITRATE, COLUMN_FILENAME,
 COLUMN_EXTENSION, COLUMN_DIRECTORY, COLUMN_PATH, COLUMN_FILESIZE) = xrange(17)

COLUMN_TITLES = [
    "#", "Playing", "Track", "Artist", "Title", "Album", "Duration",
    "Album artist", "Year", "Genre", "Format", "Bitrate", "Filename",
    "Extension", "Directory", "Path", "Filesize"
]

COLUMNS_DEFAULT_PLAYLIST = (COLUMN_PLAYING, COLUMN_TRACK, COLUMN_ARTIST,
        COLUMN_TITLE, COLUMN_ALBUM, COLUMN_DURATION)
COLUMNS_DEFAULT_QUEUE = (COLUMN_QUEUE_POSITION, COLUMN_ARTIST, COLUMN_TITLE,
        COLUMN_ALBUM)

MODE_NORMAL, MODE_SORTED, MODE_FILTERED = 1 << 0, 1 << 1, 1 << 2


def force_view():
    from blaview import BlaView
    BlaView.update_view(blaconst.VIEW_PLAYLISTS)

def update_columns(treeview, view_id):
    treeview.disconnect_changed_signal()

    if view_id == blaconst.VIEW_PLAYLISTS:
        default = COLUMNS_DEFAULT_PLAYLIST
        view = "playlist"
    elif view_id == blaconst.VIEW_QUEUE:
        default = COLUMNS_DEFAULT_QUEUE
        view = "queue"

    map(treeview.remove_column, treeview.get_columns())
    columns = blacfg.getlistint("general", "columns.%s" % view)

    if columns is None:
        columns = default
        blacfg.set(
                "general", "columns.%s" % view, ", ".join(map(str, columns)))

    xpad = gtk.CellRendererText().get_property("xpad")
    for column_id in columns:
        column = BlaColumn(column_id)
        title = COLUMN_TITLES[column_id]
        label = gtk.Label(title)
        width = label.create_pango_layout(title).get_pixel_size()[0]
        column.set_widget(label)

        if column_id not in [COLUMN_QUEUE_POSITION, COLUMN_PLAYING,
                COLUMN_TRACK, COLUMN_DURATION]:
            column.set_expand(True)
            column.set_resizable(True)
            column.set_fixed_width(1)
        else: column.set_min_width(width + 12 + xpad)

        widget = column.get_widget()
        widget.show()
        treeview.append_column(column)
        widget.get_ancestor(gtk.Button).connect(
                "button_press_event", header_popup, view_id)
        column.connect("clicked",
                lambda c=column, i=column_id: treeview.sort_column(c, i))

    treeview.connect_changed_signal()

def columns_changed(treeview, view_id):
    if view_id == blaconst.VIEW_PLAYLISTS: view = "playlist"
    elif view_id == blaconst.VIEW_QUEUE: view = "queue"

    columns = [column.id for column in treeview.get_columns()]
    blacfg.set("general", "columns.%s" % view, ", ".join(map(str, columns)))

def popup(treeview, event, view_id, catcher):
    if view_id == blaconst.VIEW_PLAYLISTS: element = BlaPlaylist
    elif view_id == blaconst.VIEW_QUEUE: element = BlaQueue

    path = None
    try:
        path = treeview.get_path_at_pos(
                *map(int, [event.x, event.y]))[0]
    except TypeError:
        menu = gtk.Menu()
        m = gtk.MenuItem("Paste")
        mod, key = gtk.accelerator_parse("<Ctrl>V")
        m.add_accelerator(
                "activate", blagui.accelgroup, mod, key, gtk.ACCEL_VISIBLE)
        m.connect("activate", element.paste)
        m.set_sensitive(bool(element.clipboard))
        menu.append(m)

        if view_id == blaconst.VIEW_QUEUE:
            m = gtk.MenuItem("Clear queue")
            m.connect("activate", lambda *x: BlaQueue.clear())
            menu.append(m)

        menu.show_all()
        menu.popup(None, None, None, event.button, event.time)
        return

    paths = treeview.get_selection().get_selected_rows()[-1]
    model = treeview.get_model()
    try: uri = BlaPlaylist.uris[model[path][0]]
    except KeyError: uri = model[path][0]

    menu = gtk.Menu()

    m = gtk.MenuItem("Play")
    m.connect("activate", lambda *x: catcher.play_track(treeview, path))
    menu.append(m)

    menu.append(gtk.SeparatorMenuItem())

    items = [
        ("Cut", element.cut, "<Ctrl>X", True),
        ("Copy",  element.copy, "<Ctrl>C", True),
        ("Paste", element.paste, "<Ctrl>V", bool(element.clipboard)),
        ("Remove", element.remove, None, True)
    ]
    for label, callback, accelerator, visibility in items:
        m = gtk.MenuItem(label)
        if accelerator:
            mod, key = gtk.accelerator_parse(accelerator)
            m.add_accelerator(
                    "activate", blagui.accelgroup, mod, key, gtk.ACCEL_VISIBLE)
        m.connect("activate", callback)
        m.set_sensitive(visibility)
        menu.append(m)

    menu.append(gtk.SeparatorMenuItem())

    submenu = gtk.Menu()
    items = [
        ("All", blaconst.SELECT_ALL),
        ("Complement", blaconst.SELECT_COMPLEMENT)]
    if view_id == blaconst.VIEW_PLAYLISTS:
        items.extend([
            ("By artist(s)", blaconst.SELECT_BY_ARTISTS),
            ("By album(s)", blaconst.SELECT_BY_ALBUMS),
            ("By album artist(s)", blaconst.SELECT_BY_ALBUM_ARTISTS),
            ("By genre(s)", blaconst.SELECT_BY_GENRES)
        ])
    for label, type_ in items:
        m = gtk.MenuItem(label)
        m.connect("activate",
                lambda x, t=type_: element.select(t))
        submenu.append(m)

    m = gtk.MenuItem("Select")
    m.set_submenu(submenu)
    menu.append(m)

    if view_id == blaconst.VIEW_PLAYLISTS:
        submenu = gtk.Menu()
        items = [
            ("Selection", blaconst.PLAYLIST_FROM_SELECTION),
            ("Selected artist(s)", blaconst.PLAYLIST_FROM_ARTISTS),
            ("Selected album(s)", blaconst.PLAYLIST_FROM_ALBUMS),
            ("Selected album artist(s)", blaconst.PLAYLIST_FROM_ALBUM_ARTISTS),
            ("Selected genre(s)", blaconst.PLAYLIST_FROM_GENRE)
        ]
        for label, type_ in items:
            m = gtk.MenuItem(label)
            m.connect("activate",
                    lambda x, t=type_: BlaPlaylist.new_playlist(t))
            submenu.append(m)

        m = gtk.MenuItem("New playlist from")
        m.set_submenu(submenu)
        menu.append(m)

        items = [
            ("Add to queue", "Q", lambda *x: catcher.send_to_queue(treeview)),
            ("Remove from queue", "R",
                    lambda *x: catcher.remove_from_queue(treeview)),
        ]
        for label, accel, callback in items:
            m = gtk.MenuItem(label)
            mod, key = gtk.accelerator_parse(accel)
            m.add_accelerator(
                    "activate", blagui.accelgroup, mod, key, gtk.ACCEL_VISIBLE)
            m.connect("activate", callback)
            menu.append(m)

    menu.append(gtk.SeparatorMenuItem())

    identifier = treeview.get_model()[path][0]
    submenu = blafm.get_popup_menu(BlaPlaylist.get_track_from_id(identifier))
    if submenu:
        m = gtk.MenuItem("last.fm")
        m.set_submenu(submenu)
        menu.append(m)

    m = gtk.MenuItem("Open containing directory")
    m.connect("activate",
            lambda *x: blautils.open_directory(os.path.dirname(uri)))
    menu.append(m)

    menu.append(gtk.SeparatorMenuItem())

    m = gtk.MenuItem("Properties")
    mod, key = gtk.accelerator_parse("<Alt>Return")
    m.add_accelerator(
            "activate", blagui.accelgroup, mod, key, gtk.ACCEL_VISIBLE)
    m.connect("activate", element.show_properties)
    menu.append(m)

    menu.show_all()
    menu.popup(None, None, None, event.button, event.time)

def header_popup(button, event, view_id):
    if not (hasattr(event, "button") and event.button == 3): return False

    def column_selected(m, column_id, view_id, view):
        if m.get_active():
            if column_id not in columns: columns.append(column_id)
        else:
            try: columns.remove(column_id)
            except ValueError: pass

        blacfg.set("general",
                "columns.%s" % view, ", ".join(map(str, columns)))
        if view_id == blaconst.VIEW_PLAYLISTS:
            [update_columns(treeview, view_id)
                    for treeview in BlaTreeView.playlist_instances]
        else: update_columns(BlaTreeView.queue_instance, view_id)

    menu = gtk.Menu()

    if view_id == blaconst.VIEW_PLAYLISTS:
        default = COLUMNS_DEFAULT_PLAYLIST
        view = "playlist"
    elif view_id == blaconst.VIEW_QUEUE:
        default = COLUMNS_DEFAULT_QUEUE
        view = "queue"
    else: raise ValueError("Invalid view type")
    columns = blacfg.getlistint("general", "columns.%s" % view)
    if columns is None: columns = default

    for column_id, label in enumerate(COLUMN_TITLES):
        if ((column_id == COLUMN_PLAYING and view_id == blaconst.VIEW_QUEUE) or
                (column_id == COLUMN_QUEUE_POSITION and
                view_id == blaconst.VIEW_PLAYLISTS)):
            continue

        m = gtk.CheckMenuItem(label)
        if column_id in columns: m.set_active(True)
        m.connect(
                "toggled", column_selected, column_id, view_id, view)
        menu.append(m)

    menu.show_all()
    menu.popup(None, None, None, event.button, event.time)

    return True


class BlaQuery(object):
    def __init__(self, tokens):
        if not tokens:
            self.query = lambda *x: True
            return

        self.__query_identifiers = [ARTIST, TITLE, ALBUM]
        columns = blacfg.getlistint("general", "columns.playlist")
        if columns is None: columns = COLUMNS_DEFAULT_PLAYLIST
        for column_id in columns:
            self.__query_identifiers.extend(
                    self.__column_to_tag_ids(column_id))

        self.__res = [re.compile(t.decode("utf-8"), re.UNICODE | re.IGNORECASE)
                for t in tokens]
        self.query = self.__query

    def __column_to_tag_ids(self, column_id):
        if column_id == COLUMN_TRACK:
            return [DISC, TRACK]
        elif column_id == COLUMN_ALBUM_ARTIST:
            return [ALBUM_ARTIST, COMPOSER, PERFORMER]
        elif column_id == COLUMN_YEAR:
            return [YEAR]
        elif column_id == COLUMN_GENRE:
            return [GENRE]
        elif column_id == COLUMN_FORMAT:
            return [FORMAT]
        return []

    def __query(self, identifier):
        track = BlaPlaylist.get_track_from_id(identifier)
        for r in self.__res:
            search = r.search
            for identifier in self.__query_identifiers:
                if search(track[identifier]): break
            else: return False
        return True

class BlaCellRenderer(blaguiutils.BlaCellRendererBase):
    """
    Custom cellrenderer class which will render an icon if the stock-id
    property is not None and the text property otherwise. This is used for the
    `Playing' column where the queue position and status icon are both supposed
    to be centered in the cell which isn't possible with two distinct
    GtkCellRenderers.
    """

    __gproperties__ = {
        "text": (
            gobject.TYPE_STRING,
            "text",
            "text to display",
            "",
            gobject.PARAM_READWRITE
        ),
        "stock-id": (
            gobject.TYPE_STRING,
            "text",
            "text to display",
            "",
            gobject.PARAM_READWRITE
        )
    }

    def __init__(self):
        super(BlaCellRenderer, self).__init__()

    def __get_text_width(self, widget):
        context = widget.get_pango_context()
        layout = pango.Layout(context)
        fdesc = gtk.widget_get_default_style().font_desc
        layout.set_font_description(fdesc)
        layout.set_text(self.get_property("text"))
        size = layout.get_pixel_size()
        return (layout, size)

    def on_get_size(self, widget, cell_area):
        return (0, 0, -1, -1)

    def on_render(self, window, widget, background_area, cell_area,
            expose_area, flags):
        cr = window.cairo_create()

        # check if a state icon should be rendered
        stock = self.get_property("stock-id")
        if stock:
            pixbuf = widget.render_icon(stock, gtk.ICON_SIZE_SMALL_TOOLBAR)
            size = (pixbuf.get_width(), pixbuf.get_height())
            cr.set_source_pixbuf(pixbuf,
                    expose_area.x +
                    round((expose_area.width - size[0] + 0.5) / 2),
                    expose_area.y +
                    round((expose_area.height - size[1] + 0.5) / 2)
            )
            cr.rectangle(*expose_area)
            cr.fill()
        else:
            # render active resp. inactive rows
            layout, size = self.__get_text_width(widget)
            layout.set_width((expose_area.width + expose_area.x) * pango.SCALE)
            layout.set_ellipsize(pango.ELLIPSIZE_END)

            # set font, font color and the text to render
            if blacfg.getboolean("colors", "overwrite"):
                if (flags == (gtk.CELL_RENDERER_SELECTED |
                        gtk.CELL_RENDERER_PRELIT) or
                        flags == gtk.CELL_RENDERER_SELECTED):
                    color = gtk.gdk.color_parse(self._active_text_color)
                else: color = gtk.gdk.color_parse(self._text_color)
            else:
                style = widget.get_style()
                if (flags == (gtk.CELL_RENDERER_SELECTED |
                        gtk.CELL_RENDERER_PRELIT) or
                        flags == gtk.CELL_RENDERER_SELECTED):
                    color = style.text[gtk.STATE_SELECTED]
                else: color = style.text[gtk.STATE_NORMAL]
            cr.set_source_color(color)

            pc_context = pangocairo.CairoContext(cr)
            if size[0] < expose_area.width:
                x = expose_area.x + round(
                        (expose_area.width - size[0] + 0.5) / 2)
            else: x = expose_area.x
            pc_context.move_to(x, expose_area.y +
                    round((expose_area.height - size[1] + 0.5) / 2))
            pc_context.show_layout(layout)

gobject.type_register(BlaCellRenderer)

class BlaTreeView(blaguiutils.BlaTreeViewBase):
    __gsignals__ = {
        "sort_column": blaplay.signal(2)
    }

    playlist_instances = []
    queue_instance = None

    def __init__(self, view_id=None):
        super(BlaTreeView, self).__init__(multicol=True)

        if view_id == blaconst.VIEW_PLAYLISTS:
            BlaTreeView.playlist_instances.append(self)
        else: BlaTreeView.queue_instance = self

        self.__view_id = view_id
        self.set_fixed_height_mode(True)
        self.set_rubber_banding(True)
        self.set_property("rules_hint", True)

        # in-treeview dnd
        self.enable_model_drag_source(gtk.gdk.BUTTON1_MASK,
                [("tracks/playlist", gtk.TARGET_SAME_WIDGET, 1)],
                gtk.gdk.ACTION_MOVE
        )

        self.connect("destroy", self.__destroy)
        self.connect_changed_signal()

    def __destroy(self, *args):
        try: BlaTreeView.playlist_instances.remove(self)
        except ValueError: pass

    def connect_changed_signal(self):
        if self.__view_id is not None:
            self.__columns_changed_id = self.connect(
                    "columns_changed", columns_changed, self.__view_id)

    def disconnect_changed_signal(self):
        try: self.disconnect(self.__columns_changed_id)
        except AttributeError: pass

    def sort_column(self, column, column_id):
        sort_indicator = column.get_sort_indicator()
        if not sort_indicator:
            sort_indicator = True
            sort_order = gtk.SORT_ASCENDING
        else:
            if column.get_sort_order() == gtk.SORT_ASCENDING:
                sort_order = gtk.SORT_DESCENDING
            else:
                sort_indicator = False
                sort_order = None
        self.emit("sort_column", column_id, sort_order)

class BlaEval(object):
    """
    Class which maps track tags to column ids, i.e. it defines what is
    displayed by cellrenderers given a specific column identifier.
    """

    def __init__(self, column_id):
        try: self.eval = self.__callbacks[column_id]
        except IndexError: self.eval = lambda *x: ""

    # these methods are static despite absent staticmethod decorators
    def __track_cb(track):
        try: value = "%d." % int(track[DISC].split("/")[0])
        except ValueError: value = ""
        try: value += "%02d" % int(track[TRACK].split("/")[0])
        except ValueError: pass
        return value

    def __artist_cb(track):
        return track[ARTIST]

    def __title_cb(track):
        return track[TITLE] or track.basename

    def __album_cb(track):
        return track[ALBUM]

    def __duration_cb(track):
        return track.duration

    def __album_artist_cb(track):
        return (track[ALBUM_ARTIST] or track[ARTIST] or track[PERFORMER] or
                track[COMPOSER])

    def __year_cb(track):
        return track[DATE].split("-")[0]

    def __genre_cb(track):
        return track[GENRE]

    def __format_cb(track):
        return track[FORMAT]

    def __bitrate_cb(track):
        return track.bitrate

    def __filename_cb(track):
        return os.path.basename(track.path)

    def __extension_cb(track):
        return blautils.get_extension(track.path)

    def __directory_cb(track):
        return os.path.dirname(track.path)

    def __path_cb(track):
        return track.path

    def __filesize_cb(track):
        return track.get_filesize(short=True)

    __callbacks = [
        lambda *x: "", lambda *x: "", __track_cb, __artist_cb, __title_cb,
        __album_cb, __duration_cb, __album_artist_cb, __year_cb, __genre_cb,
        __format_cb, __bitrate_cb, __filename_cb, __extension_cb,
        __directory_cb, __path_cb, __filesize_cb
    ]

class BlaColumn(gtk.TreeViewColumn):
    def __init__(self, column_id):
        super(BlaColumn, self).__init__()
        self.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)

        self.id = column_id
        self.set_reorderable(True)

        alignment = (0.5 if column_id == COLUMN_PLAYING else 1.0
                if column_id == COLUMN_DURATION else 0.0)

        self.__cb = BlaEval(column_id).eval

        if column_id == COLUMN_PLAYING:
            r = BlaCellRenderer()
            self.pack_start(r)
            self.add_attribute(r, "stock-id", 1)
        else:
            r = gtk.CellRendererText()
            self.pack_start(r)
            r.set_property("ellipsize", pango.ELLIPSIZE_END)
        r.set_property("xalign", alignment)

        if column_id != COLUMN_PLAYING: self.set_clickable(True)
        self.set_resizable(True)
        self.set_cell_data_func(r, self.__cell_data_func, column_id)
        self.set_alignment(alignment)

    def __cell_data_func(self, column, renderer, model, iterator, column_id):
        track = BlaPlaylist.get_track_from_id(model[iterator][0])

        if column_id == COLUMN_QUEUE_POSITION:
            text = "%02d" % (model.get_path(iterator)[0] + 1)
        elif column_id == COLUMN_PLAYING:
            l = model[iterator][2]
            text = "(%s)" % (", ".join(map(str, l))) if l else ""
        else: text = self.__cb(track)

        renderer.set_property("text", text)

class BlaQueue(blaguiutils.BlaScrolledWindow):
    """ Class that represents a play queue. """

    __gsignals__ = {
        "count_changed": blaplay.signal(2)
    }

    __layout = [
        gobject.TYPE_PYOBJECT, # playlist id or uri if track comes from browser
        gobject.TYPE_PYOBJECT  # playlist or None if track comes from browser
    ]
    __queue = gtk.ListStore(*__layout)
    __treeview = BlaTreeView(view_id=blaconst.VIEW_QUEUE)
    __instance = None
    __added_rows = []

    clipboard = []

    def __init__(self):
        super(BlaQueue, self).__init__()
        type(self).__instance = self

        self.__treeview.set_model(self.__queue)
        self.__treeview.set_enable_search(False)
        self.__treeview.set_property("rules_hint", True)

        self.set_shadow_type(gtk.SHADOW_IN)
        self.add(self.__treeview)

        self.__treeview.enable_model_drag_dest(
                [("queue", 0, 3)], gtk.gdk.ACTION_MOVE)
        self.__treeview.enable_model_drag_source(gtk.gdk.BUTTON1_MASK,
                [("queue", gtk.TARGET_SAME_WIDGET, 3)], gtk.gdk.ACTION_MOVE)

        self.__treeview.connect("popup", popup, blaconst.VIEW_QUEUE, self)
        self.__treeview.connect("row_activated", self.play_track)
        self.__treeview.connect("key_press_event", self.__key_press_event)
        self.__treeview.connect("drag_data_get", self.__drag_data_get)
        self.__treeview.connect("drag_data_received", self.__drag_data_recv)

        update_columns(self.__treeview, view_id=blaconst.VIEW_QUEUE)

        self.show_all()

    def __key_press_event(self, treeview, event):
        if blagui.is_accel(event, "Delete"): self.remove()
        elif blagui.is_accel(event, "<Alt>Return"): self.show_properties()
        return False

    def __drag_data_get(self, treeview, drag_context, selection_data, info,
            time):
        self.__paths = treeview.get_selection().get_selected_rows()[-1]
        selection_data.set("queue", 8, "")

    def __drag_data_recv(self, treeview, drag_context, x, y, selection_data,
            info, time):
        drop_info = treeview.get_dest_row_at_pos(x, y)

        if drop_info:
            path, pos = drop_info
            iterator = type(self).__queue.get_iter(path)

            if (pos == gtk.TREE_VIEW_DROP_BEFORE or
                        pos == gtk.TREE_VIEW_DROP_INTO_OR_BEFORE):
                move_before = type(self).__queue.move_before
                f = lambda it: move_before(it, iterator)
            else:
                move_after = type(self).__queue.move_after
                f = lambda it: move_after(it, iterator)
                self.__paths.reverse()
        else:
            iterator = None
            move_before = type(self).__queue.move_before
            f = lambda it: move_before(it, iterator)

        get_iter = type(self).__queue.get_iter
        iterators = map(get_iter, self.__paths)
        map(f, iterators)
        self.__paths = []
        self.update_queue_positions()

    @classmethod
    def __get_items(cls, remove=True):
        treeview = cls.__instance.__treeview
        selections = treeview.get_selection().get_selected_rows()[-1]
        if selections:
            f = cls.__queue.get_iter
            iterators = map(f, selections)
            items = [map(None, cls.__queue[iterator])
                    for iterator in iterators]
            if remove: cls.update_queue_positions(iterators=iterators)
            return items
        return []

    @classmethod
    def __add_items(cls, items, path=None, select_rows=False):
        ns = {}.fromkeys(["iterator"])
        ib = cls.__queue.insert_before
        iaa = cls.__queue.append
        def insert_before(ns, item): ns["iterator"] = ib(ns["iterator"], item)
        def append(ns, item): iaa(item)

        treeview = cls.__instance.__treeview
        paths = treeview.get_selection().get_selected_rows()[-1]

        try:
            if not paths or path == "append": raise TypeError
            if not path:
                path, column = cls.__instance.__treeview.get_cursor()
        except TypeError: insert_func = append
        else:
            ns["iterator"] = cls.__queue.get_iter(path)
            insert_func = insert_before
            items.reverse()

        [insert_func(ns, item) for item in items]
        cls.update_queue_positions()

    def play_track(self, treeview, path, column=None):
        BlaPlaylist.play_from_playlist(*map(None, type(self).__queue[path]))
        if blacfg.getboolean("general", "queue.remove.when.activated"):
            self.update_queue_positions([self.__queue.get_iter(path)])

    @classmethod
    def select(cls, type_):
        treeview = cls.__instance.__treeview
        selection = treeview.get_selection()

        if type_ == blaconst.SELECT_ALL: selection.select_all()
        elif type_ == blaconst.SELECT_COMPLEMENT:
            selected_paths = set(selection.get_selected_rows()[-1])
            paths = set([(p,) for p in xrange(
                    treeview.get_model().iter_n_children(None))])
            paths.difference_update(selected_paths)
            selection.unselect_all()
            select_path = selection.select_path
            map(select_path, paths)

    @classmethod
    def show_properties(cls, *args):
        treeview = cls.__instance.__treeview
        paths = treeview.get_selection().get_selected_rows()[-1]
        uris = []
        for path in paths:
            x = cls.__queue[path][0]
            try: uri = BlaPlaylist.uris[x]
            except KeyError: uri = x
            uris.append(uri)
        if uris: BlaTagedit(uris)

    @classmethod
    def update_queue_positions(cls, iterators=[]):
        def reset(model, path, iterator, args):
            iterators, playlists, positions = args
            track, playlist = map(None, cls.__queue[iterator])

            if playlist:
                identifier = id(playlist)
                playlists.add(playlist)
                try: positions[identifier][track] = []
                except KeyError: positions[identifier] = {track: []}

        def determine_positions(model, path, iterator, args):
            playlists, positions = args
            track, playlist = map(None, cls.__queue[iterator])

            if playlist:
                pos = cls.__queue.get_path(iterator)[0]+1
                identifier = id(playlist)
                playlists.add(playlist)
                try: d = positions[identifier]
                except KeyError:
                    positions[identifier] = {}
                    d = positions[identifier]

                try: d[track].append(pos)
                except KeyError: d[track] = [pos]

        def update_models(playlists, positions):
            for playlist in playlists:
                d = positions[id(playlist)]
                items = zip(d.keys(), d.values())

                # if a playlist is removed from the notebook the garbage
                # collector might not pick it up if the queue still holds a
                # reference to it. however, since the model of the playlist is
                # already destroyed the following call raises a TypeError we
                # need to catch
                try: playlist.update_queue_positions(items)
                except TypeError: pass

        # reset old positions and remove items if necessary
        playlists, positions = set(), {}
        cls.__queue.foreach(reset, (iterators, playlists, positions))
        update_models(playlists, positions)
        remove = cls.__queue.remove
        map(remove, iterators)

        # determine new positions of the remaining entries
        playlists, positions = set(), {}
        cls.__queue.foreach(determine_positions, (playlists, positions))
        update_models(playlists, positions)

        cls.__instance.emit(
                "count_changed", blaconst.VIEW_QUEUE, cls.get_queue_count())

    @classmethod
    def get_queued_tracks(cls):
        queue = []
        for row in cls.__queue:
            track, playlist = map(None, row)
            if playlist:
                try: idx = BlaPlaylist.pages.index(playlist)
                except ValueError:
                    track = BlaPlaylist.uris[track]
                    idx = -1
                else: track = playlist.get_path_from_id(track)
            else: idx = -1
            queue.append((track, idx))
        return queue

    @classmethod
    def restore_queue(cls, queue):
        items = []
        append = cls.__queue.append
        for track, idx in queue:
            if idx == -1: playlist = None
            else:
                playlist = BlaPlaylist.pages[idx]
                track = playlist.get_id_from_path(track)
            items.append([track, playlist])
        cls.__add_items(items=items, path="append")

    @classmethod
    def queue_tracks(cls, tracks, playlist):
        count = blaconst.QUEUE_MAX_ITEMS - cls.__queue.iter_n_children(None)
        items = [[track, playlist] for track in tracks[:count]]
        cls.__add_items(items=items, path="append")

    @classmethod
    def remove_tracks(cls, tracks, playlist):
        # this is invoked by playlists who want to remove tracks from the queue
        iterators = []
        for row in cls.__queue:
            if row[0] in tracks and row[1] == playlist:
                iterators.append(row.iter)
        cls.update_queue_positions(iterators)

    @classmethod
    def cut(cls, *args):
        cls.clipboard = cls.__get_items(remove=True)
        blagui.update_menu(blaconst.VIEW_QUEUE)

    @classmethod
    def copy(cls, *args):
        cls.clipboard = cls.__get_items(remove=False)
        blagui.update_menu(blaconst.VIEW_QUEUE)

    @classmethod
    def paste(cls, *args, **kwargs):
        cls.__add_items(items=cls.clipboard, select_rows=True)

    @classmethod
    def remove(cls, *args):
        cls.__get_items(remove=True)

    @classmethod
    def clear(cls):
        cls.update_queue_positions([row.iter for row in cls.__queue])

    @classmethod
    def get_track(cls):
        iterator = cls.__queue.get_iter_first()
        if iterator:
            track, playlist = map(None, cls.__queue[iterator])
            cls.update_queue_positions([iterator])
            return track, playlist
        return None

    @classmethod
    def get_queue_count(cls):
        return cls.__queue.iter_n_children(None)

class BlaPlaylist(gtk.Notebook):
    __gsignals__ = {
        "play_track": blaplay.signal(1),
        "count_changed": blaplay.signal(2),
        "update_playlist_info": blaplay.signal(3)
    }

    pages = []          # list of playlists (needed for the queue)
    __instance = None   # instance of BlaPlaylist needed for classmethods
    active = None       # reference to the currently active playlist
    count = 0           # global counter used to define unique track ids
    uris = {}           # mapping between track ids and uris
    clipboard = []      # list of ids after a cut/copy operation

    class History(object):
        """
        History class which stores TreeRowReferences to previously played
        tracks of a playlist.
        """

        def __init__(self, playlist):
            super(BlaPlaylist.History, self).__init__()
            self.__playlist = playlist
            self.__model = gtk.ListStore(gobject.TYPE_INT)
            self.__iterator = None

        def add(self, identifier, choice):
            if choice == blaconst.TRACK_NEXT:
                insert_func = self.__model.insert_after
            else: insert_func = self.__model.insert_before
            self.__iterator = insert_func(self.__iterator, [identifier])

        def get(self, choice):
            if choice == blaconst.TRACK_NEXT: f = self.__model.iter_next
            elif choice == blaconst.TRACK_PREVIOUS:
                f = self.__iter_previous

            # iterate through the model until a valid reference to an entry
            # in the playlist is found
            while True:
                try: iterator = f(self.__iterator)
                except TypeError: iterator = None

                if (iterator and
                        not self.__playlist.get_path_from_id(
                        self.__model[iterator][0], unfiltered=True)):
                    self.__model.remove(iterator)
                    continue
                break

            if not iterator: identifier = None
            else:
                identifier = self.__model[iterator][0]
                self.__iterator = iterator

            return identifier

        def clear(self):
            self.__model.clear()
            self.__iterator = None

        def __iter_previous(self, iterator):
            path = self.__model.get_path(iterator)
            if path[0] > 0: return self.__model.get_iter((path[0]-1,))
            return None

    class Playlist(gtk.VBox):
        __layout = [
            gobject.TYPE_INT,       # unique identifier of playlist tracks
            gobject.TYPE_STRING,    # stock icon
            gobject.TYPE_PYOBJECT   # queue position(s)
        ]

        __current = None
        __sort_parameters = None
        __fid = -1
        __filter_parameters = []

        def __init__(self):
            super(BlaPlaylist.Playlist, self).__init__()

            self.__history = BlaPlaylist.History(self)
            self.__mode = MODE_NORMAL

            self.__entry = blaguiutils.BlaEntry()
            self.__entry.set_icon_from_stock(
                    gtk.ENTRY_ICON_SECONDARY, gtk.STOCK_CANCEL)
            self.__entry.connect(
                    "icon_release", lambda *x: self.disable_search())
            def key_press_event(entry, event):
                if blagui.is_accel(event, "Escape"): self.disable_search()
                return False
            self.__entry.connect("key_press_event", key_press_event)

            button = gtk.Button()
            button.add(gtk.image_new_from_stock(
                    gtk.STOCK_FIND, gtk.ICON_SIZE_BUTTON))
            button.connect("clicked", self.__filter)

            self.__hbox = gtk.HBox()
            self.__hbox.pack_start(self.__entry, expand=True)
            self.__hbox.pack_start(button, expand=False)
            self.__hbox.show_all()
            self.__hbox.set_visible(False)

            self.__treeview = BlaTreeView(view_id=blaconst.VIEW_PLAYLISTS)
            self.__treeview.connect_object(
                    "sort_column", BlaPlaylist.Playlist.sort, self)
            self.__treeview.connect("row_activated", self.play_track)
            self.__treeview.connect(
                    "popup", popup, blaconst.VIEW_PLAYLISTS, self)
            self.__treeview.connect("key_press_event", self.__key_press_event)
            self.__treeview.connect("drag_data_get", self.__drag_data_get)

            # receive drag and drop
            self.__treeview.enable_model_drag_dest([
                    ("tracks/library", gtk.TARGET_SAME_APP, 0),
                    ("tracks/filesystem", gtk.TARGET_SAME_APP, 1),
                    ("tracks/playlist", gtk.TARGET_SAME_WIDGET, 2),
                    ("text/uri-list", 0, 3)],
                    gtk.gdk.ACTION_COPY
            )
            self.__treeview.connect(
                    "drag_data_received", self.__drag_data_recv)

            sw = blaguiutils.BlaScrolledWindow()
            sw.add(self.__treeview)

            self.clear()

            self.pack_start(self.__hbox, expand=False)
            self.pack_start(sw, expand=True)
            sw.show_all()

            update_columns(self.__treeview, view_id=blaconst.VIEW_PLAYLISTS)
            self.show()
            self.__entry.connect("activate", self.__filter)

        def clear(self, init=False):
            self.__treeview.freeze_notify()
            self.__treeview.freeze_child_notify()
            model = self.__treeview.get_model()
            self.disable_search()

            self.__length = 0
            self.__history.clear()
            self.__current = None
            self.__old_id = -1
            self.__all_tracks = []  # unfiltered, unsorted tracks
            self.__all_sorted = []  # unfiltered, sorted tracks
            self.__tracks = []      # visible tracks when unsorted
            self.__sorted = []      # visible tracks when sorted
            self.__sort_parameters = None
            self.__mode = MODE_NORMAL

            try: model.clear()
            except AttributeError:
                self.__treeview.set_model(gtk.ListStore(*self.__layout))
            else: self.__treeview.set_model(model)
            self.__treeview.thaw_child_notify()
            self.__treeview.thaw_notify()

            self.update_playlist_info()

        def get_path_from_id(self, identifier, unfiltered=False):
            if self.__mode & MODE_FILTERED and not unfiltered:
                if self.__mode & MODE_SORTED: ids = self.__sorted
                else: ids = self.__tracks
            else:
                if self.__mode & MODE_SORTED: ids = self.__all_sorted
                else: ids = self.__all_tracks

            try: return (ids.index(identifier),)
            except ValueError: return None

        def get_id_from_path(self, path):
            if self.__mode & MODE_FILTERED:
                if self.__mode & MODE_SORTED: ids = self.__sorted
                else: ids = self.__tracks
            else:
                if self.__mode & MODE_SORTED: ids = self.__all_sorted
                else: ids = self.__all_tracks

            try: return ids[path[0]]
            except (TypeError, IndexError): return None

        def select(self, type_):
            selection = self.__treeview.get_selection()

            if type_ == blaconst.SELECT_ALL:
                selection.select_all()
                return
            elif type_ == blaconst.SELECT_COMPLEMENT:
                selected_paths = set(selection.get_selected_rows()[-1])
                paths = set([(p,) for p in xrange(
                        self.__treeview.get_model().iter_n_children(None))])
                paths.difference_update(selected_paths)
                selection.unselect_all()
                select_path = selection.select_path
                map(select_path, paths)
                return
            elif type_ == blaconst.SELECT_BY_ARTISTS: column_id = COLUMN_ARTIST
            elif type_ == blaconst.SELECT_BY_ALBUMS: column_id = COLUMN_ALBUM
            elif type_ == blaconst.SELECT_BY_ALBUM_ARTISTS:
                column_id = COLUMN_ALBUM_ARTIST
            else: column_id = COLUMN_GENRE

            paths = selection.get_selected_rows()[-1]
            ids = map(self.get_id_from_path, paths)
            eval_ = BlaEval(column_id).eval
            tracks = map(BlaPlaylist.get_track_from_id, ids)
            values = set()
            [values.add(eval_(track)) for track in tracks]

            if self.__mode & MODE_FILTERED:
                if self.__mode & MODE_SORTED: ids = self.__sorted
                else: ids = self.__tracks
            else:
                if self.__mode & MODE_SORTED: ids = self.__all_sorted
                else: ids = self.__all_tracks

            tracks = map(BlaPlaylist.get_track_from_id, ids)
            ids = [identifier for identifier, track in zip(ids, tracks)
                    if eval_(track) in values]

            paths = map(self.get_path_from_id, ids)
            selection.unselect_all()
            select_path = selection.select_path
            map(select_path, paths)

        def new_playlist(self, type_):
            paths = self.__treeview.get_selection().get_selected_rows()[-1]
            ids = map(self.get_id_from_path, paths)

            if type_ != blaconst.PLAYLIST_FROM_SELECTION:
                if type_ == blaconst.PLAYLIST_FROM_ARTISTS:
                    column_id = COLUMN_ARTIST
                elif type_ == blaconst.PLAYLIST_FROM_ALBUMS:
                    column_id = COLUMN_ALBUM
                elif type_ == blaconst.PLAYLIST_FROM_ALBUM_ARTISTS:
                    column_id = COLUMN_ALBUM_ARTIST
                else:
                    column_id = COLUMN_GENRE

                eval_ = BlaEval(column_id).eval
                tracks = map(BlaPlaylist.get_track_from_id, ids)
                values = set()
                [values.add(eval_(track)) for track in tracks]

                if self.__mode & MODE_FILTERED:
                    if self.__mode & MODE_SORTED: ids = self.__sorted
                    else: ids = self.__tracks
                else:
                    if self.__mode & MODE_SORTED: ids = self.__all_sorted
                    else: ids = self.__all_tracks

                tracks = map(BlaPlaylist.get_track_from_id, ids)
                ids = [identifier for identifier, track in zip(ids, tracks)
                        if eval_(track) in values]

            uris = [BlaPlaylist.uris[identifier] for identifier in ids]
            playlist = BlaPlaylist.add_playlist(focus=True)
            playlist.add_tracks(uris=uris)

        def add_tracks(self, uris, drop_info=None, flush=False, current=None,
                select_rows=False, restore=False):
            if flush: self.clear()
            if not uris: return

            added_rows = []
            iterator = None

            # we need a mutable type to update the iterator when calling
            # `insert_func()' through `map()'. we use a dict for this
            ns = {}.fromkeys(["iterator"])
            model = self.__treeview.get_model()
            ib = model.insert_before
            ia = model.insert_after
            iaa = model.append

            def insert_before(ns, item):
                ns["iterator"] = ib(ns["iterator"], item)
            def insert_after(ns, item):
                ns["iterator"] = ia(ns["iterator"], item)
            def append(ns, item):
                iaa(item)

            if isinstance(uris, tuple): ids, uris = uris
            else:
                ids = range(BlaPlaylist.count, BlaPlaylist.count + len(uris))
                BlaPlaylist.count += len(uris)

            reverse = False

            if drop_info == "at_cursor":
                paths = self.__treeview.get_selection().get_selected_rows()[-1]
                try:
                    if not paths: raise TypeError
                    path, colum = self.__treeview.get_cursor()
                except TypeError: path = None
                if path is None: drop_info = None
                else: drop_info = (path, gtk.TREE_VIEW_DROP_BEFORE)

            if drop_info:
                path, pos = drop_info
                ns["iterator"] = model.get_iter(path)

                if (pos == gtk.TREE_VIEW_DROP_BEFORE or
                        pos == gtk.TREE_VIEW_DROP_INTO_OR_BEFORE):
                    insert_func = insert_before
                    reverse = True
                else:
                    path = (path[0]+1,)
                    insert_func = insert_after
            else:
                path = (model.iter_n_children(None),)
                insert_func = append

            # update mapping dictionary between ids and uris (ids are unique,
            # so this call really just extends the dict)
            BlaPlaylist.uris.update(dict(zip(ids, uris)))

            self.insert(ids, path, restore=bool(restore))
            try: query, sort_parameters = restore
            except TypeError:
                query = None
                sort_parameters = None

            self.__sort_parameters = sort_parameters
            if not (restore and (query or sort_parameters)):
                scroll_id = ids[-1]
                if reverse: ids.reverse()
                model = self.__freeze_treeview()
                [insert_func(ns, [identifier, "", []]) for identifier in ids]
                self.__treeview.set_model(model)
                self.__thaw_treeview()
            elif query: self.enable_search(query)
            elif sort_parameters: self.sort(*sort_parameters)
            else: raise NotImplementedError("This shouldn't happen")

            if current:
                # when restoring a playlist, current (which usually is a
                # playlist id) conincides with the path in the playlist
                self.__current = (self.__all_sorted[current]
                        if self.__mode & MODE_SORTED else
                        self.__all_tracks[current]
                )
                self.set_row(self.get_path_from_id(self.__current))

            if flush:
                track = self.get_track(
                        choice=blaconst.TRACK_PLAY, force_advance=True)
                BlaPlaylist.play_track(track, self)

            # select the added rows if requested
            if select_rows:
                self.__treeview.freeze_child_notify()
                selection = self.__treeview.get_selection()
                s = selection.unselect_path
                map(s, selection.get_selected_rows()[-1])
                s = selection.select_path
                map(s, xrange(path[0], path[0] + len(uris)))
                self.__treeview.thaw_child_notify()

                path = self.get_path_from_id(scroll_id)
                self.set_row(path=path, row_align=1.0, keep_selection=True)

            self.update_playlist_info()

        def get_tracks(self, remove=False, paths=None):
            ids = []
            if paths is None:
                paths = self.__treeview.get_selection().get_selected_rows()[-1]

            if paths:
                model = self.__treeview.get_model()

                if (self.__current is not None and remove and
                        self.get_path_from_id(self.__current) in paths):
                    self.__old_id = self.__current
                    self.__current = paths[0]

                ids = map(self.get_id_from_path, paths)

                if remove:
                    self.__length -= sum([track[LENGTH] for track
                            in map(BlaPlaylist.get_track_from_id, ids)])

                    # remove the rows from the model
                    model = self.__freeze_treeview()
                    iterators = map(model.get_iter, paths)
                    remove = model.remove
                    map(remove, iterators)
                    self.__thaw_treeview()

                    # remove the ids
                    if self.__mode & MODE_FILTERED:
                        map(self.__tracks.remove, ids)
                        if self.__mode & MODE_SORTED:
                            map(self.__sorted.remove, ids)
                    if self.__mode & MODE_SORTED:
                        map(self.__all_sorted.remove, ids)
                    map(self.__all_tracks.remove, ids)

                    self.update_playlist_info()

            return ids

        def insert(self, inserted_ids, path, restore=False):
            if self.__old_id in inserted_ids: self.__current = self.__old_id

            # due to the way playlist contents are handled to speed up
            # filtering/sorting, dealing with track insertion is a rather
            # fiddly task
            if self.__mode & MODE_FILTERED or self.__mode & MODE_SORTED:
                original_path = path

                if self.__mode & MODE_FILTERED:
                    ids = (self.__sorted if self.__mode & MODE_SORTED else
                            self.__tracks)
                else: ids = self.__all_sorted

                offset = 1
                try: identifier = ids[0]
                except IndexError:
                    identifier = self.__all_tracks[-1]
                else:
                    if path == (0,):
                        identifier = ids[0]
                        offset = 0
                    else:
                        try: identifier = ids[path[0]-1]
                        except IndexError: identifier = ids[-1]

                path = (self.__all_tracks.index(identifier)+offset,)

                # insertion at this point needs to happen in-place so we don't
                # lose the reference
                [ids.insert(original_path[0]+idx, value)
                        for idx, value in enumerate(inserted_ids)]

            self.__all_tracks = (self.__all_tracks[0:path[0]] + inserted_ids +
                    self.__all_tracks[path[0]:])
            tracks = map(BlaPlaylist.get_track_from_id, inserted_ids)
            self.__length += sum([track[LENGTH] for track in tracks])

        # FIXME: these two are slow
        def remove_duplicates(self):
            def remove_duplicates():
                def f(identifier):
                    try: return (ids.index(identifier),)
                    except ValueError: return None

                ids = (self.__all_sorted if self.__mode & MODE_SORTED else
                        self.__all_tracks)
                unique_ids = set()
                uia = unique_ids.add
                unique_uris = set()
                uua = unique_uris.add
                uris = BlaPlaylist.uris

                # don't remove the current track
                if self.__current is not None:
                    uia(self.__current)
                    uua(uris[self.__current])

                # check the remaining ids
                for identifier in ids:
                    uri = uris[identifier]
                    if uri not in unique_uris:
                        uia(identifier)
                        uua(uri)

                # SLOW
                # remove duplicates
                    self.get_tracks(remove=True, paths=map(f,
                            set(ids).difference(unique_ids)))

                self.__treeview.set_sensitive(True)
                return False

            self.__treeview.set_sensitive(False)
            gobject.idle_add(remove_duplicates)

        def remove_invalid_tracks(self):
            def remove_invalid_tracks():
                uris = [BlaPlaylist.uris[identifier]
                        for identifier in self.__all_tracks]
                exists = os.path.exists
                invalid = [identifier for uri, identifier
                        in zip(uris, self.__all_tracks) if not exists(uri)]
                paths = map(self.get_path_from_id, invalid)
                self.get_tracks(remove=True, paths=paths)
                self.__treeview.set_sensitive(True)
                return False

            self.__treeview.set_sensitive(False)
            gobject.idle_add(remove_invalid_tracks)

        def enable_search(self, text=""):
            if text:
                self.__entry.set_text(text)
                self.__entry.activate()
            else: self.__entry.grab_focus()
            self.__cid = self.__entry.connect(
                    "changed", self.__filter_parameters_changed)
            self.__hbox.set_visible(True)

        def disable_search(self):
            self.__hbox.set_visible(False)
            try:
                if self.__entry.handler_is_connected(self.__cid):
                    self.__entry.disconnect(self.__cid)
            except AttributeError: pass
            text = self.__entry.get_text()
            self.__entry.delete_text(0, -1)
            if text: self.__entry.activate()

        def sort(self, column_id, sort_order, scroll=False):
            for column in self.__treeview.get_columns():
                if column.id == column_id: break
            else: sort_order = None

            row_align, selected_ids, scroll_identifier = \
                    self.__get_selection_and_row()
            ids = (self.__tracks if self.__mode & MODE_FILTERED else
                    self.__all_tracks)
            if sort_order is None:
                self.__mode ^= MODE_SORTED
                sort_indicator = False
            else:
                self.__mode |= MODE_SORTED
                sort_indicator = True

                if sort_order == gtk.SORT_DESCENDING: reverse = True
                elif sort_order == gtk.SORT_ASCENDING: reverse = False
                eval_ = BlaEval(column_id).eval

                self.__all_sorted = sorted(self.__all_tracks, key=lambda t:
                        eval_(BlaPlaylist.get_track_from_id(t)).lower(),
                        reverse=reverse
                )
                ids = sorted(ids, key=lambda t:
                        eval_(BlaPlaylist.get_track_from_id(t)).lower(),
                        reverse=reverse
                )
                self.__sorted = ids

            self.__treeview.freeze_notify()
            self.__treeview.freeze_child_notify()
            model = self.__treeview.get_model()
            self.__treeview.set_model(None)

            model.clear()
            append = model.append
            [append([identifier, "", []]) for identifier in ids]

            self.__treeview.set_model(model)

            if sort_order is not None:
                self.__sort_parameters = (column_id, sort_order)
            else: self.__sort_parameters = None

            column.set_sort_indicator(sort_indicator)
            if sort_indicator: column.set_sort_order(sort_order)

            self.__set_selection_and_row(row_align, selected_ids, None)
            self.update_state(player.get_state())

            self.__treeview.thaw_child_notify()
            self.__treeview.thaw_notify()

        def package_playlist(self):
            try:
                path = self.get_path_from_id(
                        self.__current, unfiltered=True)[0]
            except TypeError: path = None
            # since we sort on startup anyway, just get the __all_tracks list
            uris = [BlaPlaylist.uris[identifier]
                    for identifier in self.__all_tracks]
            playlist = [(self.__entry.get_text(), self.__sort_parameters),
                    path, uris]
            return playlist

        def get_uris(self):
            if self.__mode & MODE_FILTERED:
                if self.__mode & MODE_SORTED: ids = self.__sorted
                else: ids = self.__tracks
            else:
                if self.__mode & MODE_SORTED: ids = self.__all_sorted
                else: ids = self.__all_tracks
            return [BlaPlaylist.uris[identifier] for identifier in ids]

        def get_track(self, choice=blaconst.TRACK_PLAY, force_advance=True):
            def get_random():
                idx_max = model.iter_n_children(None)-1
                if idx_max < 0: return None
                return model[randint(0, idx_max)][0]

            order = blacfg.getint("general", "play.order")
            model = self.__treeview.get_model()

            # remove the playing icon from the old row
            try: model[self.get_path_from_id(self.__current)][1] = None
            except TypeError: pass

            # if there are no tracks in the playlist, return
            if not model.get_iter_first(): return None

            identifier = None

            # this happens when the user presses play and we should play the
            # last active track
            if (choice == blaconst.TRACK_PLAY and
                    isinstance(self.__current, int)):
                identifier = self.__current

            # play, but we didn't play a track from this playlist yet
            elif choice == blaconst.TRACK_PLAY:
                if order == blaconst.ORDER_SHUFFLE:
                    identifier = get_random()
                    self.__history.add(identifier, choice)
                else: identifier = model[0][0]

            # are we in repeat and did not ask to advance to the next track
            elif (order == blaconst.ORDER_REPEAT and not force_advance and
                    isinstance(self.__current, int)):
                identifier = self.__current

            elif choice == blaconst.TRACK_RANDOM:
                identifier = get_random()
                self.__history.add(identifier, blaconst.TRACK_NEXT)

            # this is either TRACK_NEXT or TRACK_PREVIOUS with ORDER_SHUFFLE
            elif order == blaconst.ORDER_SHUFFLE:
                identifier = self.__history.get(choice)
                if identifier is None:
                    identifier = get_random()
                    self.__history.add(identifier, choice)

            # this is either TRACK_NEXT or TRACK_PREVIOUS with ORDER_NORMAL
            else:
                if (not isinstance(self.__current, int) and
                        self.__current is not None):
                    try: model[self.__current]
                    except IndexError:
                        count = model.iter_n_children(None)
                        if count: path = (count-1,)
                        else: path = None
                    else: path = self.__current
                else:
                    path = self.get_path_from_id(self.__current)
                    if path is None: path = (0,)
                    else:
                        if choice == blaconst.TRACK_NEXT: path = (path[0]+1,)
                        else: path = (path[0]-1,) if path[0] > 0 else None

                identifier = self.get_id_from_path(path)

            track = None
            if identifier is not None:
                self.__current = identifier
                path = self.get_path_from_id(self.__current)
                if blacfg.getboolean("general", "cursor.follows.playback"):
                    self.set_row(path)
                track = BlaPlaylist.uris[self.__current]
                try: model[path][1] = gtk.STOCK_MEDIA_PLAY
                except TypeError: pass

            return track

        def update_playlist_info(self):
            try: count = self.__treeview.get_model().iter_n_children(None)
            except TypeError: count = 0

            # TODO: keep track of size of a playlist the same way we keep
            #       track of the length
            if self.__mode & MODE_FILTERED:
                tracks = map(BlaPlaylist.get_track_from_id, self.__tracks)
                size = sum([track[FILESIZE] for track in tracks])
                length = sum([track[LENGTH] for track in tracks])
            else:
                tracks = map(BlaPlaylist.get_track_from_id, self.__all_tracks)
                size = sum([track[FILESIZE] for track in tracks])
                length = self.__length

            BlaPlaylist.update_playlist_info(count, size, length)

        def update_state(self, state):
            if self.__current is None: return

            model = self.__treeview.get_model()
            path = self.get_path_from_id(self.__current)
            if None in [model, path]: return

            # only update the icon in the playlist if it currently has one.
            # this ensures the icon is only updated on tracks in a playlist,
            # but not on any from the library
            if model[path][1] != None and BlaPlaylist.active == self:
                stock = None
                if state == blaconst.STATE_PLAYING:
                    stock = gtk.STOCK_MEDIA_PLAY
                elif state == blaconst.STATE_PAUSED:
                    stock = gtk.STOCK_MEDIA_PAUSE
                model[path][1] = stock

            BlaQueue.update_queue_positions()

        def update_queue_positions(self, items):
            model = self.__treeview.get_model()
            for identifier, positions in items:
                try: model[self.get_path_from_id(identifier)][2] = positions
                except ValueError: pass

        def update_contents(self):
            try: low, high = self.__treeview.get_visible_range()
            except TypeError: pass
            else:
                model = self.__treeview.get_model()
                get_iter = model.get_iter
                row_changed = model.row_changed
                [row_changed(path, get_iter(path)) for path
                        in xrange(low[0], high[0]+1)]

        def play_track(self, treeview, path, column=None):
            model = self.__treeview.get_model()

            if self.__current is not None:
                try: model[self.get_path_from_id(self.__current)][1] = None
                except TypeError: pass
            identifier = self.get_id_from_path(path)

            order = blacfg.getint("general", "play.order")
            if (order == blaconst.ORDER_SHUFFLE and
                    self.__current != identifier and self.__current != None):
                self.__history.add(identifier, blaconst.TRACK_NEXT)
            self.__current = identifier
            path = self.get_path_from_id(self.__current)
            if blacfg.getboolean("general", "cursor.follows.playback"):
                self.set_row(path)
            track = BlaPlaylist.uris[self.__current]

            model[path][1] = gtk.STOCK_MEDIA_PLAY
            BlaPlaylist.play_track(track, self)

        def deactivate(self, clear_history=True):
            model = self.__treeview.get_model()
            self.__treeview.get_selection().unselect_all()
            try: model[self.get_path_from_id(self.__current)][1] = None
            except TypeError: pass
            if clear_history: self.__history.clear()

        def send_to_queue(self, treeview):
            queue_count = BlaQueue.get_queue_count()
            if queue_count >= blaconst.QUEUE_MAX_ITEMS: return
            count = blaconst.QUEUE_MAX_ITEMS - queue_count

            selection = treeview.get_selection().get_selected_rows()[-1]
            model = self.__treeview.get_model()

            tracks = [model[p][0] for p in selection[:count]]
            BlaQueue.queue_tracks(tracks, self)

        def remove_from_queue(self, treeview):
            selection = treeview.get_selection().get_selected_rows()[-1]
            model = self.__treeview.get_model()
            tracks = [model[p][0] for p in selection]
            BlaQueue.remove_tracks(tracks, self)

        def jump_to_playing_track(self):
            if (self.__current is None or
                    BlaPlaylist.uris[self.__current] != player.get_track(
                    uri=True)):
                return
            self.set_row(self.get_path_from_id(self.__current))

        def set_row(self, path, row_align=0.5, keep_selection=False,
                set_cursor=True):
            if not path: return

            selection = self.__treeview.get_selection()
            if keep_selection:
                selected_rows = selection.get_selected_rows()[-1]
            else: selected_rows = []

            try: low, high = self.__treeview.get_visible_range()
            except TypeError: low, high = None, None

            if low is None or not (low <= path <= high):
                self.__treeview.scroll_to_cell(
                        path, use_align=True, row_align=row_align)

            if set_cursor: self.__treeview.set_cursor(path)
            if selected_rows:
                select_path = selection.select_path
                map(select_path, selected_rows)

        def show_properties(self):
            uris = [BlaPlaylist.uris[identifier] for identifier
                    in self.get_tracks(remove=False)]
            if uris: BlaTagedit(uris)

        def __freeze_treeview(self):
            self.__treeview.freeze_notify()
            self.__treeview.freeze_child_notify()
            return self.__treeview.get_model()

        def __thaw_treeview(self):
            self.__treeview.thaw_child_notify()
            self.__treeview.thaw_notify()

        def __get_selection_and_row(self):
            row_align = 0.0
            selection = self.__treeview.get_selection()

            # get id of the row to scroll to
            try:
                identifier = self.get_id_from_path(
                        selection.get_selected_rows()[-1][0])
            except IndexError:
                try:
                    identifier = self.get_id_from_path(
                            self.__treeview.get_visible_range()[0])
                except (TypeError, IndexError): identifier = None
            else:
                column = self.__treeview.get_columns()[0]
                height = self.__treeview.get_allocation().height

                try:
                    low, high = self.__treeview.get_visible_range()
                    for path in selection.get_selected_rows()[-1]:
                        if low <= path <= high: break
                except TypeError: row_align = 0.5
                else:
                    row_align = (self.__treeview.get_cell_area(
                            path, column)[1] / float(height))

            # get selected ids
            try:
                selected_ids = [self.get_id_from_path(p)
                        for p in selection.get_selected_rows()[-1]]
            except IndexError: selected_ids = None

            if not (0.0 <= row_align <= 1.0): row_align = 0.0

            return row_align, selected_ids, identifier

        def __set_selection_and_row(self, row_align, selected_ids, identifier):
            model = self.__treeview.get_model()
            selection = self.__treeview.get_selection()

            # select rows
            if selected_ids is not None:
                paths = filter(
                        None, map(self.get_path_from_id, selected_ids))
                select_path = selection.select_path
                map(select_path, paths)

            # scroll to row
            path = self.get_path_from_id(identifier)
            if path and model.get_iter_first():
                self.set_row(path, row_align=row_align, keep_selection=True,
                        set_cursor=False)

        def __filter_parameters_changed(self, entry):
            if blacfg.getboolean("general", "search.after.timeout"):
                try: gobject.source_remove(self.__fid)
                except AttributeError: pass
                def activate():
                    self.__entry.activate()
                    return False
                self.__fid = gobject.timeout_add(500, activate)

        def __filter(self, *args):
            self.__filter_parameters = self.__entry.get_text().strip().split()
            row_align, selected_ids, scroll_identifier = \
                    self.__get_selection_and_row()

            if self.__filter_parameters: self.__mode |= MODE_FILTERED
            else: self.__mode ^= MODE_FILTERED

            # FIXME: query isn't GC'ed
            query = BlaQuery(self.__filter_parameters).query
            self.__tracks = filter(query, self.__all_tracks)

            if self.__mode & MODE_SORTED or self.__sort_parameters:
                # selection is handled in the sort function
                selected_ids = None
                try: self.sort(*self.__sort_parameters, scroll=True)
                except TypeError: self.sort(-1, None)
            else:
                model = self.__freeze_treeview()
                model.clear()
                append = model.append
                [append([identifier, "", []])
                        for identifier in self.__tracks]
                self.__thaw_treeview()

            self.__set_selection_and_row(
                    row_align, selected_ids, scroll_identifier)
            self.update_state(player.get_state())
            self.update_playlist_info()

        def __drag_data_get(self, treeview, drag_context, selection_data, info,
                time):
            self.__paths = treeview.get_selection().get_selected_rows()[-1]
            selection_data.set("tracks", 8, "")

        def __drag_data_recv(self, treeview, drag_context, x, y,
                selection_data, info, time):
            treeview.grab_focus()

            drop_info = treeview.get_dest_row_at_pos(x, y)

            # DND from the library browser
            if info == 0: data = pickle.loads(selection_data.data)

            # in-playlist DND
            elif info == 2:
                if drop_info:
                    path, pos = drop_info
                    identifier = self.get_id_from_path(path)
                    if path in self.__paths: return
                moved_ids = self.get_tracks(paths=self.__paths, remove=True)
                if drop_info:
                    path = self.get_path_from_id(identifier)
                    drop_info = (path, pos)
                uris = [BlaPlaylist.uris[identifier]
                        for identifier in moved_ids]
                self.add_tracks(drop_info=drop_info, uris=(moved_ids, uris),
                        select_rows=True)
                self.update_state(player.get_state())
                return

            # DND from an external location or the filesystem browser
            elif info in [1, 3]:
                uris = selection_data.data.strip("\n\r\x00")
                resolve_uri = blautils.resolve_uri
                uris = map(resolve_uri, uris.split())
                data = library.parse_ool_uris(uris)

            # FIXME: if data is empty gtk issues an assertion warning

            # if parsing didn't yield any tracks or the playlist was removed
            # while parsing just return
            if data and self in BlaPlaylist.pages:
                self.add_tracks(data, select_rows=True,
                        drop_info=treeview.get_dest_row_at_pos(x, y))

        def __key_press_event(self, treeview, event):
            is_accel = blagui.is_accel
            accels = [
                ("Delete", lambda: self.get_tracks(remove=True)),
                ("Q", lambda: self.send_to_queue(self.__treeview)),
                ("R", lambda: self.remove_from_queue(self.__treeview)),
                ("Escape", self.disable_search),
                ("<Alt>Return", self.show_properties)
            ]
            for accel, callback in accels:
                if is_accel(event, accel):
                    callback()
                    break
            return False

    def __init__(self):
        super(BlaPlaylist, self).__init__()
        type(self).__instance = self

        self.set_scrollable(True)

        # hook up signals
        self.connect_object("switch_page", BlaPlaylist.__switch_page, self)
        self.connect_object(
                "page_reordered", BlaPlaylist.__page_reordered, self)
        self.connect("button_press_event", self.__button_press_event)
        self.connect("key_press_event", self.__key_press_event)
        self.connect("play_track", player.play_track)
        self.connect("update_playlist_info", BlaStatusbar.update_playlist_info)
        player.connect("state_changed",
                lambda *x: self.active.update_state(player.get_state()))
        player.connect("get_track", self.get_track)

        self.show_all()
        self.show_tabs(blacfg.getboolean("general", "playlist.tabs"))

        gtk.quit_add(0, self.save)

    def __get_current_page(self):
        return self.get_nth_page(self.get_current_page())

    def __query_name(self, title, default=""):
        diag = gtk.Dialog(title=title, buttons=(gtk.STOCK_CANCEL,
                gtk.RESPONSE_CANCEL, gtk.STOCK_OK, gtk.RESPONSE_OK),
                flags=gtk.DIALOG_DESTROY_WITH_PARENT|gtk.DIALOG_MODAL
        )
        diag.set_resizable(False)

        vbox = gtk.VBox(spacing=5)
        vbox.set_border_width(10)
        entry = blaguiutils.BlaEntry()
        entry.set_text(default)
        entry.connect("activate", lambda *x: diag.response(gtk.RESPONSE_OK))
        label = gtk.Label("Title:")
        label.set_alignment(xalign=0.0, yalign=0.5)
        vbox.pack_start(label)
        vbox.pack_start(entry)
        diag.vbox.pack_start(vbox)
        diag.show_all()
        response = diag.run()

        if response == gtk.RESPONSE_OK: name = entry.get_text()
        else: name = ""

        diag.destroy()
        return name

    def __rename_playlist(self, child):
        label = self.get_tab_label(child)
        new_name = self.__query_name("Rename playlist", label.get_text())
        if new_name: label.set_text(new_name)

    def __open_popup(self, child, button, time, all_options=True):
        menu = gtk.Menu()

        items = [
            ("Rename playlist", lambda *x: self.__rename_playlist(child)),
            ("Remove playlist", lambda *x: self.remove_playlist(child)),
            ("Clear playlist", lambda *x: child.clear())
        ]

        for label, callback in items:
            m = gtk.MenuItem(label)
            m.connect("activate", callback)
            if not all_options: m.set_sensitive(False)
            menu.append(m)

        menu.append(gtk.SeparatorMenuItem())

        m = gtk.MenuItem("Add new playlist...")
        m.connect("activate",
                lambda *x: self.add_playlist(query_name=True, focus=True))
        menu.append(m)

        menu.show_all()
        menu.popup(None, None, None, button, time)

    @classmethod
    def __save_m3u(cls, uris, path):
        with open(path, "w") as f:
            f.write("#EXTM3U\n")
            for uri in uris:
                track = library[uri]
                length = track[LENGTH]
                artist = track[ARTIST]
                title = track[TITLE]
                if artist: header = "%s - %s" % (artist, title)
                else: header = title
                f.write("#EXTINF:%d, %s\n%s\n" % (length, header, uri))

    @classmethod
    def __parse_m3u(cls, path):
        uris = []
        try:
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line.startswith("#"): uris.append(line)
        except IOError:
            blaguiutils.error_dialog("Failed to parse playlist \"%s\"" % path)
            return None

        return uris

    @classmethod
    def __save_pls(cls, uris, path):
        try:
            with open(path, "w") as f:
                f.write("[playlist]\n")
                for idx, uri in enumerate(uris):
                    track = library[uri]
                    idx += 1
                    text = "File%d=%s\nTitle%d=%s\nLength%d=%s\n" % (idx, uri,
                            idx, track[TITLE], idx, track[LENGTH])
                    f.write(text)
                f.write("NumberOfEntries=%d\nVersion=2\n" % len(uris))

        except IOError:
            blaguiutils.error_dialog("Failed to save playlist \"%s\"" % path)

    @classmethod
    def __parse_pls(cls, path):
        uris = []
        try:
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line.lower().startswith("file"):
                        try: line = line[line.index("=")+1:].strip()
                        except ValueError: pass
                        else: uris.append(line)
        except IOError:
            blaguiutils.error_dialog("Failed to parse playlist \"%s\"" % path)
            return None

        return uris

    @classmethod
    def __save_xspf(cls, uris, path, name):
        # improved version of exaile's implementation

        from urllib import quote
        tags = {
            "title": TITLE,
            "creator": ARTIST,
            "album": ALBUM,
            "trackNum": TRACK
        }
        try:
            with open(path, "w") as f:
                f.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
                        "<playlist version=\"1\" "
                        "xmlns=\"http://xspf.org/ns/0/\">\n"
                )
                f.write("  <title>%s</title>\n" % name)
                f.write("  <trackList>\n")
                for uri in uris:
                    track = library[uri]
                    f.write("    <track>\n")
                    for element, identifier in tags.items():
                        value = track[identifier].replace("&", "&amp;amp;")
                        if not value: continue
                        f.write("      <%s>%s</%s>\n"
                                % (element, value, element))
                    f.write("      <location>%s</location>\n" % quote(uri))
                    f.write("    </track>\n")
                f.write("  </trackList>\n")
                f.write("</playlist>\n")

        except IOError:
            blaguiutils.error_dialog("Failed to save playlist \"%s\"" % path)

    @classmethod
    def __parse_xspf(cls, path):
        # improved version of exaile's implementation. this method is merely a
        # stub to retrieve URIs and the playlist name. we completely disregard
        # any metadata tags and just feed each URI to our track parser

        name, uris = "", []
        try:
            with open(path, "r") as f:
                import xml.etree.cElementTree as ETree
                tree = ETree.ElementTree(None, f)
                ns = "{http://xspf.org/ns/0/}"
                nodes = tree.find("%strackList" % ns).findall("%strack" % ns)
                name = tree.find("%stitle" % ns)
                if name is not None: name = name.text.strip()
                for node in nodes:
                    uris.append(node.find("%slocation" % ns).text.strip())

        except IOError:
            blaguiutils.error_dialog("Failed to parse playlist \"%s\"" % path)
            uris = None

        return name, uris

    @classmethod
    def get_track_from_id(cls, identifier):
        try: uri = cls.uris[identifier]
        except KeyError:
            if isinstance(identifier, str): uri = identifier
            else: raise ValueError("Invalid identifier: %s" % identifier)
        return library[uri]

    @classmethod
    def enable_search(cls):
        if blacfg.getint("general", "view") == blaconst.VIEW_PLAYLISTS:
            cls.__instance.__get_current_page().enable_search()

    def clear(self):
        self.__get_current_page().clear()

    @classmethod
    def open_playlist(cls, path):
        name = os.path.basename(blautils.toss_extension(path))
        ext = blautils.get_extension(path).lower()

        if ext == "m3u": uris = cls.__parse_m3u(path)
        elif ext == "pls": uris = cls.__parse_pls(path)
        elif ext == "xspf": name, uris = cls.__parse_xspf(path)
        else:
            blaguiutils.error_dialog("Failed to open playlist \"%s\"" % path,
                    "Currently we only support are M3U and PLS playlists with "
                    "absolute paths."
            )
            return False
        if uris is None: return False

        resolve_uri = blautils.resolve_uri
        uris = library.parse_ool_uris(map(resolve_uri, uris))
        if uris is None: return False
        playlist = cls.__instance.add_playlist(focus=True, name=name)
        playlist.add_tracks(uris=uris)
        return True

    @classmethod
    def save(cls, path=None, type_="m3u"):
        @blautils.thread
        def save(path, type_):
            name = cls.__instance.get_tab_label_text(
                    cls.__instance.__get_current_page())
            uris = cls.__instance.__get_current_page().get_uris()

            ext = blautils.get_extension(path)
            if ext.lower() != type_: path = "%s.%s" % (path, type_)

            if type_.lower() == "pls": cls.__save_pls(uris, path)
            elif type_.lower() == "xspf": cls.__save_xspf(uris, path, name)
            else: cls.__save_m3u(uris, path)

        if path is None:
            playlists = cls.__instance.get_playlists()
            library.save_playlists(playlists, BlaQueue.get_queued_tracks())
        else: save(path, type_)
        return 0

    def get_playlists(self):
        blaplay.print_i("Saving playlists")

        playlists = []
        for playlist in self:
            if playlist == type(self).active: current_playlist = True
            else: current_playlist = False
            name = self.get_tab_label(playlist).get_text()
            playlists.append(
                    [name, current_playlist] + playlist.package_playlist())
        return playlists

    def restore(self):
        blaplay.print_i("Restoring playlists")

        playlists, queue = library.get_playlists()

        if playlists:
            for idx, playlist in enumerate(playlists):
                name, current_playlist, restore, current, uris = playlist
                playlist = self.add_playlist(name=name)
                playlist.add_tracks(
                        uris=uris, current=current, restore=restore)
                if current_playlist:
                    self.set_current_page(idx)
                    type(self).active = playlist
            BlaQueue.restore_queue(queue)
        else: self.add_playlist()

        self.active.update_playlist_info()

    @classmethod
    def add_playlist(cls, name=None, query_name=False, focus=False):
        list_name = ""

        if query_name:
            list_name = cls.__instance.__query_name("Playlist name")
            if not list_name: return

        elif name: list_name = name

        else:
            indices = []
            for idx, playlist in enumerate(cls.__instance):
                label = cls.__instance.get_tab_label_text(playlist)

                if label == "bla":
                    indices.append(0)
                    continue
                try:
                    num = int(label.split("bla (")[-1].split(")")[0])
                    if num > 0: indices.append(num)
                except ValueError: continue

            indices = list(set(indices))
            if not indices or 0 not in indices: list_name = "bla"
            else:
                candidates = xrange(1, max(indices)+2)
                for idx in xrange(1, len(indices)):
                    if indices[idx] != candidates[idx]:
                        list_name = "bla (%d)" % candidates[idx]
                        break

                if not list_name: list_name = "bla (%d)" % (len(indices)+1)

        playlist = BlaPlaylist.Playlist()
        BlaPlaylist.pages.append(playlist)
        page_num = cls.__instance.append_page(playlist, gtk.Label(list_name))
        cls.__instance.child_set_property(playlist, "reorderable", True)

        if focus: cls.__instance.set_current_page(page_num)

        # if we don't have a current playlist select the one we just created
        if not cls.active: cls.active = playlist

        cls.__instance.emit("count_changed", blaconst.VIEW_PLAYLISTS,
                cls.__instance.get_n_pages())
        return playlist

    @classmethod
    def remove_playlist(cls, playlist):
        if not playlist: return False

        if playlist == cls.active: cls.active = None
        page_num = cls.__instance.page_num(playlist)

        if page_num != -1:
            cls.__instance.remove_page(page_num)
            BlaPlaylist.pages.remove(playlist)
            playlist.destroy()
            del playlist

        # if we just removed the last playlist, create an empty new one
        if cls.__instance.get_n_pages() < 1: cls.__instance.add_playlist()

        # select the actively viewed playlist as the new current playlist to
        # pick tracks from on track change
        cls.active = cls.__instance.__get_current_page()

        cls.__instance.emit("count_changed", blaconst.VIEW_PLAYLISTS,
                cls.__instance.get_n_pages())
        return False

    @classmethod
    def select(cls, type_):
        cls.__instance.__get_current_page().select(type_)

    @classmethod
    def cut(cls, *args):
        playlist = cls.__instance.__get_current_page()
        cls.clipboard = playlist.get_tracks(remove=True)
        blagui.update_menu(blaconst.VIEW_PLAYLISTS)

    @classmethod
    def copy(cls, *args):
        playlist = cls.__instance.__get_current_page()
        cls.clipboard = playlist.get_tracks(remove=False)
        blagui.update_menu(blaconst.VIEW_PLAYLISTS)

    @classmethod
    def paste(cls, *args, **kwargs):
        playlist = cls.__instance.__get_current_page()
        playlist.add_tracks(uris=[cls.uris[identifier] for identifier in
                cls.clipboard], drop_info="at_cursor", select_rows=True)

    @classmethod
    def remove(cls, *args):
        playlist = cls.__instance.__get_current_page()
        playlist.get_tracks(remove=True)

    @classmethod
    def new_playlist(cls, type_):
        cls.__instance.__get_current_page().new_playlist(type_)

    @classmethod
    def remove_duplicates(cls):
        cls.__instance.__get_current_page().remove_duplicates()

    @classmethod
    def remove_invalid_tracks(cls):
        cls.__instance.__get_current_page().remove_invalid_tracks()

    @classmethod
    def send_to_current_playlist(cls, name, uris, resolve=False):
        playlist = cls.__instance.__get_current_page()
        if resolve: uris = library.parse_ool_uris(uris)
        if not uris: return

        cls.active.deactivate()
        cls.active = playlist
        cls.active.add_tracks(uris, flush=True)
        force_view()

    @classmethod
    def add_to_current_playlist(cls, name, uris, resolve=False):
        playlist = cls.__instance.__get_current_page()
        if resolve: uris = library.parse_ool_uris(uris)
        if not uris: return

        playlist.add_tracks(uris, select_rows=True)
        force_view()

    @classmethod
    def send_to_new_playlist(cls, name, uris, resolve=False):
        if resolve: uris = library.parse_ool_uris(uris)
        if not uris: return

        playlist = cls.__instance.add_playlist(name=name, focus=True)
        playlist.add_tracks(uris)
        force_view()

    @classmethod
    def update_playlist_info(cls, count, size, length):
        cls.__instance.emit("update_playlist_info", count, size, length)

    @classmethod
    def update_uris(cls, uris):
        old_uris = dict(
            zip(BlaPlaylist.uris.values(), BlaPlaylist.uris.keys()))
        for old_uri, new_uri in uris:
            try: old_uris[new_uri] = old_uris.pop(old_uri)
            except KeyError: pass
        BlaPlaylist.uris = dict(zip(old_uris.values(), old_uris.keys()))

    @classmethod
    def update_contents(cls):
        cls.__instance.__get_current_page().update_contents()

    @classmethod
    def play_track(cls, track, playlist):
        if cls.active != playlist: cls.active.deactivate()
        cls.active = playlist
        cls.__instance.emit("play_track", track)

    @classmethod
    def play_from_playlist(cls, track, playlist):
        if playlist:
            if cls.active: cls.active.deactivate(clear_history=True)
            cls.active = playlist
            cls.active.play_track(treeview=None,
                    path=playlist.get_path_from_id(track), column=None)
        else:
            if cls.active: cls.active.deactivate(clear_history=False)
            cls.__instance.emit("play_track", track)

    def get_track(self, player, choice, force_advance):
        try:
            if choice in [blaconst.TRACK_PREVIOUS, blaconst.TRACK_RANDOM]:
                raise TypeError
            track, playlist = BlaQueue.get_track()
        except TypeError:
            if self.active:
                track = self.active.get_track(choice, force_advance)
                self.emit("play_track", track)
        else:
            if (playlist and
                    self.page_num(playlist) != -1 and
                    playlist.get_path_from_id(track) is not None):
                self.play_from_playlist(track, playlist)
            else:
                if self.active: self.active.deactivate()
                try: uri = BlaPlaylist.uris[track]
                except KeyError:
                    if isinstance(track, str): uri = track
                    else: raise ValueError("Invalid identifier: %r" % track)
                self.emit("play_track", uri)

    @classmethod
    def show_properties(cls, *args):
        cls.__instance.__get_current_page().show_properties()

    @classmethod
    def show_tabs(cls, state):
        cls.__instance.set_show_tabs(state)
        blacfg.setboolean("general", "playlist.tabs", state)

    @classmethod
    def jump_to_playing_track(cls):
        if (blacfg.getint("general", "view") == blaconst.VIEW_PLAYLISTS and
                cls.active == cls.__instance.__get_current_page()):
            cls.active.jump_to_playing_track()

    def __switch_page(self, *args):
        page = self.get_nth_page(args[-1])
        page.update_playlist_info()

    def __page_reordered(self, page, page_num):
        BlaPlaylist.pages.remove(page)
        BlaPlaylist.pages.insert(page_num, page)

    def __button_press_event(self, notebook, event):
        for child in notebook.get_children():
            label = notebook.get_tab_label(child)
            x0, y0 = self.window.get_origin()
            x, y, w, h = label.get_allocation()
            xp = self.get_property("tab_hborder")
            yp = self.get_property("tab_vborder")

            x_min = x0 + x - 2 * xp
            x_max = x0 + x + w + 2 * xp
            y_min = y0 + y - 2 * yp
            y_max = y0 + y + h + 2 * yp

            if (event.x_root >= x_min and event.x_root <= x_max and
                    event.y_root >= y_min and event.y_root <= y_max):
                if (event.button == 2 and
                        not event.type == gtk.gdk._2BUTTON_PRESS and
                        not event.type == gtk.gdk._3BUTTON_PRESS):
                    self.remove_playlist(child)

                elif event.button == 3:
                    self.__open_popup(child, event.button, event.time)

                return False

        if ((event.button == 2 and
                not event.type == gtk.gdk._2BUTTON_PRESS and
                not event.type == gtk.gdk._3BUTTON_PRESS) or
                (event.button == 1 and
                event.type == gtk.gdk._2BUTTON_PRESS)):
            self.add_playlist(focus=True)
            return True

        elif event.button == 3:
            self.__open_popup(None, event.button, event.time,
                    all_options=False)
            return True

        return False

    def __key_press_event(self, notebook, event):
        if blagui.is_accel(event, "<Ctrl>T"): self.add_playlist(focus=True)
        elif blagui.is_accel(event, "<Ctrl>W"):
            BlaPlaylist.remove_playlist(self.__get_current_page())
        return False

