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

from collections import OrderedDict
from copy import copy as copyfunc
import os
import re

import gobject
import gtk
import pango
from pangocairo import CairoContext

from blaplay.blacore import blaconst
from blaplay import blagui, blautil
from blaplay.formats._identifiers import *
from blaplay.blautil import blafm
from .blaview import BlaView
from ..blawindows import BlaScrolledWindow
from .. import blaguiutil

(COLUMN_INDEX, COLUMN_PLAYING, COLUMN_TRACK, COLUMN_ARTIST,
 COLUMN_TITLE, COLUMN_ALBUM, COLUMN_DURATION, COLUMN_ALBUM_ARTIST, COLUMN_YEAR,
 COLUMN_GENRE, COLUMN_FORMAT, COLUMN_BITRATE, COLUMN_FILESIZE, COLUMN_FILENAME,
 COLUMN_DIRECTORY) = range(15)

COLUMNS_DEFAULT_PLAYLIST = (COLUMN_PLAYING, COLUMN_TRACK, COLUMN_ARTIST,
                            COLUMN_TITLE, COLUMN_ALBUM, COLUMN_DURATION)

MODE_NORMAL, MODE_SORTED, MODE_FILTERED = 1 << 0, 1 << 1, 1 << 2


@blautil.caches_return_value
def _format_track_list_stats(count, size, length_seconds):
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

def _make_query_function(config, filter_string, treat_as_regex):
    def column_to_tag_ids(column_id):
        if column_id == COLUMN_ALBUM_ARTIST:
            return [ALBUM_ARTIST, COMPOSER, PERFORMER]
        elif column_id == COLUMN_YEAR:
            return [YEAR]
        elif column_id == COLUMN_GENRE:
            return [GENRE]
        elif column_id == COLUMN_FORMAT:
            return [FORMAT]
        return []

    query_identifiers = [ARTIST, TITLE, ALBUM]
    # TODO: Pass in a list of columns instead.
    columns = config.getlistint("general", "columns.playlist")
    if columns is None:
        columns = COLUMNS_DEFAULT_PLAYLIST
    for column_id in columns:
        query_identifiers.extend(column_to_tag_ids(column_id))
    flags = re.UNICODE | re.IGNORECASE
    filter_string = filter_string.decode("utf-8")
    if treat_as_regex:
        search_functions = [re.compile(r"%s" % filter_string, flags).search]
    else:
        search_functions = [re.compile(t, flags).search
                            for t in map(re.escape, filter_string.split())]

    def query(item):
        track = item.track
        for search_function in search_functions:
            for identifier in query_identifiers:
                if search_function(track[identifier]):
                    break
            else:
                return False
        return True
    return query


class BlaTrackListItem(object):
    __slots__ = ("_track", "queue_positions" )

    def __init__(self, track):
        self._track = track
        self.queue_positions = []

    @property
    def track(self):
        return self._track

    @property
    def uri(self):
        return self._track.uri

class _BlaCellRenderer(blaguiutil.BlaCellRendererBase):
    """
    Custom cellrenderer class which will render an icon if the stock-id
    property is not None and the text property otherwise. This is used for the
    `Playing' column where the queue position and status icon are both supposed
    to be centered in the cell which isn't possible with two distinct
    CellRenderers.
    """

    __gproperties__ = {
        "text": (gobject.TYPE_STRING, "text", "", "", gobject.PARAM_READWRITE),
        "stock-id": (gobject.TYPE_STRING, "text", "", "",
                     gobject.PARAM_READWRITE)
    }

    def __init__(self):
        super(_BlaCellRenderer, self).__init__()

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

            context = CairoContext(cr)
            if width < expose_area.width:
                x = (expose_area.x +
                     round((expose_area.width - width + 0.5) / 2))
            else:
                x = expose_area.x
            context.move_to(
                x,
                expose_area.y + round((expose_area.height - height + 0.5) / 2))
            context.show_layout(layout)

