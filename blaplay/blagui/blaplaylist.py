# blaplay, Copyright (C) 2012-2013  Niklas Koep

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
import xml.etree.cElementTree as ETree
from xml.sax.saxutils import escape as xml_escape
from copy import copy

import gobject
import gtk
import cairo
import pango
import pangocairo
import numpy as np

import blaplay
player = blaplay.bla.player
library = blaplay.bla.library
from blaplay.blacore import blaconst, blacfg
from blaplay import blautil, blagui
from blaplay.blautil import blafm
from blastatusbar import BlaStatusbar
from blatagedit import BlaTagedit
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
    if blacfg.getint("general", "view") != blaconst.VIEW_PLAYLISTS:
        from blaview import BlaView
        BlaView.update_view(blaconst.VIEW_PLAYLISTS)

def parse_playlist_stats(count, size, length_seconds):
    values = [("seconds", 60), ("minutes", 60), ("hours", 24), ("days",)]
    length = {}.fromkeys([v[0] for v in values], 0)
    length["seconds"] = length_seconds

    for idx in xrange(len(values) - 1):
        v = values[idx]
        div, mod = divmod(length[v[0]], v[1])
        length[v[0]] = mod
        length[values[idx+1][0]] += div

    labels = []
    keys = ["days", "hours", "minutes", "seconds"]
    for k in keys:
        if length[k] == 1:
            labels.append(k[:-1])
        else:
            labels.append(k)

    if length["days"] != 0:
        length = "%d %s %d %s %d %s %d %s" % (
            length["days"], labels[0], length["hours"], labels[1],
            length["minutes"], labels[2], length["seconds"], labels[3])
    elif length["hours"] != 0:
        length = "%d %s %d %s %d %s" % (
            length["hours"], labels[1], length["minutes"], labels[2],
            length["seconds"], labels[3])
    elif length["minutes"] != 0:
        length = "%d %s %d %s" % (
            length["minutes"], labels[2], length["seconds"], labels[3])
    elif length["seconds"] != 0:
        length = "%d %s" % (length["seconds"], labels[3])

    mb = 1024.0 * 1024.0
    if size > mb * 1024.0:
        size /= mb * 1024.0
        unit = "GB"
    else:
        size /= mb
        unit = "MB"
    size = "%.1f %s" % (size, unit)

    if count == 1:
        return "%s track (%s) | %s" % (count, size, length)
    return "%s tracks (%s) | %s" % (count, size, length)

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
        else:
            column.set_min_width(width + 12 + xpad)

        widget = column.get_widget()
        widget.show()
        treeview.append_column(column)
        widget.get_ancestor(gtk.Button).connect(
            "button_press_event", header_popup, view_id)
        column.connect(
            "clicked",
            lambda c=column, i=column_id: treeview.sort_column(c, i))

    treeview.connect_changed_signal()

def columns_changed(treeview, view_id):
    if view_id == blaconst.VIEW_PLAYLISTS:
        view = "playlist"
    elif view_id == blaconst.VIEW_QUEUE:
        view = "queue"

    columns = [column.id for column in treeview.get_columns()]
    blacfg.set("general", "columns.%s" % view, ", ".join(map(str, columns)))

def popup(treeview, event, view_id, target):
    if view_id == blaconst.VIEW_PLAYLISTS:
        element = BlaPlaylistManager
    elif view_id == blaconst.VIEW_QUEUE:
        element = BlaQueue

    try:
        path = treeview.get_path_at_pos(*map(int, [event.x, event.y]))[0]
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
            m.connect("activate", lambda *x: element.clear())
            menu.append(m)

        menu.show_all()
        menu.popup(None, None, None, event.button, event.time)
        return

    model, paths = treeview.get_selection().get_selected_rows()
    item = model[path][0]

    menu = gtk.Menu()

    m = gtk.MenuItem("Play")
    m.connect("activate", lambda *x: target.play_item(treeview, path))
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
        ("Complement", blaconst.SELECT_COMPLEMENT),
        ("By artist(s)", blaconst.SELECT_BY_ARTISTS),
        ("By album(s)", blaconst.SELECT_BY_ALBUMS),
        ("By album artist(s)", blaconst.SELECT_BY_ALBUM_ARTISTS),
        ("By genre(s)", blaconst.SELECT_BY_GENRES)
    ]

    for label, type_ in items:
        m = gtk.MenuItem(label)
        m.connect("activate", lambda x, t=type_: element.select(t))
        submenu.append(m)

    m = gtk.MenuItem("Select")
    m.set_submenu(submenu)
    menu.append(m)

    if view_id == blaconst.VIEW_PLAYLISTS:
        # New playlist from...
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
                      lambda x, t=type_: BlaPlaylistManager.new_playlist(t))
            submenu.append(m)

        m = gtk.MenuItem("New playlist from")
        m.set_submenu(submenu)
        menu.append(m)

        playlists = BlaPlaylistManager.get_playlists()
        if len(playlists) > 1:
            # Move to playlist
            submenu = gtk.Menu()
            current_playlist = BlaPlaylistManager.get_current_playlist()
            for playlist in playlists:
                try:
                    if playlist == current_playlist:
                        raise AttributeError
                    label = BlaPlaylistManager.get_playlist_name(playlist)
                except AttributeError:
                    continue
                m = gtk.MenuItem(label)
                m.connect("activate", lambda x, p=playlist:
                          target.add_selection_to_playlist(p, move=True))
                submenu.append(m)

            m = gtk.MenuItem("Move to playlist")
            m.set_submenu(submenu)
            menu.append(m)

            # Add to playlist
            submenu = gtk.Menu()
            current_playlist = BlaPlaylistManager.get_current_playlist()
            for playlist in playlists:
                try:
                    if playlist == current_playlist:
                        raise AttributeError
                    label = BlaPlaylistManager.get_playlist_name(playlist)
                except AttributeError:
                    continue
                m = gtk.MenuItem(label)
                m.connect("activate", lambda x, p=playlist:
                          target.add_selection_to_playlist(p, move=False))
                submenu.append(m)

            m = gtk.MenuItem("Add to playlist")
            m.set_submenu(submenu)
            menu.append(m)

        menu.append(gtk.SeparatorMenuItem())

        # Remaining options
        items = [
            ("Add to queue", "Q", lambda *x: target.send_to_queue()),
            ("Remove from queue", "R",
             lambda *x: target.remove_from_queue(treeview)),
        ]
        for label, accel, callback in items:
            m = gtk.MenuItem(label)
            mod, key = gtk.accelerator_parse(accel)
            m.add_accelerator(
                "activate", blagui.accelgroup, mod, key, gtk.ACCEL_VISIBLE)
            m.connect("activate", callback)
            menu.append(m)

    menu.append(gtk.SeparatorMenuItem())

    item = treeview.get_model()[path][0]
    submenu = blafm.get_popup_menu(item.track)
    if submenu:
        m = gtk.MenuItem("last.fm")
        m.set_submenu(submenu)
        menu.append(m)

    m = gtk.MenuItem("Open containing directory")
    m.connect("activate",
              lambda *x: blautil.open_directory(os.path.dirname(item.uri)))
    menu.append(m)

    menu.append(gtk.SeparatorMenuItem())

    m = gtk.MenuItem("Properties")
    mod, key = gtk.accelerator_parse("<Alt>Return")
    m.add_accelerator("activate", blagui.accelgroup, mod, key,
                      gtk.ACCEL_VISIBLE)
    m.connect("activate", element.show_properties)
    menu.append(m)

    menu.show_all()
    menu.popup(None, None, None, event.button, event.time)

def header_popup(button, event, view_id):
    if not (hasattr(event, "button") and event.button == 3):
        return False

    def column_selected(m, column_id, view_id, view):
        if m.get_active():
            if column_id not in columns:
                columns.append(column_id)
        else:
            try:
                columns.remove(column_id)
            except ValueError:
                pass

        blacfg.set("general",
                   "columns.%s" % view, ", ".join(map(str, columns)))
        if view_id == blaconst.VIEW_PLAYLISTS:
            for treeview in BlaTreeView.playlist_instances:
                update_columns(treeview, view_id)
        else:
            update_columns(BlaTreeView.queue_instance, view_id)

    menu = gtk.Menu()

    if view_id == blaconst.VIEW_PLAYLISTS:
        default = COLUMNS_DEFAULT_PLAYLIST
        view = "playlist"
    elif view_id == blaconst.VIEW_QUEUE:
        default = COLUMNS_DEFAULT_QUEUE
        view = "queue"

    columns = blacfg.getlistint("general", "columns.%s" % view)
    if columns is None:
        columns = default

    for column_id, label in enumerate(COLUMN_TITLES):
        if ((column_id == COLUMN_PLAYING and view_id == blaconst.VIEW_QUEUE) or
            (column_id == COLUMN_QUEUE_POSITION and
            view_id == blaconst.VIEW_PLAYLISTS)):
            continue

        m = gtk.CheckMenuItem(label)
        if column_id in columns:
            m.set_active(True)
            if len(columns) == 1:
                m.set_sensitive(False)
        m.connect("toggled", column_selected, column_id, view_id, view)
        menu.append(m)

    menu.show_all()
    menu.popup(None, None, None, event.button, event.time)

    return True

def create_items_from_uris(uris):
    return map(BlaListItem, uris)


