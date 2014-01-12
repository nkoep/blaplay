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

import os

import gobject
import gtk
import pango
from pangocairo import CairoContext

import blaplay
library = blaplay.bla.library
ui_manager = blaplay.bla.ui_manager
from blaplay.blacore import blaconst, blacfg
from blaplay import blautil, blagui
from blaplay.formats._identifiers import *
from blaplay.blautil import blafm
import blaguiutils

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


def parse_track_list_stats(count, size, length_seconds):
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
        tracks_label = "track"
    else:
        tracks_label = "tracks"
    return "%s %s | %s | %s" % (count, tracks_label, length, size)

def _header_popup(button, event, view_id):
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
            "button_press_event", _header_popup, view_id)
        column.connect(
            "clicked",
            lambda c=column, i=column_id: treeview.sort_column(c, i))

    treeview.connect_changed_signal()

def popup(treeview, event, view_id, target):
    from blaplaylist import BlaPlaylistManager
    from blaqueue import BlaQueue

    if view_id == blaconst.VIEW_PLAYLISTS:
        element = BlaPlaylistManager
    elif view_id == blaconst.VIEW_QUEUE:
        element = BlaQueue

    accel_group = ui_manager.get_accel_group()

    try:
        path = treeview.get_path_at_pos(*map(int, [event.x, event.y]))[0]
    except TypeError:
        menu = gtk.Menu()
        m = gtk.MenuItem("Paste")
        mod, key = gtk.accelerator_parse("<Ctrl>V")
        m.add_accelerator("activate", accel_group, mod, key, gtk.ACCEL_VISIBLE)
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
            m.add_accelerator("activate", accel_group, mod, key,
                              gtk.ACCEL_VISIBLE)
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
                if playlist == current_playlist:
                    continue
                m = gtk.MenuItem(playlist.get_name())
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
                if playlist == current_playlist:
                    continue
                m = gtk.MenuItem(playlist.get_name())
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
            m.add_accelerator("activate", accel_group, mod, key,
                              gtk.ACCEL_VISIBLE)
            m.connect("activate", callback)
            menu.append(m)

    menu.append(gtk.SeparatorMenuItem())

    item = treeview.get_model()[path][0]
    submenu = blafm.create_popup_menu(item.track)
    if submenu:
        m = gtk.MenuItem("last.fm")
        m.set_submenu(submenu)
        menu.append(m)

    m = gtk.MenuItem("Open containing directory")
    m.connect("activate",
              lambda *x: blautil.open_directory(os.path.dirname(item.uri)))
    menu.append(m)

    menu.show_all()
    menu.popup(None, None, None, event.button, event.time)


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

            style = widget.get_style()
            if (flags == (gtk.CELL_RENDERER_SELECTED |
                          gtk.CELL_RENDERER_PRELIT) or
                flags == gtk.CELL_RENDERER_SELECTED):
                color = style.text[gtk.STATE_SELECTED]
            else:
                color = style.text[gtk.STATE_NORMAL]
            cr.set_source_color(color)

            pc_context = CairoContext(cr)
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
        super(BlaTreeView, self).__init__()

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
        def columns_changed(treeview, view_id):
            if view_id == blaconst.VIEW_PLAYLISTS:
                view = "playlist"
            elif view_id == blaconst.VIEW_QUEUE:
                view = "queue"

            columns = [column.id_ for column in treeview.get_columns()]
            blacfg.set("general", "columns.%s" % view,
                       ", ".join(map(str, columns)))

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

# TODO: make this a "factory" function which returns the appropriate callable
#       based on the given column_id
class BlaEval(object):
    """
    Class which maps column ids to track tags, i.e. it defines what is
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

        self.id_ = column_id
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
        from blaqueue import BlaQueue

        if column_id == COLUMN_QUEUE_POSITION:
            text = "%02d" % int(model[iterator][1])
        elif column_id == COLUMN_PLAYING:
            pos = BlaQueue.get_queue_positions(item)
            text = "(%s)" % (", ".join(pos)) if pos else ""
        else:
            text = self.__cb(item.track)

        renderer.set_property("text", text)

class BlaTrackListItem(object):
    def __init__(self, uri):
        self.uri = uri
        self.playlist = None

    @property
    def track(self):
        return library[self.uri]

    def play(self):
        from blaplaylist import BlaPlaylistManager
        BlaPlaylistManager.play_item(self)

    def select(self):
        if not self.playlist:
            return
        from blaplaylist import BlaPlaylistManager
        if BlaPlaylistManager.get_current_playlist() != self.playlist:
            BlaPlaylistManager.focus_playlist(self.playlist)
        self.playlist.set_row(self.playlist.get_path_from_item(self))

    def clear_icon(self):
        if self.playlist:
            self.playlist.update_icon(clear=True)