class _BlaColumn(gtk.TreeViewColumn):
    def __new__(cls, *args, **kwargs):
        if cls == _BlaColumn:
            raise ValueError("Cannot instantiate abstract class '%s'" %
                             cls.__name__)
        return super(_BlaColumn, cls).__new__(cls, *args, **kwargs)

    def __init__(self, renderer=None, alignment=0.0, fixed_size=False):
        super(_BlaColumn, self).__init__(self.TITLE)
        self.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        self.set_reorderable(True)
        self.set_clickable(True)

        if renderer is None:
            renderer = gtk.CellRendererText()
            renderer.set_property("ellipsize", pango.ELLIPSIZE_END)
        self.pack_start(renderer)
        renderer.set_property("xalign", alignment)
        self.set_cell_data_func(renderer, self._cell_data_func)
        self.set_alignment(alignment)

        # Add the column header.
        label = gtk.Label(self.TITLE)
        self.set_widget(label)
        label.show()

        # Define the column-sizing policy.
        if fixed_size:
            xpad = gtk.CellRendererText().get_property("xpad")
            width = self._get_text_width(self.TITLE)
            padding = 14  # Arbitrary offset (see `self._get_text_with`)
            self.set_min_width(width + padding + 2 * xpad)
        else:
            self.set_expand(True)
            self.set_resizable(True)

    @staticmethod
    def _get_text_width(text):
        # FIXME: This doesn't take theming rules into account. For instance,
        #        Adwaita uses bold fonts in treeview headers so the width
        #        returned here is wrong. So far, we solve this by adding an
        #        arbitrary offset to the minimum width which is less than
        #        ideal.
        return gtk.Label().create_pango_layout(text).get_pixel_size()[0]

    def _cell_data_func(self, column, renderer, model, iterator):
        track = model[iterator][0].track
        renderer.set_property("text", self.eval_track(track))

    @staticmethod
    def eval_track(track):
        raise NotImplementedError

    def get_header(self):
        return self.get_widget().get_ancestor(gtk.Button)

class BlaColumnIndex(_BlaColumn):
    ID = COLUMN_INDEX
    TITLE = "#"

    def __init__(self):
        super(BlaColumnIndex, self).__init__(fixed_size=True)
        self.set_clickable(False)

    def _cell_data_func(self, column, renderer, model, iterator):
        renderer.set_property("text", str(model[iterator].path[0]+1))

class BlaColumnPlaying(_BlaColumn):
    ID = COLUMN_PLAYING
    TITLE = "Playing"

    def __init__(self):
        renderer = _BlaCellRenderer()
        super(BlaColumnPlaying, self).__init__(
            renderer=renderer, alignment=0.5, fixed_size=True)
        self.add_attribute(renderer, "stock-id", 1)
        self.set_clickable(False)

    def _cell_data_func(self, column, renderer, model, iterator):
        queue_positions = model[iterator][0].queue_positions
        if queue_positions:
            text = "(%s)" % (", ".join(queue_positions))
        else:
            text = ""
        renderer.set_property("text", text)

class BlaColumnTrack(_BlaColumn):
    ID = COLUMN_TRACK
    TITLE = "Track"

    def __init__(self):
        super(BlaColumnTrack, self).__init__(fixed_size=True)

    @staticmethod
    def eval_track(track):
        try:
            value = "%d." % int(track[DISC].split("/")[0])
        except ValueError:
            value = ""
        try:
            value += "%02d" % int(track[TRACK].split("/")[0])
        except ValueError:
            pass
        return value

class BlaColumnArtist(_BlaColumn):
    ID = COLUMN_ARTIST
    TITLE = "Artist"

    def __init__(self):
        super(BlaColumnArtist, self).__init__()

    @staticmethod
    def eval_track(track):
        return track[ARTIST]

class BlaColumnTitle(_BlaColumn):
    ID = COLUMN_TITLE
    TITLE = "Title"

    def __init__(self):
        super(BlaColumnTitle, self).__init__()

    @staticmethod
    def eval_track(track):
        return track[TITLE] or track.basename

class BlaColumnAlbum(_BlaColumn):
    ID = COLUMN_ALBUM
    TITLE = "Album"

    def __init__(self):
        super(BlaColumnAlbum, self).__init__()

    @staticmethod
    def eval_track(track):
        return track[ALBUM]

class BlaColumnDuration(_BlaColumn):
    ID = COLUMN_DURATION
    TITLE = "Duration"

    def __init__(self):
        super(BlaColumnDuration, self).__init__(alignment=1.0, fixed_size=True)

    @staticmethod
    def eval_track(track):
        return track.duration