class BlaQuery(object):
    def __init__(self, filter_string, regexp):
        self.__query_identifiers = [ARTIST, TITLE, ALBUM]
        columns = blacfg.getlistint("general", "columns.playlist")
        if columns is None:
            columns = COLUMNS_DEFAULT_PLAYLIST
        for column_id in columns:
            self.__query_identifiers.extend(
                self.__column_to_tag_ids(column_id))

        flags = re.UNICODE | re.IGNORECASE
        if regexp:
            self.__res = [re.compile(r"%s" % filter_string, flags)]
        else:
            self.__res = [re.compile(t.decode("utf-8"), flags)
                          for t in map(re.escape, filter_string.split())]

    def __column_to_tag_ids(self, column_id):
        if column_id == COLUMN_ALBUM_ARTIST:
            return [ALBUM_ARTIST, COMPOSER, PERFORMER]
        elif column_id == COLUMN_YEAR:
            return [YEAR]
        elif column_id == COLUMN_GENRE:
            return [GENRE]
        elif column_id == COLUMN_FORMAT:
            return [FORMAT]
        return []

    def query(self, item):
        track = item.track
        for r in self.__res:
            search = r.search
            for identifier in self.__query_identifiers:
                if search(track[identifier]):
                    break
            else:
                return False
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
        "text": (gobject.TYPE_STRING, "text", "", "", gobject.PARAM_READWRITE),
        "stock-id": (gobject.TYPE_STRING, "text", "", "",
                     gobject.PARAM_READWRITE)
    }

    def __init__(self):
        super(BlaCellRenderer, self).__init__()

    def __get_layout(self, widget):
        context = widget.get_pango_context()
        layout = pango.Layout(context)
        fdesc = gtk.widget_get_default_style().font_desc
        layout.set_font_description(fdesc)
        layout.set_text(self.get_property("text"))
        return layout

    def on_get_size(self, widget, cell_area):
        return (0, 0, -1, -1)

    def on_render(self, window, widget, background_area, cell_area,
                  expose_area, flags):
        cr = window.cairo_create()

        # Check if a state icon should be rendered.
        stock = self.get_property("stock-id")
        if stock:
            # ICON_SIZE_MENU is the default size specified in the GTK sources.
            pixbuf = widget.render_icon(stock, gtk.ICON_SIZE_MENU)
            width, height = pixbuf.get_width(), pixbuf.get_height()
            cr.set_source_pixbuf(
                pixbuf,
                expose_area.x + round((expose_area.width - width + 0.5) / 2),
                expose_area.y + round((expose_area.height - height + 0.5) / 2))
            cr.rectangle(*expose_area)
            cr.fill()
        else:
            # Render active resp. inactive rows.
            layout = self.__get_layout(widget)
            width, height = layout.get_pixel_size()
            layout.set_width((expose_area.width + expose_area.x) * pango.SCALE)
            layout.set_ellipsize(pango.ELLIPSIZE_END)
            layout.set_font_description(widget.get_style().font_desc)

            if blacfg.getboolean("colors", "overwrite"):
                if (flags == (gtk.CELL_RENDERER_SELECTED |
                    gtk.CELL_RENDERER_PRELIT) or
                    flags == gtk.CELL_RENDERER_SELECTED):
                    color = gtk.gdk.color_parse(self._active_text_color)
                else:
                    color = gtk.gdk.color_parse(self._text_color)
            else:
                style = widget.get_style()
                if (flags == (gtk.CELL_RENDERER_SELECTED |
                    gtk.CELL_RENDERER_PRELIT) or
                    flags == gtk.CELL_RENDERER_SELECTED):
                    color = style.text[gtk.STATE_SELECTED]
                else:
                    color = style.text[gtk.STATE_NORMAL]
            cr.set_source_color(color)

            pc_context = pangocairo.CairoContext(cr)
            if width < expose_area.width:
                x = (expose_area.x +
                     round((expose_area.width - width + 0.5) / 2))
            else:
                x = expose_area.x
            pc_context.move_to(x, expose_area.y +
                               round((expose_area.height - height + 0.5) / 2))
            pc_context.show_layout(layout)