class BlaColumnAlbumArtist(_BlaColumn):
    ID = COLUMN_ALBUM_ARTIST
    TITLE = "Album artist"

    def __init__(self):
        super(BlaColumnAlbumArtist, self).__init__()

    @staticmethod
    def eval_track(track):
        return (track[ALBUM_ARTIST] or track[PERFORMER] or track[ARTIST] or
                track[COMPOSER])

class BlaColumnYear(_BlaColumn):
    ID = COLUMN_YEAR
    TITLE = "Year"

    def __init__(self):
        super(BlaColumnYear, self).__init__()

    @staticmethod
    def eval_track(track):
        return track[DATE].split("-")[0]

class BlaColumnGenre(_BlaColumn):
    ID = COLUMN_GENRE
    TITLE = "Genre"

    def __init__(self):
        super(BlaColumnGenre, self).__init__()

    @staticmethod
    def eval_track(track):
        return track[GENRE]

class BlaColumnFormat(_BlaColumn):
    ID = COLUMN_FORMAT
    TITLE = "Format"

    def __init__(self):
        super(BlaColumnFormat, self).__init__()

    @staticmethod
    def eval_track(track):
        return track[FORMAT]

class BlaColumnBitrate(_BlaColumn):
    ID = COLUMN_BITRATE
    TITLE = "Bitrate"

    def __init__(self):
        super(BlaColumnBitrate, self).__init__()

    @staticmethod
    def eval_track(track):
        return track.bitrate

class BlaColumnFilesize(_BlaColumn):
    ID = COLUMN_FILESIZE
    TITLE = "Filesize"

    def __init__(self):
        super(BlaColumnFileize, self).__init__()

    @staticmethod
    def eval_track(track):
        return track.get_filesize(short=True)

class BlaColumnFilename(_BlaColumn):
    ID = COLUMN_FILENAME
    TITLE = "Filename"

    def __init__(self):
        super(BlaColumnFilename, self).__init__()

    @staticmethod
    def eval_track(track):
        return os.path.basename(track.uri)

class BlaColumnDirectory(_BlaColumn):
    ID = COLUMN_DIRECTORY
    TITLE = "Directory"

    def __init__(self):
        super(BlaColumnDirectory, self).__init__()

    @staticmethod
    def eval_track(track):
        return os.path.dirname(track.uri)

_classes = (
    BlaColumnIndex, BlaColumnPlaying, BlaColumnTrack, BlaColumnArtist,
    BlaColumnTitle, BlaColumnAlbum, BlaColumnDuration, BlaColumnAlbumArtist,
    BlaColumnYear, BlaColumnGenre, BlaColumnFormat, BlaColumnBitrate,
    BlaColumnFilesize, BlaColumnFilename, BlaColumnDirectory
)
COLUMNS = OrderedDict([(cls.ID, cls) for cls in _classes])

class _BlaTrackListTreeView(blaguiutil.BlaTreeViewBase):
    __gsignals__ = {
        "column-layout-changed": blautil.signal(1),
        "sort-column": blautil.signal(2)
    }

    def __init__(self, ignored_column_ids=None):
        super(_BlaTrackListTreeView, self).__init__()
        self.set_fixed_height_mode(True)
        self.set_rubber_banding(True)
        self.set_property("rules-hint", True)

        self._ignored_column_ids = ignored_column_ids or []

        self._callback_id = self.connect_object(
            "columns-changed", _BlaTrackListTreeView._on_columns_changed, self)

    def _on_columns_changed(self):
        active_column_ids = [column.ID for column in self.get_columns()]
        self.emit("column-layout-changed", active_column_ids)

    def _on_button_press_event(self, event):
        if not (hasattr(event, "button") and event.button == 3):
            return False

        def on_toggled(menu_item, column_id):
            if menu_item.get_active():
                if column_id not in active_column_ids:
                    active_column_ids.append(column_id)
            else:
                try:
                    active_column_ids.remove(column_id)
                except ValueError:
                    pass
            self.emit("column-layout-changed", active_column_ids)

        active_column_ids = [column.ID for column in self.get_columns()]
        menu = blaguiutil.BlaMenu(event)
        for column_id, column in COLUMNS.items():
            if column_id in self._ignored_column_ids:
                continue
            m = menu.append_check_item(column.TITLE)
            m.set_active(column_id in active_column_ids)
            m.set_sensitive(len(active_column_ids) > 1)
            m.connect("toggled", on_toggled, column_id)
        menu.run()

    def add_columns(self, column_ids):
        # We have to block the signal handler of the "columns-changed" event
        # as otherwise it gets invoked on every `self.append_column()' call.
        self.handler_block(self._callback_id)
        for column in self.get_columns():
            self.remove_column(column)
        for column_id in column_ids:
            if column_id in self._ignored_column_ids:
                continue
            column = COLUMNS[column_id]()
            self.append_column(column)
            header = column.get_header()
            header.connect_object(
                "button-press-event",
                _BlaTrackListTreeView._on_button_press_event, self)
            column.connect("clicked", self.sort_column)
        self.handler_unblock(self._callback_id)

    def sort_column(self, column):
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
        self.emit("sort-column", column.ID, sort_order)