class BlaTreeView(blaguiutils.BlaTreeViewBase):
    __gsignals__ = {
        "sort_column": blautil.signal(2)
    }

    playlist_instances = []
    queue_instance = None

    def __init__(self, view_id=None):
        super(BlaTreeView, self).__init__(multicol=True)

        if view_id == blaconst.VIEW_PLAYLISTS:
            BlaTreeView.playlist_instances.append(self)
        else:
            BlaTreeView.queue_instance = self

        self.__view_id = view_id
        self.set_fixed_height_mode(True)
        self.set_rubber_banding(True)
        self.set_property("rules_hint", True)
        self.connect("destroy", self.__destroy)
        self.connect_changed_signal()

    def __destroy(self, *args):
        try:
            BlaTreeView.playlist_instances.remove(self)
        except ValueError:
            pass

    def connect_changed_signal(self):
        if self.__view_id is not None:
            self.__columns_changed_id = self.connect(
                "columns_changed", columns_changed, self.__view_id)

    def disconnect_changed_signal(self):
        try:
            self.disconnect(self.__columns_changed_id)
        except AttributeError:
            pass

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
        try:
            self.eval = self.__callbacks[column_id]
        except IndexError:
            self.eval = BlaEval.__empty_cb

    # These methods are static despite the absence of staticmethod decorators.
    def __empty_cb(track):
        return ""

    def __track_cb(track):
        try:
            value = "%d." % int(track[DISC].split("/")[0])
        except ValueError:
            value = ""
        try:
            value += "%02d" % int(track[TRACK].split("/")[0])
        except ValueError:
            pass
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
        return (track[ALBUM_ARTIST] or track[PERFORMER] or track[ARTIST] or
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
        return os.path.basename(track.uri)

    def __extension_cb(track):
        return blautil.get_extension(track.uri)

    def __directory_cb(track):
        return os.path.dirname(track.uri)

    def __path_cb(track):
        return track.uri

    def __filesize_cb(track):
        return track.get_filesize(short=True)

    __callbacks = [
        __empty_cb, __empty_cb, __track_cb, __artist_cb, __title_cb,
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

        if column_id != COLUMN_PLAYING:
            self.set_clickable(True)
        self.set_resizable(True)
        self.set_cell_data_func(r, self.__cell_data_func, column_id)
        self.set_alignment(alignment)

    def __cell_data_func(self, column, renderer, model, iterator, column_id):
        item = model[iterator][0]

        if column_id == COLUMN_QUEUE_POSITION:
            text = "%02d" % int(model[iterator][1])
        elif column_id == COLUMN_PLAYING:
            pos = BlaQueue.get_queue_positions(item)
            text = "(%s)" % (", ".join(pos)) if pos else ""
        else:
            text = self.__cb(item.track)

        renderer.set_property("text", text)

class BlaListItem(object):
    def __init__(self, uri):
        self.uri = uri
        self.playlist = None

    @property
    def track(self):
        return library[self.uri]

    def play(self):
        BlaPlaylistManager.play_item(self)

    def select(self):
        if self.playlist:
            if BlaPlaylistManager.get_current_playlist() != self.playlist:
                BlaPlaylistManager.focus_playlist(self.playlist)
            self.playlist.set_row(self.playlist.get_path_from_item(self))

    def clear_icon(self):
        if self.playlist:
            self.playlist.update_icon(clear=True)

class BlaQueue(blaguiutils.BlaScrolledWindow):
    __gsignals__ = {
        "count_changed": blautil.signal(2)
    }

    __layout = (
        gobject.TYPE_PYOBJECT,  # An instance of BlaListItem
        gobject.TYPE_STRING     # Position in the queue
    )
    __treeview = BlaTreeView(view_id=blaconst.VIEW_QUEUE)
    __instance = None
    __size = 0
    __length = 0

    clipboard = []

    @property
    def name(self):
        return "Queue"

    def __init__(self):
        super(BlaQueue, self).__init__()
        type(self).__instance = self

        self.__treeview.set_model(gtk.ListStore(*self.__layout))
        self.__treeview.set_enable_search(False)
        self.__treeview.set_property("rules_hint", True)

        self.set_shadow_type(gtk.SHADOW_IN)
        self.add(self.__treeview)

        self.__treeview.enable_model_drag_dest(
            [("queue", 0, 3)], gtk.gdk.ACTION_COPY)
        self.__treeview.enable_model_drag_source(
            gtk.gdk.BUTTON1_MASK, [("queue", gtk.TARGET_SAME_WIDGET, 3)],
            gtk.gdk.ACTION_COPY)

        self.__treeview.connect("popup", popup, blaconst.VIEW_QUEUE, self)
        self.__treeview.connect("row_activated", self.play_item)
        self.__treeview.connect(
            "button_press_event", self.__button_press_event)
        self.__treeview.connect("key_press_event", self.__key_press_event)
        self.__treeview.connect("drag_data_get", self.__drag_data_get)
        self.__treeview.connect("drag_data_received", self.__drag_data_recv)

        update_columns(self.__treeview, view_id=blaconst.VIEW_QUEUE)
        self.show_all()

    def __button_press_event(self, treeview, event):
        if (event.button == 2 and
            event.type not in [gtk.gdk._2BUTTON_PRESS,
                               gtk.gdk._3BUTTON_PRESS]):
            self.paste()
            return True

    def __key_press_event(self, treeview, event):
        if blagui.is_accel(event, "<Ctrl>X"):
            self.cut()
        elif blagui.is_accel(event, "<Ctrl>C"):
            self.copy()
        elif blagui.is_accel(event, "<Ctrl>V"):
            self.paste()
        elif blagui.is_accel(event, "Delete"):
            self.remove()
        elif blagui.is_accel(event, "<Alt>Return"):
            self.show_properties()
        return False

    def __drag_data_get(self, treeview, drag_context, selection_data, info,
                        time):
        data = pickle.dumps(treeview.get_selection().get_selected_rows()[-1],
                            pickle.HIGHEST_PROTOCOL)
        selection_data.set("", 8, data)

    def __drag_data_recv(self, treeview, drag_context, x, y, selection_data,
                         info, time):
        drop_info = treeview.get_dest_row_at_pos(x, y)
        model = self.__treeview.get_model()
        paths = pickle.loads(selection_data.data)

        if drop_info:
            path, pos = drop_info
            iterator = model.get_iter(path)

            if (pos == gtk.TREE_VIEW_DROP_BEFORE or
                pos == gtk.TREE_VIEW_DROP_INTO_OR_BEFORE):
                move_before = model.move_before
                def move_func(it):
                    move_before(it, iterator)
            else:
                move_after = model.move_after
                def move_func(it):
                    move_after(it, iterator)
                paths.reverse()
        else:
            iterator = None
            move_before = model.move_before
            def move_func(it):
                move_before(it, iterator)

        get_iter = model.get_iter
        iterators = map(get_iter, paths)
        map(move_func, iterators)
        self.update_queue_positions()

    @classmethod
    def __add_items(cls, items, path=None, select_rows=False):
        treeview = cls.__treeview
        model = treeview.get_model()
        iterator = None

        try:
            if (not treeview.get_selection().get_selected_rows()[-1] or
                path == -1):
                raise TypeError
            if not path:
                path, column = cls.__treeview.get_cursor()
        except TypeError:
            path = (len(model),)
            append = model.append
            def insert_func(iterator, item):
                append(item)
        else:
            iterator = model.get_iter(path)
            insert_func = model.insert_before
            items.reverse()

        for item in items:
            iterator = insert_func(iterator, [item, None])

        if select_rows:
            cls.__treeview.freeze_notify()
            selection = cls.__treeview.get_selection()
            selection.unselect_all()
            select_path = selection.select_path
            map(select_path, xrange(path[0], path[0] + len(items)))
            cls.__treeview.thaw_notify()

        cls.update_queue_positions()

    @classmethod
    def __get_items(cls, remove=True):
        treeview = cls.__treeview
        model, selections = treeview.get_selection().get_selected_rows()
        if selections:
            get_iter = model.get_iter
            iterators = map(get_iter, selections)
            items = [model[iterator][0] for iterator in iterators]
            if remove:
                remove = model.remove
                map(remove, iterators)
                cls.update_queue_positions()
            return items
        return []

    def play_item(self, treeview, path, column=None):
        model = treeview.get_model()
        iterator = model.get_iter(path)
        model[iterator][0].play()
        if blacfg.getboolean("general", "queue.remove.when.activated"):
            model.remove(iterator)
            self.update_queue_positions()

    def update_statusbar(self):
        model = self.__treeview.get_model()
        count = len(model)
        if count == 0:
            info = ""
        else:
            info = parse_playlist_stats(count, self.__size, self.__length)
        BlaStatusbar.set_view_info(blaconst.VIEW_QUEUE, info)

    @classmethod
    def select(cls, type_):
        treeview = cls.__treeview
        selection = treeview.get_selection()
        model, selected_paths = selection.get_selected_rows()

        if type_ == blaconst.SELECT_ALL:
            selection.select_all()
            return
        elif type_ == blaconst.SELECT_COMPLEMENT:
            selected_paths = set(selected_paths)
            paths = set([(p,) for p in xrange(len(model))])
            paths.difference_update(selected_paths)
            selection.unselect_all()
            select_path = selection.select_path
            map(select_path, paths)
            return

        elif type_ == blaconst.SELECT_BY_ARTISTS:
            column_id = COLUMN_ARTIST
        elif type_ == blaconst.SELECT_BY_ALBUMS:
            column_id = COLUMN_ALBUM
        elif type_ == blaconst.SELECT_BY_ALBUM_ARTISTS:
            column_id = COLUMN_ALBUM_ARTIST
        else:
            column_id = COLUMN_GENRE

        items = [model[path][0] for path in selected_paths]
        eval_ = BlaEval(column_id).eval
        values = set()
        for item in items:
            values.add(eval_(item.track).lower())
        if not values:
            return
        r = re.compile(
            r"^(%s)$" % "|".join(values), re.UNICODE | re.IGNORECASE)
        items = [row[0] for row in model if r.match(eval_(row[0].track))]
        paths = [row.path for row in model if row[0] in items]
        selection.unselect_all()
        select_path = selection.select_path
        map(select_path, paths)

    @classmethod
    def show_properties(cls, *args):
        model, paths = cls.__treeview.get_selection().get_selected_rows()
        uris = [model[path][0].uri for path in paths]
        if uris:
            BlaTagedit(uris)

    @classmethod
    def update_queue_positions(cls):
        model = cls.__treeview.get_model()

        # Update the position labels for our own treeview.
        for idx, row in enumerate(model):
            model[row.path][1] = idx+1

        # Invalidate the visible rows of the current playlists so the
        # position labels also get updated in playlists.
        BlaPlaylistManager.get_current_playlist().invalidate_visible_rows()

        # Calculate size and length of the queue and update the statusbar.
        cls.__size = cls.__length = 0
        for row in model:
            track = row[0].track
            cls.__size += track[FILESIZE]
            cls.__length += track[LENGTH]
        cls.__instance.emit("count_changed", blaconst.VIEW_QUEUE,
                            cls.queue_n_items())
        cls.__instance.update_statusbar()

    @classmethod
    def get_queue_positions(cls, item):
        model = cls.__treeview.get_model()
        return [row[1] for row in model if row[0] == item]

    @classmethod
    def queue_items(cls, items):
        if not items:
            return

        # If any of the items is not an instance of BlaListItem it means all of
        # the items are actually just URIs which stem from the library browser
        # and are not part of a playlist.
        if not isinstance(items[0], BlaListItem):
            items = map(BlaListItem, items)

        count = blaconst.QUEUE_MAX_ITEMS - cls.queue_n_items()
        cls.__add_items(items[:count], path=-1)

    @classmethod
    def remove_items(cls, items):
        # This is invoked by playlists who want to remove tracks from the
        # queue.
        model = cls.__treeview.get_model()
        for row in model:
            if row[0] in items:
                model.remove(row.iter)
        cls.update_queue_positions()

    @classmethod
    def get_queue(cls):
        queue = []
        playlists = BlaPlaylistManager.get_playlists()

        for row in cls.__treeview.get_model():
            item = row[0]
            playlist = item.playlist

            try:
                playlist_idx = playlists.index(playlist)
            except ValueError:
                item = (item.uri,)
            else:
                item = (playlist_idx,
                        playlist.get_path_from_item(item, all_=True))

            queue.append(item)

        return queue

    @classmethod
    def restore(cls, items):
        if not items:
            return

        items_ = []
        playlists = BlaPlaylistManager.get_playlists()

        for item in items:
            try:
                playlist_idx, path = item
            except ValueError:
                item = BlaListItem(item)
            else:
                item = playlists[playlist_idx].get_item_from_path(path)

            items_.append(item)

        cls.queue_items(items_)

    @classmethod
    def cut(cls, *args):
        cls.clipboard = cls.__get_items(remove=True)
        blagui.update_menu(blaconst.VIEW_QUEUE)

    @classmethod
    def copy(cls, *args):
        # We specifically don't create actual copies of items here as it's not
        # desired to have unique ones in the queue. Copied and pasted tracks
        # should still refer to the same BlaListItem instances which are part
        # (possibly part of a playlist).
        cls.clipboard = cls.__get_items(remove=False)
        blagui.update_menu(blaconst.VIEW_QUEUE)

    @classmethod
    def paste(cls, *args, **kwargs):
        cls.__add_items(items=cls.clipboard, select_rows=True)

    @classmethod
    def remove(cls, *args):
        cls.__get_items(remove=True)

    @classmethod
    def remove_duplicates(cls):
        unique = set()
        model = cls.__treeview.get_model()
        for row in model:
            uri = row[0].uri
            if uri not in unique:
                unique.add(uri)
            else:
                model.remove(row.iter)
        cls.update_queue_positions()

    @classmethod
    def remove_invalid_tracks(cls):
        model = cls.__treeview.get_model()
        isfile = os.path.isfile

        for row in model:
            uri = row[0].uri
            if not isfile(uri):
                model.remove(row.iter)
        cls.update_queue_positions()

    @classmethod
    def clear(cls):
        cls.__treeview.get_model().clear()
        cls.update_queue_positions()

    @classmethod
    def get_item(cls):
        model = cls.__treeview.get_model()
        iterator = model.get_iter_first()
        if iterator:
            item = model[iterator][0]
            model.remove(iterator)
            cls.update_queue_positions()
            return item
        return None

    @classmethod
    def queue_n_items(cls):
        return len(cls.__treeview.get_model())

class BlaPlaylist(gtk.VBox):
    __layout = (
        gobject.TYPE_PYOBJECT,  # BlaListItem instance
        gobject.TYPE_STRING     # Stock item id
    )
    __sort_parameters = None
    __fid = -1

    class History(object):
        def __init__(self, playlist):
            super(BlaPlaylist.History, self).__init__()
            self.__playlist = playlist
            self.__model = gtk.ListStore(gobject.TYPE_PYOBJECT)
            self.__iterator = None

        def add(self, identifier, choice):
            if choice == blaconst.TRACK_NEXT:
                insert_func = self.__model.insert_after
            else:
                insert_func = self.__model.insert_before
            self.__iterator = insert_func(self.__iterator, [identifier])

        def get(self, choice):
            if choice == blaconst.TRACK_NEXT:
                f = self.__model.iter_next
            elif choice == blaconst.TRACK_PREVIOUS:
                f = self.__iter_previous

            # Iterate through the model until a valid reference to an item
            # in the playlist is found.
            while True:
                try:
                    iterator = f(self.__iterator)
                except TypeError:
                    iterator = None

                if (iterator and
                    not self.__playlist.get_path_from_item(
                    self.__model[iterator][0], all_=True)):
                    self.__model.remove(iterator)
                    continue
                break

            if not iterator:
                item = None
            else:
                item = self.__model[iterator][0]
                self.__iterator = iterator

            return item

        def clear(self):
            self.__model.clear()
            self.__iterator = None

        def __iter_previous(self, iterator):
            path = self.__model.get_path(iterator)
            if path[0] > 0:
                return self.__model.get_iter(path[0]-1)
            return None

    def __init__(self, name="bla"):
        super(BlaPlaylist, self).__init__()

        self.__name = gtk.HBox()
        self.__name.pack_start(gtk.Label(name))
        self.__name.show_all()

        self.__lock = blautil.BlaLock()

        self.__history = BlaPlaylist.History(self)
        self.__mode = MODE_NORMAL

        self.__entry = gtk.Entry()
        self.__entry.set_icon_from_stock(
            gtk.ENTRY_ICON_SECONDARY, gtk.STOCK_CANCEL)
        self.__entry.connect(
            "icon_release", lambda *x: self.disable_search())
        def key_press_event(item, event):
            if blagui.is_accel(event, "Escape"):
                self.disable_search()
            return False
        self.__entry.connect("key_press_event", key_press_event)

        self.__regexp_button = gtk.ToggleButton(label="r\"\"")
        self.__regexp_button.set_tooltip_text(
            "Interpret search string as regular expression")

        button = gtk.Button()
        button.add(
            gtk.image_new_from_stock(gtk.STOCK_FIND, gtk.ICON_SIZE_BUTTON))
        button.connect("clicked", self.__filter)

        self.__hbox = gtk.HBox()
        self.__hbox.pack_start(self.__regexp_button, expand=False)
        self.__hbox.pack_start(self.__entry, expand=True)
        self.__hbox.pack_start(button, expand=False)
        self.__hbox.show_all()
        self.__hbox.set_visible(False)

        self.__treeview = BlaTreeView(view_id=blaconst.VIEW_PLAYLISTS)
        self.__treeview.connect_object(
            "sort_column", BlaPlaylist.sort, self)
        self.__treeview.connect("row_activated", self.play_item)
        self.__treeview.connect(
            "popup", popup, blaconst.VIEW_PLAYLISTS, self)
        self.__treeview.connect("key_press_event", self.__key_press_event)
        self.__treeview.connect("drag_data_get", self.__drag_data_get)
        self.__treeview.connect(
            "drag_data_received", self.__drag_data_recv)

        # DND between playlists (including one and the same playlist)
        self.__treeview.enable_model_drag_source(
            gtk.gdk.BUTTON1_MASK,
            [("tracks/playlist", gtk.TARGET_SAME_APP, 2)], gtk.gdk.ACTION_COPY)

        # Receive drag and drop
        self.__treeview.enable_model_drag_dest(
            [("tracks/library", gtk.TARGET_SAME_APP, 0),
             ("tracks/filesystem", gtk.TARGET_SAME_APP, 1),
             ("tracks/playlist", gtk.TARGET_SAME_APP, 2),
             ("text/uri-list", gtk.TARGET_OTHER_APP, 3)],
            gtk.gdk.ACTION_COPY)

        sw = blaguiutils.BlaScrolledWindow()
        sw.add(self.__treeview)

        self.clear()

        self.pack_start(self.__hbox, expand=False)
        self.pack_start(sw, expand=True)
        sw.show_all()

        update_columns(self.__treeview, view_id=blaconst.VIEW_PLAYLISTS)
        self.show()
        self.__entry.connect("activate", self.__filter)

    def __reduce__(self):
        return (self.__class__, (), self.__getstate__())

    def __getstate__(self):
        state = {
            "name": self.__name.children()[0].get_text(),
            "locked": self.__lock.locked(),
            "all_items": self.__all_items,
            "items": self.__items,
            "all_sorted": self.__all_sorted,
            "sorted": self.__sorted,
            "mode": self.__mode,
            "sort_parameters": self.__sort_parameters,
            "regexp": self.__regexp_button.get_active(),
            "query": self.__entry.get_text()
        }
        return state

    def __setstate__(self, state):
        name = state.get("name", "")
        if name:
            self.set_name(name)
        if state.get("locked", False):
            self.toggle_lock()
        self.__all_items = state.get("all_items", [])
        self.__items = state.get("items", [])
        self.__all_sorted = state.get("all_sorted", [])
        self.__sorted = state.get("sorted", [])
        self.__mode = state.get("mode", MODE_NORMAL)
        self.__sort_parameters = state.get("sort_parameters", None)

        self.__regexp_button.set_active(state.get("regexp", True))
        self.__entry.set_text(state.get("query", ""))
        if self.__entry.get_text():
            self.enable_search()

        self.__populate_model()

    def __populate_model(self, scroll_item=None, row_align=0.5,
                         selected_items=[]):
        if self.__mode & MODE_FILTERED:
            if self.__mode & MODE_SORTED:
                items = self.__sorted
            else:
                items = self.__items
        else:
            if self.__mode & MODE_SORTED:
                items = self.__all_sorted
            else:
                items = self.__all_items

        # Determine new playlist metadata for the statusbar.
        self.__length = sum([item.track[LENGTH] for item in items])
        self.__size = sum([item.track[FILESIZE] for item in items])

        # Fill and apply the new model.
        model = gtk.ListStore(*self.__layout)
        append = model.append
        for item in items:
            append([item, None])
        self.__treeview.set_model(model)

        # Select the appropriate rows and scroll to last known location.
        if selected_items is not None:
            selection = self.__treeview.get_selection()
            paths = self.get_paths_from_items(selected_items)
            select_path = selection.select_path
            map(select_path, paths)

        path = self.get_path_from_item(scroll_item)
        if path and model.get_iter_first():
            self.set_row(path, row_align=row_align, keep_selection=True,
                         set_cursor=False)

        # Set sort indicators if necessary
        try:
            column_id, sort_order, sort_indicator = self.__sort_parameters
        except TypeError:
            pass
        else:
            for column in self.__treeview.get_columns():
                if column.id == column_id:
                    break
            else:
                sort_order = None

            column.set_sort_indicator(sort_indicator)
            if sort_indicator:
                column.set_sort_order(sort_order)

        # Update the statusbar and the state icon in the playlist.
        self.update_icon()
        BlaPlaylistManager.update_statusbar()

    def __get_selection_and_row(self):
        row_align = 0.0
        selection = self.__treeview.get_selection()
        selected_paths = selection.get_selected_rows()[-1]

        # Get item of the row to scroll to.
        try:
            scroll_item = self.get_item_from_path(selected_paths[0])
        except IndexError:
            try:
                scroll_item = self.get_item_from_path(
                    self.__treeview.get_visible_range()[0])
            except (TypeError, IndexError):
                scroll_item = None
        else:
            column = self.__treeview.get_columns()[0]
            height = self.__treeview.get_allocation().height

            try:
                low, high = self.__treeview.get_visible_range()
                for path in selected_paths:
                    if low <= path <= high:
                        break
            except TypeError:
                row_align = 0.5
            else:
                row_align = (self.__treeview.get_cell_area(path, column)[1] /
                             float(height))

        # Get selected items
        try:
            selected_items = [self.get_item_from_path(p)
                              for path in selected_paths]
        except IndexError:
            selected_items = None

        if not (0.0 <= row_align <= 1.0):
            row_align = 0.0
        return scroll_item, row_align, selected_items

    def __get_current_items(self):
        if self.__mode & MODE_FILTERED:
            if self.__mode & MODE_SORTED:
                items = self.__sorted
            else:
                items = self.__items
        else:
            if self.__mode & MODE_SORTED:
                items = self.__all_sorted
            else:
                items = self.__all_items
        return items

    def __freeze_treeview(self):
        self.__treeview.freeze_notify()
        self.__treeview.freeze_child_notify()
        return self.__treeview.get_model()

    def __thaw_treeview(self):
        self.__treeview.thaw_child_notify()
        self.__treeview.thaw_notify()

    def __filter_parameters_changed(self, item):
        if blacfg.getboolean("general", "search.after.timeout"):
            try:
                gobject.source_remove(self.__fid)
            except AttributeError:
                pass
            def activate():
                self.__entry.activate()
                return False
            self.__fid = gobject.timeout_add(500, activate)

    def __filter(self, *args):
        scroll_item, row_align, selected_items = self.__get_selection_and_row()

        filter_string = self.__entry.get_text().strip()
        if filter_string:
            self.__mode |= MODE_FILTERED
            query = BlaQuery(
                filter_string, self.__regexp_button.get_active()).query
            if self.__mode & MODE_SORTED:
                self.__sorted = filter(query, self.__all_sorted)
            else:
                self.__items = filter(query, self.__all_items)
        else:
            self.__mode ^= MODE_FILTERED
            if self.__mode & MODE_SORTED:
                self.__sorted = list(self.__all_sorted)
            else:
                self.__items = list(self.__all_items)

        self.__populate_model(scroll_item, row_align, selected_items)

    def __drag_data_get(self, treeview, drag_context, selection_data, info,
                        time):
        idx = BlaPlaylistManager.get_playlist_index(self)
        data = pickle.dumps((treeview.get_selection().get_selected_rows()[-1],
                            idx), pickle.HIGHEST_PROTOCOL)
        selection_data.set("", 8, data)

    def __drag_data_recv(self, treeview, drag_context, x, y, selection_data,
                         info, time):
        if not self.modification_allowed():
            return

        data = None
        treeview.grab_focus()
        drop_info = treeview.get_dest_row_at_pos(x, y)

        # DND from the library browser
        if info == 0:
            uris = pickle.loads(selection_data.data)
            items = create_items_from_uris(uris)

        # DND between playlists
        elif info == 2:
            paths, idx = pickle.loads(selection_data.data)

            if drop_info:
                path, pos = drop_info
                item = self.get_item_from_path(path)
                if (path in paths and
                    idx == BlaPlaylistManager.get_playlist_index(self)):
                    return

            playlist = BlaPlaylistManager.get_nth_playlist(idx)
            items = playlist.get_items(paths=paths, remove=True)
            if drop_info:
                path = self.get_path_from_item(item)
                drop_info = (path, pos)

        # DND from an external location or the filesystem browser
        elif info in [1, 3]:
            uris = selection_data.data.strip("\n\r\x00")
            resolve_uri = blautil.resolve_uri
            uris = map(resolve_uri, uris.split())
            uris = library.parse_ool_uris(uris)
            items = create_items_from_uris(uris)

        # FIXME: if we don't add anything here GTK issues an assertion warning
        if items:
            self.add_items(items, drop_info=drop_info, select_rows=True)

    def __key_press_event(self, treeview, event):
        def delete():
            items = self.get_items(remove=True)
            if BlaPlaylistManager.current in items:
                BlaPlaylistManager.current = None

        is_accel = blagui.is_accel
        accels = [
            ("Delete", delete),
            ("Q", lambda: self.send_to_queue()),
            ("R", lambda: self.remove_from_queue(self.__treeview)),
            ("Escape", self.disable_search),
            ("<Alt>Return", self.show_properties)
        ]
        for accel, callback in accels:
            if is_accel(event, accel):
                callback()
                break
        return False

    def get_name(self, as_text=False):
        if not as_text:
            return self.__name
        return self.__name.children()[0].get_text()

    def set_name(self, name):
        self.__name.children()[0].set_text(name)

    def modification_allowed(self, check_filter_state=True):
        if self.__lock.locked():
            text = "The playlist is locked"
            secondary_text = "Unlock it first to modify its contents."
        elif check_filter_state and self.__mode & MODE_FILTERED:
            text = "Error"
            secondary_text = "Cannot modify filtered playlists."
        else:
            text = secondary_text = ""

        if text and secondary_text:
            # Opening an error dialog after a double-click onto a row in the
            # library browser has a weird effect in that the treeview will
            # initiate a DND operation of the row once the dialog is destroyed.
            # Handling the dialog with gobject.idle_add resolves the issue.
            gobject.idle_add(blaguiutils.error_dialog, text, secondary_text)
            return False
        return True

    def clear(self):
        if not self.modification_allowed(check_filter_state=False):
            return

        self.__treeview.freeze_notify()
        self.__treeview.freeze_child_notify()
        model = self.__treeview.get_model()
        self.disable_search()

        self.__length = 0
        self.__size = 0
        self.__history.clear()
        self.__all_items = []   # Unfiltered, unsorted tracks
        self.__all_sorted = []  # Unfiltered, sorted tracks
        self.__items = []       # Visible tracks when unsorted
        self.__sorted = []      # Visible tracks when sorted
        self.__sort_parameters = None
        for column in self.__treeview.get_columns():
            column.set_sort_indicator(False)
        self.__mode = MODE_NORMAL

        self.__treeview.set_model(gtk.ListStore(*self.__layout))
        self.__treeview.thaw_child_notify()
        self.__treeview.thaw_notify()

    def get_path_from_item(self, item, all_=False):
        if self.__mode & MODE_FILTERED and not all_:
            if self.__mode & MODE_SORTED:
                items = self.__sorted
            else:
                items = self.__items
        else:
            if self.__mode & MODE_SORTED:
                items = self.__all_sorted
            else:
                items = self.__all_items
        try:
            return (items.index(item),)
        except ValueError:
            return None

    def get_paths_from_items(self, items):
        items_ = self.__get_current_items()
        paths = []
        for item in items:
            try:
                paths.append((items_.index(item),))
            except ValueError:
                pass
        return paths

    def get_item_from_path(self, path):
        if self.__mode & MODE_FILTERED:
            if self.__mode & MODE_SORTED:
                items = self.__sorted
            else:
                items = self.__items
        else:
            if self.__mode & MODE_SORTED:
                items = self.__all_sorted
            else:
                items = self.__all_items
        try:
            return items[path[0]]
        except (TypeError, IndexError):
            return None

    def get_items_from_paths(self, paths):
        items_ = self.__get_current_items()
        items = []
        for path in paths:
            try:
                items.append(items_[path[0]])
            except (TypeError, IndexError):
                pass
        return items

    def select(self, type_):
        selection = self.__treeview.get_selection()
        selected_paths = selection.get_selected_rows()[-1]

        if type_ == blaconst.SELECT_ALL:
            selection.select_all()
            return
        elif type_ == blaconst.SELECT_COMPLEMENT:
            selected_paths = set(selected_paths)
            paths = [(p,) for p in xrange(len(self.__treeview.get_model()))]
            paths = set(paths)
            paths.difference_update(selected_paths)
            selection.unselect_all()
            select_path = selection.select_path
            map(select_path, paths)
            return
        elif type_ == blaconst.SELECT_BY_ARTISTS:
            column_id = COLUMN_ARTIST
        elif type_ == blaconst.SELECT_BY_ALBUMS:
            column_id = COLUMN_ALBUM
        elif type_ == blaconst.SELECT_BY_ALBUM_ARTISTS:
            column_id = COLUMN_ALBUM_ARTIST
        else:
            column_id = COLUMN_GENRE

        # Assemble a set of strings we want to match.
        items = self.get_items_from_paths(selected_paths)
        eval_ = BlaEval(column_id).eval
        values = set()
        for item in items:
            values.add(eval_(item.track).lower())
        if not values:
            return

        # Filter currently displayed items
        r = re.compile(r"^(%s)$" % "|".join(values),
                       re.UNICODE | re.IGNORECASE)
        items = [item for item in self.__get_current_items()
                 if r.match(eval_(item.track))]
        paths = self.get_paths_from_items(items)
        selection.unselect_all()
        select_path = selection.select_path
        map(select_path, paths)

    def new_playlist(self, type_):
        paths = self.__treeview.get_selection().get_selected_rows()[-1]
        items = self.get_items_from_paths(paths)

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
            values = set()
            for item in items:
                values.add(eval_(item.track).lower())
            if not values:
                return

            r = re.compile(r"^(%s)$" % "|".join(values),
                           re.UNICODE | re.IGNORECASE)
            items = [copy(item) for item in self.__get_current_items()
                     if r.match(eval_(item.track))]

        playlist = BlaPlaylistManager.add_playlist(focus=True)
        playlist.add_items(items=items)

    def add_items(self, items, drop_info=None, select_rows=False):
        if not items:
            return

        # Update the playlist reference of the new items.
        all_items = self.__all_items
        for idx, item in enumerate(items):
            # When a copied item is pasted into the same playlist multiple
            # times make sure to always get a new id().
            if item.playlist == self:
                items[idx] = copy(item)
            item.playlist = self

        # If drop_info is -1 insert at the cursor or at the end of the playlist
        # if nothing is selected.
        if drop_info == -1:
            try:
                # The get_cursor() method might still return something even if
                # the selection in a treeview is empty. In this case we also
                # want to append tracks to the playlist and thus raise a
                # TypeError here to force path to be None.
                if not self.__treeview.get_selection().get_selected_rows()[-1]:
                    raise TypeError
                path, column = self.__treeview.get_cursor()
            except TypeError:
                drop_info = None
            else:
                drop_info = (path, gtk.TREE_VIEW_DROP_BEFORE)

        reverse = False
        model = self.__freeze_treeview()
        iterator = None
        if drop_info:
            path, pos = drop_info
            iterator = model.get_iter(path)

            if pos in [gtk.TREE_VIEW_DROP_BEFORE,
                       gtk.TREE_VIEW_DROP_INTO_OR_BEFORE]:
                insert_func = model.insert_before
                reverse = True
            else:
                path = (path[0]+1,)
                insert_func = model.insert_after
        else:
            path = (len(model),)
            append = model.append
            def insert_func(iterator, item):
                append(item)

        # Insert new items into our book-keeping lists.
        self.insert(items, drop_info)

        scroll_item = items[-1]
        if reverse:
            items.reverse()

        for item in items:
            iterator = insert_func(iterator, [item, None])

        # Insertion is likely to destroy the sort order so remove any sort
        # indicators.
        for column in self.__treeview.get_columns():
            column.set_sort_indicator(False)

        # Select added rows if requested
        if select_rows:
            selection = self.__treeview.get_selection()
            selection.unselect_all()
            selection.select_range(path, (path[0] + len(items) - 1,))
            self.set_row(self.get_path_from_item(scroll_item), row_align=1.0,
                         keep_selection=True)

        self.__thaw_treeview()
        BlaPlaylistManager.update_statusbar()
        self.update_icon()

    def insert(self, items, drop_info):
        # Due to the way playlist contents are handled to speed up filtering
        # and sorting, dealing with track insertion into our book-keeping lists
        # is a rather fiddly task.

        if self.__mode & MODE_SORTED:
            list_ = self.__all_sorted
        else:
            list_ = self.__all_items

        if drop_info:
            path, pos = drop_info
            if pos in [gtk.TREE_VIEW_DROP_BEFORE,
                       gtk.TREE_VIEW_DROP_INTO_OR_BEFORE]:
                starting_point = path[0]
            else:
                starting_point = path[0] + 1
        else:
            starting_point = len(list_)

        for idx, item in enumerate(items):
            list_.insert(starting_point + idx, item)

        if self.__mode & MODE_SORTED:
            if starting_point > 0:
                item = list_[starting_point - 1]
                starting_point = self.__all_items.index(item) + 1
            else:
                item = list_[starting_point + 1]
                starting_point = self.__all_items.index(item)

            for idx, item in enumerate(items):
                self.__all_items.insert(starting_point + idx, item)

        # Update playlist statistics
        self.__length += sum(
            [item.track[LENGTH] for item in items])
        self.__size += sum(
            [item.track[FILESIZE] for item in items])

    def get_items(self, remove=False, paths=None):
        if remove and not self.modification_allowed():
            return []

        items = []

        # If paths is not given return the currently selected rows.
        if paths is None:
            paths = self.__treeview.get_selection().get_selected_rows()[-1]

        if paths:
            if isinstance(paths, tuple):
                items, paths = paths
            else:
                items = self.get_items_from_paths(paths)

            if remove:
                self.__length -= sum(
                    [item.track[LENGTH] for item in items])
                self.__size -= sum(
                    [item.track[FILESIZE] for item in items])

                # Remove the rows from the model.
                model = self.__freeze_treeview()
                get_iter = model.get_iter
                iterators = map(get_iter, paths)
                remove = model.remove
                map(remove, iterators)
                self.__thaw_treeview()

                # Remove items from the book-keeping lists.
                lists = [self.__all_items]
                if self.__mode & MODE_FILTERED:
                    lists.append(self.__items)
                    if self.__mode & MODE_SORTED:
                        lists.append(self.__sorted)
                if self.__mode & MODE_SORTED:
                    lists.append(self.__all_sorted)

                for list_ in lists:
                    remove = list_.remove
                    map(remove, items)

                BlaPlaylistManager.update_statusbar()
        return items

    def remove_duplicates(self):
        def remove_duplicates():
            items = self.__get_current_items()
            scroll_item, row_align, selected_items = \
                self.__get_selection_and_row()

            paths = self.__treeview.get_selection().get_selected_rows()[-1]
            selected_items = self.get_items_from_paths(paths)

            # Determine unique tracks
            unique_items = blautil.BlaOrderedSet()
            unique_uris = blautil.BlaOrderedSet()
            for item in items:
                if item.uri not in unique_uris:
                    unique_items.add(item)
                    unique_uris.add(item.uri)
            unique_items = list(unique_items)
            unique_uris = list(unique_uris)

            if self.__mode & MODE_FILTERED:
                if self.__mode & MODE_SORTED:
                    self.__sorted = unique_items
                else:
                    self.__items = unique_items
            else:
                if self.__mode & MODE_SORTED:
                    self.__all_sorted = unique_items
                else:
                    self.__all_items = unique_items

            self.__populate_model(scroll_item, row_align, selected_items)
            self.__treeview.set_sensitive(True)

        self.__treeview.set_sensitive(False)
        remove_duplicates()

    def remove_invalid_tracks(self):
        # TODO
        def remove_invalid_tracks():
            if self.__mode & MODE_FILTERED:
                if self.__mode & MODE_SORTED:
                    items = self.__sorted
                else:
                    items = self.__items
            else:
                if self.__mode & MODE_SORTED:
                    items = self.__all_sorted
                else:
                    items = self.__all_items

            # Create a copy to leave the referenced list unchanged.
            items_copy = list(items)

            isfile = os.path.isfile
            for idx, item in enumerate(items):
                uri = item.uri
                if not isfile(uri):
                    items_copy.remove(item)
                if idx % 25 == 0:
                    yield True

            paths = self.__treeview.get_selection().get_selected_rows()[-1]
            get_item_from_path = self.get_item_from_path
            selected_items = []
            for idx, path in enumerate(paths):
                selected_items.append(get_item_from_path(path))
                if idx % 25 == 0:
                    yield True

            self.__populate_model(items_copy, selected_items)
            self.__treeview.set_sensitive(True)
            yield False

        self.__treeview.set_sensitive(False)
        p = remove_invalid_tracks()
        gobject.idle_add(p.next)

    def toggle_lock(self):
        if self.__lock.locked():
            self.__lock.release()
            self.__name.remove(self.__name.children()[-1])
        else:
            self.__lock.acquire()

            # Create a lock image and resize it so it fits the text size.
            label = self.__name.children()[0]
            width, height = label.create_pango_layout(
                label.get_text()).get_pixel_size()
            pixbuf = self.render_icon(
                gtk.STOCK_DIALOG_AUTHENTICATION, gtk.ICON_SIZE_MENU)
            pixbuf = pixbuf.scale_simple(
                width, height, gtk.gdk.INTERP_BILINEAR)
            image = gtk.image_new_from_pixbuf(pixbuf)
            self.__name.pack_start(image)
            self.__name.show_all()

        BlaPlaylistManager.update_playlist_lock_state()

    def locked(self):
        return self.__lock.locked()

    def enable_search(self):
        self.__entry.grab_focus()
        self.__cid = self.__entry.connect(
            "changed", self.__filter_parameters_changed)
        self.__hbox.set_visible(True)

    def disable_search(self):
        self.__hbox.set_visible(False)
        try:
            if self.__entry.handler_is_connected(self.__cid):
                self.__entry.disconnect(self.__cid)
        except AttributeError:
            pass
        text = self.__entry.get_text()
        self.__entry.delete_text(0, -1)
        if text:
            self.__entry.activate()

    def sort(self, column_id, sort_order, scroll=False):
        for column in self.__treeview.get_columns():
            if column.id == column_id:
                break
        else:
            sort_order = None

        scroll_item, row_align, selected_items = self.__get_selection_and_row()

        items = (self.__items if self.__mode & MODE_FILTERED else
                 self.__all_items)
        if sort_order is None:
            self.__mode ^= MODE_SORTED
            sort_indicator = False
        else:
            self.__mode |= MODE_SORTED
            sort_indicator = True

            if sort_order == gtk.SORT_DESCENDING:
                reverse = True
            elif sort_order == gtk.SORT_ASCENDING:
                reverse = False
            eval_ = BlaEval(column_id).eval

            self.__all_sorted = sorted(
                self.__all_items,
                key=lambda item: eval_(item.track).lower(),
                reverse=reverse)
            items = sorted(
                items,
                key=lambda item: eval_(item.track).lower(),
                reverse=reverse)
            self.__sorted = items

        if sort_order is not None:
            self.__sort_parameters = (column_id, sort_order, sort_indicator)
        else:
            self.__sort_parameters = None

        self.__populate_model(scroll_item, row_align, selected_items)

    def get_uris(self, all_=False):
        if self.__mode & MODE_FILTERED and not all_:
            if self.__mode & MODE_SORTED:
                items = self.__sorted
            else:
                items = self.__items
        else:
            if self.__mode & MODE_SORTED:
                items = self.__all_sorted
            else:
                items = self.__all_items

        return [item.uri for item in items]

    def update_uris(self, uris):
        for item in self.__all_items:
            try:
                new_uri = uris[item.uri]
            except KeyError:
                pass
            else:
                item.uri = new_uri

    def get_item(self, choice=blaconst.TRACK_PLAY, force_advance=True):
        def get_random(old=None):
            idx_max = len(model) - 1
            if idx_max < 0:
                return None
            item = model[randint(0, idx_max)][0]
            if old is not None and idx_max > 0:
                while item == old:
                    item = model[randint(0, idx_max)][0]
            return item

        order = blacfg.getint("general", "play.order")
        model = self.__treeview.get_model()

        # Remove the playing icon from the old row.
        current = BlaPlaylistManager.current
        path = self.get_path_from_item(current)
        if path is not None:
            model[path][1] = None

        # If there are no tracks in the playlist, return.
        if not model.get_iter_first():
            return None

        item = None

        # Play the last active track (this applies to ORDER_REPEAT, too).
        if ((choice == blaconst.TRACK_PLAY or
            (order == blaconst.ORDER_REPEAT and not force_advance)) and
            current is not None):
            item = current
            self.__history.add(item, choice)

        # Play request, but we didn't play a track from this playlist yet.
        elif choice == blaconst.TRACK_PLAY:
            if order == blaconst.ORDER_SHUFFLE:
                item = get_random()
                self.__history.add(item, choice)
            else:
                item = model[0][0]

        elif choice == blaconst.TRACK_RANDOM:
            item = get_random()
            self.__history.add(item, blaconst.TRACK_NEXT)

        # This is either TRACK_NEXT or TRACK_PREVIOUS with ORDER_SHUFFLE.
        elif order == blaconst.ORDER_SHUFFLE:
            item = self.__history.get(choice)
            if item is None:
                item = get_random(current)
                self.__history.add(item, choice)

        # This is either TRACK_NEXT or TRACK_PREVIOUS with ORDER_NORMAL.
        else:
            path = self.get_path_from_item(current)
            if path is None:
                path = (0,)
            else:
                if choice == blaconst.TRACK_NEXT:
                    path = (path[0]+1,)
                else:
                    path = (path[0]-1,) if path[0] > 0 else None

            item = self.get_item_from_path(path)

        return item

    def get_playlist_stats(self):
        items = (self.__items if self.__mode & MODE_FILTERED else
                 self.__all_items)
        return (len(items), self.__size, self.__length)

    def update_icon(self, clear=False):
        model = self.__treeview.get_model()
        path = self.get_path_from_item(BlaPlaylistManager.current)
        state = player.get_state()

        if clear or state == blaconst.STATE_STOPPED:
            stock = None
        elif state == blaconst.STATE_PLAYING:
            stock = gtk.STOCK_MEDIA_PLAY
        elif blaconst.STATE_PAUSED:
            stock = gtk.STOCK_MEDIA_PAUSE
        try:
            model[path][1] = stock
        except TypeError:
            pass

    def invalidate_visible_rows(self):
        try:
            low, high = self.__treeview.get_visible_range()
        except TypeError:
            pass
        else:
            model = self.__treeview.get_model()
            get_iter = model.get_iter
            row_changed = model.row_changed
            for path in xrange(low[0], high[0]+1):
                row_changed(path, get_iter(path))

    def play_item(self, treeview, path, column=None):
        model = self.__treeview.get_model()
        current = BlaPlaylistManager.current
        item = self.get_item_from_path(path)
        order = blacfg.getint("general", "play.order")
        if (order == blaconst.ORDER_SHUFFLE and
            current != item and current is not None):
            self.__history.add(item, blaconst.TRACK_NEXT)
        BlaPlaylistManager.play_item(item)

    def add_selection_to_playlist(self, playlist, move):
        if not playlist.modification_allowed():
            return

        items = self.get_items(remove=move)
        if not items:
            return
        if not move:
            items = map(copy, items)
        playlist.add_items(items=items, select_rows=True)
        BlaPlaylistManager.focus_playlist(playlist)

    def send_to_queue(self):
        queue_n_items = BlaQueue.queue_n_items()
        if queue_n_items >= blaconst.QUEUE_MAX_ITEMS:
            return

        count = blaconst.QUEUE_MAX_ITEMS - queue_n_items
        model, selection = self.__treeview.get_selection().get_selected_rows()
        BlaQueue.queue_items([model[p][0] for p in selection[:count]])

    def remove_from_queue(self, treeview):
        model, selection = treeview.get_selection().get_selected_rows()
        BlaQueue.remove_items([model[p][0] for p in selection])

    def jump_to_playing_track(self):
        current = BlaPlaylistManager.current
        try:
            if current is None:
                raise KeyError
            if current.uri != player.get_track().uri:
                raise KeyError
        except KeyError:
            return
        self.set_row(self.get_path_from_item(current))

    def set_row(self, path, row_align=0.5, keep_selection=False,
                set_cursor=True):
        # Wrap the actual heavy lifting in gobject.idle_add. If we decorate the
        # instance method itself we can't use kwargs anymore which is rather
        # annoying for this particular method.
        @blautil.idle
        def set_row():
            try:
                low, high = self.__treeview.get_visible_range()
            except TypeError:
                low, high = None, None
            if low is None or not (low <= path <= high):
                self.__treeview.scroll_to_cell(
                    path, use_align=True, row_align=row_align)

            selection = self.__treeview.get_selection()
            if keep_selection:
                selected_rows = selection.get_selected_rows()[-1]
            else:
                selected_rows = []
            if set_cursor:
                self.__treeview.set_cursor(path)
            if selected_rows:
                select_path = selection.select_path
                map(select_path, selected_rows)

        if path:
            set_row()

    def show_properties(self):
        uris = [item.uri for item in self.get_items(remove=False)]
        if uris:
            BlaTagedit(uris)

class BlaPlaylistManager(gtk.Notebook):
    __gsignals__ = {
        "play_track": blautil.signal(1),
        "count_changed": blautil.signal(2)
    }

    __instance = None   # Instance of BlaPlaylist needed for classmethods
    current = None      # Reference to the currently active playlist
    clipboard = []      # List of items after a cut/copy operation

    @property
    def name(self):
        return "Playlists"

    def __init__(self):
        super(BlaPlaylistManager, self).__init__()
        type(self).__instance = self

        self.set_scrollable(True)
        targets = [
            ("tracks/library", gtk.TARGET_SAME_APP, 0),
            ("tracks/filesystem", gtk.TARGET_SAME_APP, 1),
            ("tracks/playlist", gtk.TARGET_SAME_APP, 2),
            ("text/uri-list", gtk.TARGET_SAME_APP, 3)
        ]
        self.drag_dest_set(gtk.DEST_DEFAULT_MOTION | gtk.DEST_DEFAULT_DROP,
                           targets, gtk.gdk.ACTION_COPY)

        # Lock/Unlock playlist button
        self.__lock_button = gtk.Button()
        self.__lock_button.set_relief(gtk.RELIEF_NONE)
        self.__lock_button.set_focus_on_click(False)
        self.__lock_button.add(
            gtk.image_new_from_stock(gtk.STOCK_DIALOG_AUTHENTICATION,
            gtk.ICON_SIZE_MENU))
        style = gtk.RcStyle()
        style.xthickness = style.ythickness = 0
        self.__lock_button.modify_style(style)
        self.__lock_button.connect("clicked", self.toggle_lock_playlist)
        self.__lock_button.show_all()
        self.set_action_widget(self.__lock_button, gtk.PACK_END)

        def page_num_changed(*args):
            self.emit("count_changed", blaconst.VIEW_PLAYLISTS,
                      self.get_n_pages())
        self.connect("page_added", page_num_changed)
        self.connect("page_removed", page_num_changed)
        def switch_page(*args):
            playlist = self.get_nth_page(args[-1])
            self.update_playlist_lock_state()
            self.update_statusbar(playlist)
        self.connect_after("switch_page", switch_page)

        self.connect("button_press_event", self.__button_press_event)
        self.connect("key_press_event", self.__key_press_event)
        self.connect("play_track", player.play_track)
        self.connect_object("drag_data_received",
                            BlaPlaylistManager.__drag_data_recv, self)

        def state_changed(player):
            state = player.get_state()
            playlist = self.get_active_playlist()
            if playlist:
                playlist.update_icon()
            # If the state changed to STATE_STOPPED and we just played a song
            # that was in the queue but which was not part of a playlist,
            # overwrite cls.current so we'll try to get a new song from a
            # playlist or the queue when we request to start playing again.
            if (state == blaconst.STATE_STOPPED and self.current and
                self.current.playlist is None):
                type(self).current = None
        player.connect("state_changed", state_changed)
        player.connect_object("get_track", BlaPlaylistManager.get_track, self)

        self.show_all()
        self.show_tabs(blacfg.getboolean("general", "playlist.tabs"))

        blaplay.bla.register_for_cleanup(self)

    def __call__(self):
        self.save()

    def __drag_data_recv(self, drag_context, x, y, selection_data, info, time):
        resolve = select = False

        # DND from the library browser
        if info == 0:
            items = pickle.loads(selection_data.data)

        # DND from another playlist
        elif info == 2:
            paths, idx = pickle.loads(selection_data.data)
            playlist = self.get_nth_page(idx)
            items = playlist.get_items(paths=paths, remove=True)
            select = True

        # DND from the filebrowser or an external source
        elif info in [1, 3]:
            uris = selection_data.data.strip("\n\r\x00")
            resolve_uri = blautil.resolve_uri
            items = map(resolve_uri, uris.split())
            resolve = True

        self.send_to_new_playlist(items, resolve=resolve, select=select)

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
        if blagui.is_accel(event, "<Ctrl>X"):
            self.cut()
        elif blagui.is_accel(event, "<Ctrl>C"):
            self.copy()
        elif blagui.is_accel(event, "<Ctrl>V"):
            self.paste()

        # TODO: handle these two by global accelerators
        elif blagui.is_accel(event, "<Ctrl>T"):
            self.add_playlist(focus=True)
        elif blagui.is_accel(event, "<Ctrl>W"):
            self.remove_playlist(self.get_current_playlist())

        elif blagui.is_accel(event, "Escape"):
            self.get_current_playlist().disable_search()
        return False

    def __query_name(self, title, default=""):
        diag = gtk.Dialog(title=title, flags=gtk.DIALOG_DESTROY_WITH_PARENT |
                          gtk.DIALOG_MODAL, buttons=(gtk.STOCK_CANCEL,
                          gtk.RESPONSE_CANCEL, gtk.STOCK_OK, gtk.RESPONSE_OK))
        diag.set_resizable(False)

        vbox = gtk.VBox(spacing=5)
        vbox.set_border_width(10)
        item = gtk.Entry()
        item.set_text(default)
        item.connect("activate", lambda *x: diag.response(gtk.RESPONSE_OK))
        label = gtk.Label("Title:")
        label.set_alignment(xalign=0.0, yalign=0.5)
        vbox.pack_start(label)
        vbox.pack_start(item)
        diag.vbox.pack_start(vbox)
        diag.show_all()
        response = diag.run()

        name = item.get_text() if response == gtk.RESPONSE_OK else ""
        diag.destroy()
        return name

    def __rename_playlist(self, playlist):
        name = playlist.get_name(as_text=True)
        new_name = self.__query_name("Rename playlist", name)
        if new_name:
            playlist.set_name(new_name)

    def __open_popup(self, playlist, button, time, all_options=True):
        menu = gtk.Menu()

        items = [
            ("Rename playlist", lambda *x: self.__rename_playlist(playlist)),
            ("Remove playlist", lambda *x: self.remove_playlist(playlist)),
            ("Clear playlist", lambda *x: playlist.clear())
        ]

        for label, callback in items:
            m = gtk.MenuItem(label)
            m.connect("activate", callback)
            if not all_options:
                m.set_sensitive(False)
            menu.append(m)

        menu.append(gtk.SeparatorMenuItem())

        try:
            label = "%s playlist" % ("Unlock" if playlist.locked() else "Lock")
        except AttributeError:
            pass
        else:
            m = gtk.MenuItem(label)
            m.connect("activate", lambda *x: playlist.toggle_lock())
            menu.append(m)

            menu.append(gtk.SeparatorMenuItem())

        m = gtk.MenuItem("Add new playlist...")
        m.connect("activate",
                  lambda *x: self.add_playlist(query_name=True, focus=True))
        menu.append(m)

        menu.show_all()
        menu.popup(None, None, None, button, time)

    def __save_m3u(self, uris, path, relative):
        with open(path, "w") as f:
            f.write("#EXTM3U\n")
            for uri in uris:
                track = library[uri]
                length = track[LENGTH]
                artist = track[ARTIST]
                title = track[TITLE]
                if artist:
                    header = "%s - %s" % (artist, title)
                else:
                    header = title
                if relative:
                    uri = os.path.basename(uri)
                f.write("#EXTINF:%d, %s\n%s\n" % (length, header, uri))

    def __parse_m3u(self, path):
        directory = os.path.dirname(path)
        uris = []
        try:
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line.startswith("#"):
                        if not os.path.isabs(line):
                            line = os.path.join(directory, line)
                        uris.append(line)
        except IOError:
            blaguiutils.error_dialog("Failed to parse playlist \"%s\"" % path)
            uris = None

        return uris

    def __save_pls(self, uris, path, relative):
        try:
            with open(path, "w") as f:
                f.write("[playlist]\n")
                for idx, uri in enumerate(uris):
                    track = library[uri]
                    idx += 1
                    if relative:
                        uri = os.path.basename(uri)
                    text = "File%d=%s\nTitle%d=%s\nLength%d=%s\n" % (
                        idx, uri, idx, track[TITLE], idx, track[LENGTH])
                    f.write(text)
                f.write("NumberOfEntries=%d\nVersion=2\n" % len(uris))

        except IOError:
            blaguiutils.error_dialog("Failed to save playlist \"%s\"" % path)

    def __parse_pls(self, path):
        directory = os.path.dirname(path)
        uris = []
        try:
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line.lower().startswith("file"):
                        try:
                            line = line[line.index("=")+1:].strip()
                        except ValueError:
                            pass
                        else:
                            if not os.path.isabs(line):
                                line = os.path.join(directory, line)
                            uris.append(line)
        except IOError:
            blaguiutils.error_dialog("Failed to parse playlist \"%s\"" % path)
            uris = None

        return uris

    def __save_xspf(self, uris, path, name):
        # Improved version of exaile's implementation
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
                        "xmlns=\"http://xspf.org/ns/0/\">\n")
                f.write("  <title>%s</title>\n" % name)
                f.write("  <trackList>\n")
                for uri in uris:
                    track = library[uri]
                    f.write("    <track>\n")
                    for element, identifier in tags.iteritems():
                        value = xml_escape(track[identifier])
                        if not value:
                            continue
                        f.write("      <%s>%s</%s>\n" % (element, value,
                                                         element))
                    f.write("      <location>file://%s</location>\n" %
                            urllib.quote(uri))
                    f.write("    </track>\n")
                f.write("  </trackList>\n")
                f.write("</playlist>\n")

        except IOError:
            blaguiutils.error_dialog("Failed to save playlist \"%s\"" % path)

    def __parse_xspf(self, path):
        # Improved version of exaile's implementation. This method is merely a
        # stub to retrieve URIs and the playlist name. We completely ignore any
        # other metadata tags and just feed each URI to our track parser.

        name, uris = "", []
        try:
            with open(path, "r") as f:
                tree = ETree.ElementTree(None, f)
                ns = "{http://xspf.org/ns/0/}"
                nodes = tree.find("%strackList" % ns).findall("%strack" % ns)
                name = tree.find("%stitle" % ns)
                if name is not None:
                    name = name.text.strip()
                for node in nodes:
                    uris.append(node.find("%slocation" % ns).text.strip())

        except IOError:
            blaguiutils.error_dialog("Failed to parse playlist \"%s\"" % path)
            uris = None

        return name, uris

    @classmethod
    def update_playlist_lock_state(cls):
        playlist = cls.get_current_playlist()
        try:
            label = "%s playlist" % ("Unlock" if playlist.locked() else "Lock")
        except AttributeError:
            return
        cls.__instance.__lock_button.set_tooltip_text(label)
        blagui.uimanager.get_widget("/Menu/Edit/LockUnlockPlaylist").set_label(
            label)

    @classmethod
    def get_active_playlist(cls):
        try:
            playlist = cls.current.playlist
        except AttributeError:
            playlist = None
        return playlist

    @classmethod
    def get_current_playlist(cls):
        self_ = cls.__instance
        return self_.get_nth_page(self_.get_current_page())

    @classmethod
    def get_playlist_name(cls, playlist):
        return cls.__instance.get_tab_label(playlist).get_text()

    @classmethod
    def enable_search(cls):
        if blacfg.getint("general", "view") == blaconst.VIEW_PLAYLISTS:
            cls.get_current_playlist().enable_search()

    @classmethod
    def open_playlist(cls, path):
        name = os.path.basename(blautil.toss_extension(path))
        ext = blautil.get_extension(path).lower()

        if ext == "m3u":
            uris = cls.__instance.__parse_m3u(path)
        elif ext == "pls":
            uris = cls.__instance.__parse_pls(path)
        elif ext == "xspf":
            name, uris = cls.__instance.__parse_xspf(path)
        else:
            blaguiutils.error_dialog(
                "Failed to open playlist \"%s\"" % path,
                "Only M3U, PLS, and XSPF playlists are supported.")
            return False
        if uris is None:
            return False

        resolve_uri = blautil.resolve_uri
        uris = library.parse_ool_uris(map(resolve_uri, uris))
        if uris is None:
            return False
        playlist = cls.__instance.add_playlist(focus=True, name=name)
        playlist.add_tracks(uris=uris)
        return True

    @classmethod
    def save(cls, path=None, type_="m3u", relative=False):
        @blautil.thread
        def save(path, type_):
            name = cls.__instance.get_tab_label_text(
                cls.get_current_playlist())
            uris = cls.get_current_playlist().get_uris()

            ext = blautil.get_extension(path)
            if ext.lower() != type_:
                path = "%s.%s" % (path, type_)

            if type_.lower() == "pls":
                cls.__save_pls(uris, path, relative)
            elif type_.lower() == "xspf":
                cls.__save_xspf(uris, path, name)
            else:
                cls.__save_m3u(uris, path, relative)

        if path is None:
            print_i("Saving playlists")
            playlists = cls.get_playlists()

            active_playlist = cls.get_active_playlist()
            if active_playlist:
                current = active_playlist.get_path_from_item(cls.current)
                active_playlist = cls.__instance.page_num(active_playlist)
            else:
                active_playlist = current = None

            uris = set()
            for playlist in playlists:
                uris.update(playlist.get_uris(all_=True))
            library.save_ool_tracks(uris)
            blautil.serialize_to_file(
                (playlists, active_playlist, current, BlaQueue.get_queue()),
                blaconst.PLAYLISTS_PATH)
        else:
            save(path, type_)

    def restore(self):
        print_i("Restoring playlists")

        try:
            playlists, active_playlist, current, queue = \
                blautil.deserialize_from_file(blaconst.PLAYLISTS_PATH)
        except (TypeError, ValueError):
            self.add_playlist()
        else:
            for playlist in playlists:
                self.append_page(playlist, playlist.get_name())

            if active_playlist is not None:
                self.set_current_page(active_playlist)
                playlist = self.get_nth_page(active_playlist)
                type(self).current = playlist.get_item_from_path(current)
                self.current.select()

            BlaQueue.restore(queue)

        # FIXME: weird to handle this here. do this with a pipe instead
#        try:
#            action, uris = blaplay.cli_queue
#            blaplay.cli_queue = None
#        except TypeError:
#            pass
#        else:
#            if action == "append":
#                BlaPlaylistManager.add_to_current_playlist(uris, resolve=True)
#            elif action == "new":
#                BlaPlaylistManager.send_to_new_playlist(uris, resolve=True)
#            else:
#                BlaPlaylistManager.send_to_current_playlist(uris, resolve=True)

    @classmethod
    def add_playlist(cls, name=None, query_name=False, focus=False):
        if query_name:
            list_name = cls.__instance.__query_name("Playlist name")
            if not list_name:
                return
        elif name:
            list_name = name
        else:
            indices = set()
            r = re.compile(r"(^bla \()([0-9]+)\)")
            for playlist in cls.__instance:
                label = playlist.get_name(as_text=True)

                if label == "bla":
                    indices.add(0)
                else:
                    try:
                        num = r.match(label).group(2)
                    except AttributeError:
                        continue
                    num = int(num)
                    if num > 0:
                        indices.add(num)

            list_name = "bla"
            if indices and 0 in indices:
                indices = list(indices)
                candidates = xrange(min(indices), max(indices) + 2)
                candidates = list(set(candidates).difference(indices))
                if candidates:
                    idx = candidates[0]
                else:
                    idx = indices[-1]
                list_name += " (%d)" % idx

        playlist = BlaPlaylist(list_name)
        page_num = cls.__instance.append_page(playlist, playlist.get_name())
        cls.__instance.child_set_property(playlist, "reorderable", True)

        if focus:
            cls.__instance.set_current_page(page_num)

        return playlist

    @classmethod
    def focus_playlist(cls, playlist):
        self_ = cls.__instance
        self_.set_current_page(self_.page_num(playlist))

    @classmethod
    def get_playlist_index(cls, playlist):
        idx = cls.__instance.page_num(playlist)
        if idx == -1:
            idx = None
        return idx

    @classmethod
    def get_nth_playlist(cls, idx):
        return cls.__instance.get_nth_page(idx)

    @classmethod
    def remove_playlist(cls, playlist):
        if not playlist.modification_allowed(check_filter_state=False):
            return
        if not playlist:
            return False

        if cls.get_active_playlist() == playlist:
            try:
                cls.current.playlist = None
            except AttributeError:
                pass
        playlist.clear()
        page_num = cls.__instance.page_num(playlist)
        if page_num != -1:
            cls.__instance.remove_page(page_num)

        if cls.__instance.get_n_pages() < 1:
            cls.__instance.add_playlist()

    @classmethod
    def select(cls, type_):
        cls.get_current_playlist().select(type_)

    @classmethod
    def cut(cls, *args):
        playlist = cls.get_current_playlist()
        cls.clipboard = playlist.get_items(remove=True)
        blagui.update_menu(blaconst.VIEW_PLAYLISTS)

    @classmethod
    def copy(cls, *args):
        playlist = cls.get_current_playlist()
        cls.clipboard = map(copy, playlist.get_items(remove=False))
        blagui.update_menu(blaconst.VIEW_PLAYLISTS)

    @classmethod
    def paste(cls, *args, **kwargs):
        playlist = cls.get_current_playlist()
        if not playlist.modification_allowed():
            return
        playlist.add_items(items=cls.clipboard, drop_info=-1, select_rows=True)

    @classmethod
    def remove(cls, *args):
        playlist = cls.get_current_playlist()
        playlist.get_items(remove=True)

    @classmethod
    def clear(cls, *args):
        cls.get_current_playlist().clear()

    @classmethod
    def toggle_lock_playlist(cls, *args):
        playlist = cls.get_current_playlist()
        playlist.toggle_lock()

    @classmethod
    def new_playlist(cls, type_):
        cls.get_current_playlist().new_playlist(type_)

    @classmethod
    def remove_duplicates(cls):
        cls.get_current_playlist().remove_duplicates()

    @classmethod
    def remove_invalid_tracks(cls):
        cls.get_current_playlist().remove_invalid_tracks()

    @classmethod
    def send_to_current_playlist(cls, uris, resolve=False):
        playlist = cls.get_current_playlist()
        if not playlist.modification_allowed(check_filter_state=False):
            return

        if resolve:
            uris = library.parse_ool_uris(uris)
        if not uris:
            return

        try:
            cls.current.clear_icon()
        except AttributeError:
            pass
        # Reset cls.current to make sure the get_track() method will try to
        # request the next track from the currently visible playlist.
        cls.current = None
        playlist.clear()
        playlist.add_items(create_items_from_uris(uris))
        cls.__instance.get_track(blaconst.TRACK_NEXT, False)
        force_view()

    @classmethod
    def add_to_current_playlist(cls, uris, resolve=False):
        playlist = cls.get_current_playlist()
        if not playlist.modification_allowed():
            return

        if resolve:
            uris = library.parse_ool_uris(uris)
        if not uris:
            return

        playlist.add_items(create_items_from_uris(uris), select_rows=True)
        force_view()

    @classmethod
    def send_to_new_playlist(cls, items, name="", resolve=False, select=False):
        # This is also invoked as response to DND operations on the notebook
        # tab strip. In this case we get BlaListItem instances instead of URIs
        # which we need to preserve in order for their id()'s to remain
        # unchanged.

        if resolve:
            items = library.parse_ool_uris(items)
        if not items:
            return

        if not isinstance(items[0], BlaListItem):
            items = create_items_from_uris(items)
        else:
            items = items

        playlist = cls.__instance.add_playlist(name=name, focus=True)
        playlist.add_items(items, select_rows=select)
        force_view()

    @classmethod
    def update_statusbar(cls, playlist=None):
        # This is called by BlaPlaylist instances to update the statusbar.

        if playlist is None:
            playlist = cls.get_current_playlist()
        try:
            count, size, length_seconds = playlist.get_playlist_stats()
        except AttributeError:
            return

        if count == 0:
            info = ""
        else:
            info = parse_playlist_stats(count, size, length_seconds)
        BlaStatusbar.set_view_info(blaconst.VIEW_PLAYLISTS, info)

    @classmethod
    def update_uris(cls, uris):
        for playlist in cls.get_playlists():
            playlist.update_uris(uris)

    @classmethod
    def invalidate_visible_rows(cls):
        cls.get_current_playlist().invalidate_visible_rows()

    def get_track(self, choice, force_advance):
        # This is called in response to BlaPlayer's get_track signal.

        item = None
        if choice not in [blaconst.TRACK_PREVIOUS, blaconst.TRACK_RANDOM]:
            item = BlaQueue.get_item()

        if not item:
            playlist = self.get_active_playlist()
            if not playlist:
                playlist = self.get_current_playlist()
            item = playlist.get_item(choice, force_advance)

        self.play_item(item)

    @classmethod
    def play_item(cls, item):
        try:
            cls.current.clear_icon()
        except AttributeError:
            pass

        cls.current = item
        if item:
            cls.__instance.emit("play_track", item.uri)
            if blacfg.getboolean("general", "cursor.follows.playback"):
                item.select()

    @classmethod
    def get_playlists(cls):
        return map(None, cls.__instance)

    @classmethod
    def next(cls):
        for playlist in cls.__instance:
            yield playlist

    @classmethod
    def show_properties(cls, *args):
        cls.get_current_playlist().show_properties()

    @classmethod
    def show_tabs(cls, state):
        cls.__instance.set_show_tabs(state)
        blacfg.setboolean("general", "playlist.tabs", state)

    @classmethod
    def jump_to_playing_track(cls):
        playlist = cls.get_active_playlist()
        if (blacfg.getint("general", "view") == blaconst.VIEW_PLAYLISTS and
            playlist == cls.get_current_playlist()):
            playlist.jump_to_playing_track()