class _ListStoreSet(gtk.ListStore):
    def __init__(self, *args):
        super(_ListStoreSet, self).__init__(*args)
        self._set = set()

    def append(self, value):
        if value not in self._set:
            super(_ListStoreSet, self).append(value)

class BlaTrackList(BlaView):
    _MODEL_LAYOUT = (
        gobject.TYPE_PYOBJECT,  # BlaTrackListItem instance
        gobject.TYPE_STRING     # Stock item id
    )

    def _reset(self):
        self._length = 0
        self._size = 0
        self._all_items = []            # Unfiltered, unsorted tracks
        self._all_sorted = []           # Unfiltered, sorted tracks
        self._items = []                # Visible tracks when unsorted
        self._sorted = []               # Visible tracks when sorted
        self._sort_parameters = None
        self._filter_callback_id = -1
        self._mode = MODE_NORMAL

    def _create_filter_entry(self):
        entry = gtk.Entry()
        entry.set_icon_from_stock(gtk.ENTRY_ICON_SECONDARY, gtk.STOCK_CANCEL)
        entry.connect("icon-release", lambda *x: self.disable_search())
        def on_key_press_event(item, event):
            if blagui.is_accel(event, "Escape"):
                self.disable_search()
            return False
        entry.connect("key-press-event", on_key_press_event)
        completion = gtk.EntryCompletion()
        completion.set_inline_completion(True)
        completion.set_inline_selection(True)
        completion.set_popup_completion(False)
        completion.set_model(_ListStoreSet(gobject.TYPE_STRING))
        completion.set_text_column(0)
        entry.set_completion(completion)
        entry.connect("activate", self._filter)
        return entry

    @staticmethod
    def _create_filter_box(regex_button, entry, search_button):
        hbox = gtk.HBox()
        hbox.pack_start(regex_button, expand=False)
        hbox.pack_start(entry)
        hbox.pack_start(search_button, expand=False)
        hbox.set_visible(False)
        return hbox

    def __init__(self, player, name, *args, **kwargs):
        super(BlaTrackList, self).__init__(name, *args, **kwargs)
        self._player = player

        self._reset()

        # Set up the filter box.
        self._entry = self._create_filter_entry()
        self._regex_button = gtk.ToggleButton(".*")
        self._regex_button.set_tooltip_text(
            "Treat search string as regular expression")
        search_button = gtk.Button()
        search_button.add(
            gtk.image_new_from_stock(gtk.STOCK_FIND,
                                     gtk.ICON_SIZE_SMALL_TOOLBAR))
        search_button.connect("clicked", self._filter)
        self._filter_box = self._create_filter_box(
            self._regex_button, self._entry, search_button)

        self._treeview = _BlaTrackListTreeView()

        sw = BlaScrolledWindow()
        sw.set_shadow_type(gtk.SHADOW_NONE)
        sw.add(self._treeview)

        vbox = gtk.VBox()
        vbox.pack_start(self._filter_box, expand=False)
        vbox.pack_start(sw)

        self.add(blaguiutil.wrap_in_viewport(vbox))

        self.show_all()
        self.disable_search()

    def _populate_model(self, scroll_item=None, row_align=0.5,
                        selected_items=None):
        items = self._get_visible_items()

        # Determine new track list metadata.
        self._length = sum([item.track[LENGTH] for item in items])
        self._size = sum([item.track[FILESIZE] for item in items])

        # Fill and apply the new model.
        model = gtk.ListStore(*self._MODEL_LAYOUT)
        append = model.append
        for item in items:
            append([item, None])
        self._treeview.set_model(model)

        # Select the appropriate rows and scroll to last known location.
        if selected_items is not None:
            selection = self._treeview.get_selection()
            paths = self.get_paths_from_items(selected_items)
            select_path = selection.select_path
            map(select_path, paths)

        path = self.get_path_from_item(scroll_item)
        if path and model.get_iter_first():
            self._scroll_to_cell(path, row_align=row_align)

        # Set the sort indicators if necessary.
        try:
            sort_column, sort_order, sort_indicator = self._sort_parameters
        except TypeError:
            pass
        else:
            # Find the column we should sort for.
            for column in self._treeview.get_columns():
                if column.ID == sort_column:
                    column.set_sort_indicator(sort_indicator)
                    if sort_indicator:
                        column.set_sort_order(sort_order)
                    break

        # Update the state icon and the statusbar.
        self._update_state_icon()
        self.manager.update_statusbar(self)

    def _update_state_icon(self):
        pass

    def _get_selection_and_row(self):
        row_align = 0.0
        selection = self._treeview.get_selection()
        selected_paths = self.get_selected_paths()

        # Get item of the row to scroll to.
        try:
            scroll_item = self.get_item_from_path(selected_paths[0])
        except IndexError:
            try:
                scroll_item = self.get_item_from_path(
                    self._treeview.get_visible_range()[0])
            except (TypeError, IndexError):
                scroll_item = None
        else:
            column = self._treeview.get_columns()[0]
            height = self._treeview.get_allocation().height

            try:
                low, high = self._treeview.get_visible_range()
                for path in selected_paths:
                    if low <= path <= high:
                        break
            except TypeError:
                row_align = 0.5
            else:
                row_align = (self._treeview.get_cell_area(path, column)[1] /
                             float(height))

        # Get selected items
        try:
            selected_items = [self.get_item_from_path(path)
                              for path in selected_paths]
        except IndexError:
            selected_items = None

        if not (0.0 <= row_align <= 1.0):
            row_align = 0.0
        return scroll_item, row_align, selected_items

    def _get_visible_items(self):
        if self._mode & MODE_FILTERED:
            if self._mode & MODE_SORTED:
                items = self._sorted
            else:
                items = self._items
        else:
            if self._mode & MODE_SORTED:
                items = self._all_sorted
            else:
                items = self._all_items
        return items

    def _freeze_treeview(self):
        self._treeview.freeze_notify()
        self._treeview.freeze_child_notify()
        return self._treeview.get_model()

    def _thaw_treeview(self):
        self._treeview.thaw_child_notify()
        self._treeview.thaw_notify()

    def _filter(self, *args):
        scroll_item, row_align, selected_items = self._get_selection_and_row()

        filter_string = self._entry.get_text().strip()
        if filter_string:
            # Add the search string to the completion model (it's subclassed
            # to behave like a set).
            completion_model = self._entry.get_completion().get_model()
            completion_model.append((filter_string,))

            self._mode |= MODE_FILTERED
            config = self._manager._config # XXX: Ugly!!
            query = _make_query_function(
                config, filter_string, self._regex_button.get_active())
            if self._mode & MODE_SORTED:
                self._sorted = filter(query, self._all_sorted)
            else:
                self._items = filter(query, self._all_items)
        else:
            self._mode &= ~MODE_FILTERED
            if self._mode & MODE_SORTED:
                self._sorted = list(self._all_sorted)
            else:
                self._items = list(self._all_items)

        self._populate_model(scroll_item, row_align, selected_items)

    def _on_drag_data_get(self, drag_context, selection_data, info, time):
        raise NotImplementedError

    def _on_drag_data_recveived(
        self, drag_context, x, y, selection_data, info, time):
        raise NotImplementedError

    def _select(self, type_):
        selection = self._treeview.get_selection()
        selected_paths = self.get_selected_paths()

        if type_ == blaconst.SELECT_ALL:
            selection.select_all()
            return
        elif type_ == blaconst.SELECT_COMPLEMENT:
            selected_paths = set(selected_paths)
            paths = [(p,) for p in xrange(len(self._treeview.get_model()))]
            paths = set(paths)
            paths.difference_update(selected_paths)
            selection.unselect_all()
            select_path = selection.select_path
            map(select_path, paths)
            return
        elif type_ == blaconst.SELECT_BY_ARTISTS:
            column_id = COLUMN_ARTIST
        elif type_ == blaconst.SELECT_BY_ALBUMS:
            # FIXME: This fails on Anjunadeep05 (CD1).
            column_id = COLUMN_ALBUM
        elif type_ == blaconst.SELECT_BY_ALBUM_ARTISTS:
            column_id = COLUMN_ALBUM_ARTIST
        else:
            column_id = COLUMN_GENRE

        # Assemble a set of strings we want to match.
        items = self.get_items_from_paths(selected_paths)
        eval_ = COLUMNS[column_id].eval_track
        values = set()
        for item in items:
            values.add(eval_(item.track).lower())
        if not values:
            return

        # Filter currently displayed items
        r = re.compile(r"^(%s)$" % "|".join(values),
                       re.UNICODE | re.IGNORECASE)
        items = [item for item in self._get_visible_items()
                 if r.match(eval_(item.track))]
        paths = self.get_paths_from_items(items)
        selection.unselect_all()
        select_path = selection.select_path
        map(select_path, paths)

    def _play_item_at_path(self, path):
        item = self.get_item_from_path(path)
        self.manager.play_item(item)

    def _remove_selected_items(self):
        paths = self.get_selected_paths()
        return self.get_items(paths, remove=True)

    def _cut_selected_items(self):
        self._manager.clipboard[:] = self._remove_selected_items()

    def _copy_selected_items(self, *args):
        paths = self.get_selected_paths()
        self._manager.clipboard[:] = map(copyfunc, self.get_items(paths))

    def _paste_items_from_clipboard(self, *args, **kwargs):
        if not self.can_modify():
            return
        self.add_items(items=self._manager.clipboard, drop_info=-1,
                       select_rows=True)

    def _add_context_menu_options(self, menu):
        pass

    def _on_popup(self, treeview, event):
        accel_group = blagui.get_accelerator_group(self)
        clipboard_has_items = len(self._manager.clipboard) > 0

        menu = blaguiutil.BlaMenu(event)
        try:
            path = treeview.get_path_at_pos(*map(int, [event.x, event.y]))[0]
        except TypeError:
            m = menu.append_item("Paste", self._paste_items_from_clipboard)
            m.set_sensitive(clipboard_has_items)
            mod, key = gtk.accelerator_parse("<Ctrl>V")
            m.add_accelerator(
                "activate", accel_group, mod, key, gtk.ACCEL_VISIBLE)

            menu.append_item("Clear list", self.clear)
        else:
            model, paths = treeview.get_selection().get_selected_rows()
            item = model[path][0]

            menu.append_item("Play", self._play_item_at_path, path)
            menu.append_separator()

            items = [
                ("Cut", self._cut_selected_items, "<Ctrl>X", True),
                ("Copy",  self._copy_selected_items, "<Ctrl>C", True),
                ("Remove", self._remove_selected_items, "Delete", True),
                ("Paste", self._paste_items_from_clipboard, "<Ctrl>V",
                 len(self._manager.clipboard) > 0),
                ("Clear list", self.clear, None, True)
            ]
            for label, callback, accelerator, sensitive in items:
                m = menu.append_item(label, callback)
                if accelerator is not None:
                    mod, key = gtk.accelerator_parse(accelerator)
                    m.add_accelerator(
                        "activate", accel_group, mod, key, gtk.ACCEL_VISIBLE)
                m.set_sensitive(sensitive)
            menu.append_separator()

            submenu = blaguiutil.BlaMenu()
            items = [
                # TODO: Pull the blaconst.SELECT_* flags into this module.
                ("all", blaconst.SELECT_ALL),
                ("complement", blaconst.SELECT_COMPLEMENT),
                ("by artist(s)", blaconst.SELECT_BY_ARTISTS),
                ("by album(s)", blaconst.SELECT_BY_ALBUMS),
                ("by album artist(s)", blaconst.SELECT_BY_ALBUM_ARTISTS),
                ("by genre(s)", blaconst.SELECT_BY_GENRES)
            ]
            for label, type_ in items:
                submenu.append_item(label, self._select, type_)
            menu.append_submenu("Select...", submenu)

            self._add_context_menu_options(menu)
            if not menu.is_last_item_separator():
                menu.append_separator()

            item = treeview.get_model()[path][0]
            submenu = blafm.create_popup_menu(self._player, item.track)
            if submenu is not None:
                menu.append_submenu("last.fm", submenu)
                menu.append_separator()

            menu.append_item(
                "Open containing directory",
                lambda *x: blautil.open_directory(os.path.dirname(item.uri)))

        menu.run()

    def _on_key_press_event(self, treeview, event):
        accels = [
            ("<Ctrl>X", self._cut_selected_items),
            ("<Ctrl>C", self._copy_selected_items),
            ("<Ctrl>V", self._paste_items_from_clipboard),
            ("Escape", self.disable_search)
        ]
        for accel, callback in accels:
            if blagui.is_accel(event, accel):
                callback()
                return True
        return False

    def _scroll_to_cell(self, path, row_align):
        try:
            low, high = self._treeview.get_visible_range()
        except TypeError:
            low = high = None
        if low is None or not (low <= path <= high):
            self._treeview.scroll_to_cell(
                path, use_align=True, row_align=row_align)

    def get_status_message(self):
        count, size, length_seconds = self.get_stats()
        if count == 0:
            info = ""
        else:
            info = _format_track_list_stats(
                count, size, length_seconds)
        return info

    def refresh_column_layout(self):
        raise NotImplementedError

    def can_modify(self, check_filter_state=True):
        return True

    def get_items(self, paths, remove=False):
        if remove and not self.can_modify():
            return []

        items = self.get_items_from_paths(paths)
        if remove:
            length, size = self._get_length_and_size_of_items(items)
            self._length -= length
            self._size -= size

            # Remove the rows from the model.
            model = self._freeze_treeview()
            get_iter = model.get_iter
            iterators = map(get_iter, paths)
            remove = model.remove
            map(remove, iterators)
            self._thaw_treeview()

            # Remove items from the book-keeping lists.
            lists = [self._all_items]
            if self._mode & MODE_FILTERED:
                lists.append(self._items)
                if self._mode & MODE_SORTED:
                    lists.append(self._sorted)
            if self._mode & MODE_SORTED:
                lists.append(self._all_sorted)

            for list_ in lists:
                remove = list_.remove
                map(remove, items)

            self.manager.update_statusbar(self)
        return items

    def get_path_from_item(self, item, all_=False):
        if self._mode & MODE_FILTERED and not all_:
            if self._mode & MODE_SORTED:
                items = self._sorted
            else:
                items = self._items
        else:
            if self._mode & MODE_SORTED:
                items = self._all_sorted
            else:
                items = self._all_items
        try:
            return (items.index(item),)
        except ValueError:
            return None

    def get_paths_from_items(self, items):
        items_ = self._get_visible_items()
        paths = []
        for item in items:
            try:
                paths.append((items_.index(item),))
            except ValueError:
                pass
        return paths

    def get_item_from_path(self, path):
        if self._mode & MODE_FILTERED:
            if self._mode & MODE_SORTED:
                items = self._sorted
            else:
                items = self._items
        else:
            if self._mode & MODE_SORTED:
                items = self._all_sorted
            else:
                items = self._all_items
        try:
            return items[path[0]]
        except (TypeError, IndexError):
            return None

    def get_items_from_paths(self, paths):
        items_ = self._get_visible_items()
        items = []
        for path in paths:
            try:
                items.append(items_[path[0]])
            except (TypeError, IndexError):
                pass
        return items

    def _get_all_items(self):
        if self._mode & MODE_SORTED:
            items = self._all_sorted
        else:
            items = self._all_items
        return items

    def get_all_tracks(self):
        return [item.track for item in self._get_all_items()]

    def get_all_uris(self):
        return [item.uri for item in self._get_all_items()]

    def add_items(self, items, drop_info=None, select_rows=False):
        if not items:
            return

        # XXX: Why don't we do this on drop_info == None?
        # If drop_info is -1 insert at the cursor or at the end of the playlist
        # if nothing is selected.
        if drop_info == -1:
            try:
                # The get_cursor() method might still return something even if
                # the selection in a treeview is empty. In this case we also
                # want to append tracks to the playlist and thus raise a
                # TypeError here to force path to be None.
                if not self.get_selected_paths():
                    raise TypeError
                path, column = self._treeview.get_cursor()
            except TypeError:
                drop_info = None
            else:
                drop_info = (path, gtk.TREE_VIEW_DROP_BEFORE)

        reverse = False
        model = self._freeze_treeview()
        iterator = None
        if drop_info is not None:
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

        # Insert into the actual model.
        for item in items:
            iterator = insert_func(iterator, [item, None])

        # Insertion is likely to destroy the sort order so remove the sort
        # indicator.
        for column in self._treeview.get_columns():
            column.set_sort_indicator(False)

        # Select the added rows if requested.
        if select_rows:
            selection = self._treeview.get_selection()
            selection.unselect_all()
            paths = [(p,) for p in range(path[0], path[0]+len(items))]
            self.set_row(self.get_path_from_item(scroll_item), paths,
                         row_align=1.0)

        self._thaw_treeview()

        self._update_state_icon()
        self.manager.update_statusbar(self)

    @staticmethod
    def _get_length_and_size_of_items(items):
        length = size = 0
        for item in items:
            length += item.track[LENGTH]
            size += item.track[FILESIZE]
        return length, size

    def insert(self, items, drop_info):
        # Due to the way playlist contents are handled to speed up filtering
        # and sorting, dealing with track insertion into our book-keeping lists
        # is a rather fiddly task so be careful tampering with this function!
        if self._mode & MODE_SORTED:
            list_ = self._all_sorted
        else:
            list_ = self._all_items

        if drop_info is not None:
            path, pos = drop_info
            if pos in [gtk.TREE_VIEW_DROP_BEFORE,
                       gtk.TREE_VIEW_DROP_INTO_OR_BEFORE]:
                start = path[0]
            else:
                start = path[0]+1
        else:
            start = len(list_)

        # Use slice notation to insert into `list_' in-place.
        list_[:] = list_[:start] + items + list_[start:]

        # FIXME: This is the second check whether the list is sorted in this
        #        function.
        if self._mode & MODE_SORTED:
            if start > 0:
                item = list_[start-1]
                start = self._all_items.index(item)+1
            else:
                item = list_[start+1]
                start = self._all_items.index(item)

            self._all_items[:] = (self._all_items[:start] + items +
                                  self._all_items[start:])

        # Update the playlist statistics.
        length, size = self._get_length_and_size_of_items(items)
        self._length += length
        self._size += size

    def get_selected_paths(self):
        return self._treeview.get_selection().get_selected_rows()[-1]

    def enable_search(self):
        self._entry.grab_focus()
        self._filter_callback_id = self._entry.connect(
            "activate", self._filter)
        self._filter_box.set_visible(True)

    def disable_search(self):
        self._filter_box.set_visible(False)
        if self._entry.handler_is_connected(self._filter_callback_id):
            self._entry.disconnect(self._filter_callback_id)
        self._entry.delete_text(0, -1)
        # If the playlist was filtered, unfilter it. This happens implicitly
        # as we made sure the search entry is empty.
        if self._mode & MODE_FILTERED:
            self._filter()

    # XXX: Remove this once we use unique IDs instead of URIs to identify
    #      library tracks.
    def update_uris(self, uris):
        for item in self._all_items:
            try:
                item.uri = uris[item.uri]
            except KeyError:
                pass

    def get_stats(self):
        items = (self._items if self._mode & MODE_FILTERED else
                 self._all_items)
        # TODO: Keep a _stats dict() in each playlist that stores this info.
        return (len(items), self._size, self._length)

    def invalidate_visible_rows(self):
        try:
            low, high = self._treeview.get_visible_range()
        except TypeError:
            pass
        else:
            model = self._treeview.get_model()
            get_iter = model.get_iter
            row_changed = model.row_changed
            for path in range(low[0], high[0]+1):
                row_changed(path, get_iter(path))

    def set_row(self, path, paths=None, row_align=0.5):
        # Wrap the actual heavy lifting in gobject.idle_add. If we decorate the
        # instance method itself we can't use kwargs anymore which is rather
        # annoying for this particular method.
        @blautil.idle
        def set_row():
            if path is not None:
                self._scroll_to_cell(path, row_align)
                self._treeview.set_cursor(path)
            if paths is not None:
                select_path = self._treeview.get_selection().select_path
                map(select_path, paths)
        set_row()

    def clear(self):
        self._reset()
        self._treeview.get_model().clear()
        self.disable_search()

