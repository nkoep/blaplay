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

import blaplay
player = blaplay.bla.player
library = blaplay.bla.library
ui_manager = blaplay.bla.ui_manager
from blaplay.blacore import blaconst, blacfg
from blaplay import blautil, blagui
from blaplay.formats._identifiers import *
from blawindows import BlaScrolledWindow
from blatracklist import (
    COLUMN_ALBUM_ARTIST, COLUMN_YEAR, COLUMN_GENRE, COLUMN_FORMAT,
    COLUMN_ARTIST, COLUMN_ALBUM, update_columns, parse_track_list_stats, popup,
    BlaTreeView, BlaEval, BlaTrackListItem)
from blaplay.blautil import blafm
from blastatusbar import BlaStatusbar
import blaview
import blaguiutils

MODE_NORMAL, MODE_SORTED, MODE_FILTERED = 1 << 0, 1 << 1, 1 << 2


def create_items_from_uris(uris):
    return map(BlaTrackListItem, uris)


# TODO: make this a factory function
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
        filter_string = filter_string.decode("utf-8")
        if regexp:
            self.__res = [re.compile(r"%s" % filter_string, flags)]
        else:
            self.__res = [re.compile(t, flags)
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

class BlaPlaylist(gtk.VBox):
    __layout = (
        gobject.TYPE_PYOBJECT,  # BlaTrackListItem instance
        gobject.TYPE_STRING     # Stock item id
    )
    __sort_parameters = None
    __fid = -1

    class ListStoreSet(gtk.ListStore):
        def __init__(self, *args):
            super(BlaPlaylist.ListStoreSet, self).__init__(*args)
            self.__set = set()

        def append(self, row):
            if row not in self.__set:
                super(BlaPlaylist.ListStoreSet, self).append(row)

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

    def __init__(self, name):
        super(BlaPlaylist, self).__init__()

        self.__history = BlaPlaylist.History(self)
        self.__mode = MODE_NORMAL

        self.__lock = blautil.BlaLock()

        self.__header_box = gtk.HBox()
        self.__header_box.pack_start(gtk.Label(name))
        self.__header_box.show_all()

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
        completion = gtk.EntryCompletion()
        completion.set_inline_completion(True)
        completion.set_inline_selection(True)
        completion.set_popup_completion(False)
        completion.set_model(BlaPlaylist.ListStoreSet(gobject.TYPE_STRING))
        completion.set_text_column(0)
        self.__entry.set_completion(completion)
        self.__entry.connect("activate", self.__filter)

        self.__regexp_button = gtk.ToggleButton(label="r\"\"")
        self.__regexp_button.set_tooltip_text(
            "Interpret search string as regular expression")

        button = gtk.Button()
        button.add(
            gtk.image_new_from_stock(gtk.STOCK_FIND, gtk.ICON_SIZE_BUTTON))
        button.connect("clicked", self.__filter)

        self.__filter_box = gtk.HBox()
        self.__filter_box.pack_start(self.__regexp_button, expand=False)
        self.__filter_box.pack_start(self.__entry, expand=True)
        self.__filter_box.pack_start(button, expand=False)
        self.__filter_box.show_all()
        self.__filter_box.set_visible(False)

        self.__treeview = BlaTreeView(view_id=blaconst.VIEW_PLAYLISTS)
        def selection_changed(selection):
            # FIXME: This gets called for each newly selected item in
            #        `add_items'.
            if playlist_manager.get_current_playlist() != self:
                return False
            paths = selection.get_selected_rows()[-1]
            uris = [item.uri for item in self.get_items_from_paths(paths)]
            playlist_manager.emit("selection_changed", uris)
        self.__treeview.get_selection().connect("changed", selection_changed)
        self.__treeview.connect_object(
            "sort_column", BlaPlaylist.sort, self)
        self.__treeview.connect("row_activated", self.play_item)
        self.__treeview.connect(
            "popup", popup, blaconst.VIEW_PLAYLISTS, self)
        self.__treeview.connect("key_press_event", self.__key_press_event)
        self.__treeview.connect_object("drag_data_get",
                                       BlaPlaylist.__drag_data_get, self)
        self.__treeview.connect_object("drag_data_received",
                                       BlaPlaylist.__drag_data_recv, self)

        # DND between playlists (includes playlist-internal DND)
        self.__treeview.enable_model_drag_source(
            gtk.gdk.BUTTON1_MASK,
            [blagui.DND_TARGETS[blagui.DND_PLAYLIST],
             blagui.DND_TARGETS[blagui.DND_URIS]],
            gtk.gdk.ACTION_COPY)

        # Receive drag and drop
        self.__treeview.enable_model_drag_dest(blagui.DND_TARGETS.values(),
                                               gtk.gdk.ACTION_COPY)

        sw = BlaScrolledWindow()
        sw.add(self.__treeview)

        self.clear()

        self.pack_start(self.__filter_box, expand=False)
        self.pack_start(sw, expand=True)
        sw.show_all()

        update_columns(self.__treeview, view_id=blaconst.VIEW_PLAYLISTS)
        self.show()

    def __reduce__(self):
        # This method can either return a string or a tuple. In the latter case
        # it has to return a tuple consisting of a callable used to create the
        # initial copy of the object, its default arguments, as well as the
        # state as passed to __setstate__ upon deserialization.
        return (self.__class__, ("bla",), self.__getstate__())

    def __getstate__(self):
        state = {
            "name": self.__header_box.children()[0].get_text(),
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
        self.set_name(state.get("name", ""))
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
            self.__scroll_to_cell(path, row_align=row_align)

        # Set sort indicators if necessary.
        try:
            column_id, sort_order, sort_indicator = self.__sort_parameters
        except TypeError:
            pass
        else:
            for column in self.__treeview.get_columns():
                if column.id_ == column_id:
                    break
            else:
                sort_order = None

            column.set_sort_indicator(sort_indicator)
            if sort_indicator:
                column.set_sort_order(sort_order)

        # Update the statusbar and the state icon in the playlist.
        self.update_icon()
        playlist_manager.update_statusbar()

    def __get_selection_and_row(self):
        row_align = 0.0
        selection = self.__treeview.get_selection()
        selected_paths = self.get_selected_paths()

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
            selected_items = [self.get_item_from_path(path)
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

    def __filter_parameters_changed(self, entry):
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
            # Add the search string to the completion model (it's subclassed
            # to behave like a set).
            completion_model = self.__entry.get_completion().get_model()
            completion_model.append((filter_string,))

            self.__mode |= MODE_FILTERED
            query = BlaQuery(
                filter_string, self.__regexp_button.get_active()).query
            if self.__mode & MODE_SORTED:
                self.__sorted = filter(query, self.__all_sorted)
            else:
                self.__items = filter(query, self.__all_items)
        else:
            self.__mode &= ~MODE_FILTERED
            if self.__mode & MODE_SORTED:
                self.__sorted = list(self.__all_sorted)
            else:
                self.__items = list(self.__all_items)

        self.__populate_model(scroll_item, row_align, selected_items)

    def __drag_data_get(self, drag_context, selection_data, info, time):
        idx = playlist_manager.get_playlist_index(self)
        paths = self.get_selected_paths()
        if info == blagui.DND_PLAYLIST:
            data = pickle.dumps((paths, idx), pickle.HIGHEST_PROTOCOL)
            selection_data.set("", 8, data)
        elif info == blagui.DND_URIS:
            items = self.get_items_from_paths(paths)
            uris = blautil.filepaths2uris([item.uri for item in items])
            selection_data.set_uris(uris)

    def __drag_data_recv(self, drag_context, x, y, selection_data, info, time):
        if not self.modification_allowed():
            return

        data = None
        self.__treeview.grab_focus()
        drop_info = self.__treeview.get_dest_row_at_pos(x, y)

        # DND from the library browser
        if info == blagui.DND_LIBRARY:
            uris = pickle.loads(selection_data.data)
            items = create_items_from_uris(uris)

        # DND between playlists (this case includes playlist-internal DND)
        elif info == blagui.DND_PLAYLIST:
            paths, idx = pickle.loads(selection_data.data)

            if drop_info:
                path, pos = drop_info
                item = self.get_item_from_path(path)
                if (path in paths and
                    idx == playlist_manager.get_playlist_index(self)):
                    return

            playlist = playlist_manager.get_nth_playlist(idx)
            # FIXME: what happens to the current track?
            items = playlist.get_items(paths=paths, remove=True)
            if drop_info:
                path = self.get_path_from_item(item)
                drop_info = (path, pos)

        # DND from the filesystem browser or an external location
        elif info == blagui.DND_URIS:
            uris = library.parse_ool_uris(
                blautil.resolve_uris(selection_data.get_uris()))
            items = create_items_from_uris(uris)

        # FIXME: If we don't add anything here GTK issues an assertion warning.
        if items:
            self.add_items(items, drop_info=drop_info, select_rows=True)

    def __key_press_event(self, treeview, event):
        def delete():
            paths = self.get_selected_paths()
            items = self.get_items(paths, remove=True)
            if playlist_manager.current in items:
                playlist_manager.current = None

        is_accel = blagui.is_accel
        accels = [
            ("Delete", delete),
            ("Q", lambda: self.send_to_queue()),
            ("R", lambda: self.remove_from_queue(self.__treeview)),
            ("Escape", self.disable_search)
        ]
        for accel, callback in accels:
            if is_accel(event, accel):
                callback()
                break
        return False

    def __scroll_to_cell(self, path, row_align):
        try:
            low, high = self.__treeview.get_visible_range()
        except TypeError:
            low = high = None
        if low is None or not (low <= path <= high):
            self.__treeview.scroll_to_cell(
                path, use_align=True, row_align=row_align)

    def get_header_box(self):
        return self.__header_box

    def get_name(self):
        return self.__header_box.children()[0].get_text()

    def set_name(self, name):
        self.__header_box.children()[0].set_text(name)

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
        selected_paths = self.get_selected_paths()

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

    def new_playlist_from_type(self, type_):
        paths = self.get_selected_paths()
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

        playlist = playlist_manager.add_playlist(focus=True)
        playlist.add_items(items=items)

    def add_items(self, items, drop_info=None, select_rows=False):
        if not items:
            return

        # Update the playlist reference of the new items.
        all_items = self.__all_items
        for idx, item in enumerate(items):
            # When a copied item is pasted into the same playlist multiple
            # times make sure it gets a new id by creating a shallow copy.
            if item.playlist == self:
                items[idx] = copy(item)
            else:
                item.playlist = self

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
                path, column = self.__treeview.get_cursor()
            except TypeError:
                drop_info = None
            else:
                drop_info = (path, gtk.TREE_VIEW_DROP_BEFORE)

        reverse = False
        model = self.__freeze_treeview()
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

        # Insertion is likely to destroy the sort order so remove sort
        # indicators.
        for column in self.__treeview.get_columns():
            column.set_sort_indicator(False)

        # Select the added rows if requested.
        if select_rows:
            selection = self.__treeview.get_selection()
            selection.unselect_all()
            paths = [(p,) for p in xrange(path[0], path[0]+len(items))]
            self.set_row(self.get_path_from_item(scroll_item), paths,
                         row_align=1.0)

        self.__thaw_treeview()
        playlist_manager.update_statusbar()
        self.update_icon()

    def insert(self, items, drop_info):
        # Due to the way playlist contents are handled to speed up filtering
        # and sorting, dealing with track insertion into our book-keeping lists
        # is a rather fiddly task so be careful tampering with this function!
        if self.__mode & MODE_SORTED:
            list_ = self.__all_sorted
        else:
            list_ = self.__all_items

        if drop_info is not None:
            path, pos = drop_info
            if pos in [gtk.TREE_VIEW_DROP_BEFORE,
                       gtk.TREE_VIEW_DROP_INTO_OR_BEFORE]:
                start = path[0]
            else:
                start = path[0]+1
        else:
            start = len(list_)

        # Insert into the list `list_' references by using slice notation to
        # assign the new values.
        list_[:] = list_[:start] + items + list_[start:]

        # FIXME: This is the second check whether the list is sorted in this
        #        function.
        if self.__mode & MODE_SORTED:
            if start > 0:
                item = list_[start-1]
                start = self.__all_items.index(item)+1
            else:
                item = list_[start+1]
                start = self.__all_items.index(item)

            self.__all_items[:] = (self.__all_items[:start] + items +
                                   self.__all_items[start:])

        # Update the playlist statistics.
        self.__length += sum(
            [item.track[LENGTH] for item in items])
        self.__size += sum(
            [item.track[FILESIZE] for item in items])

    def get_selected_paths(self):
        return self.__treeview.get_selection().get_selected_rows()[-1]

    def get_items(self, paths, remove=False):
        if remove and not self.modification_allowed():
            return []

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

            playlist_manager.update_statusbar()
        return items

    def remove_duplicates(self):
        def remove_duplicates():
            items = self.__get_current_items()
            scroll_item, row_align, selected_items = \
                self.__get_selection_and_row()

            paths = self.get_selected_paths()
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

            paths = self.get_selected_paths()
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
            self.__header_box.remove(self.__header_box.children()[-1])
        else:
            self.__lock.acquire()

            # Create a lock image and resize it so it fits the text size.
            label = self.__header_box.children()[0]
            height = label.create_pango_layout(
                label.get_text()).get_pixel_size()[-1]
            pixbuf = self.render_icon(
                gtk.STOCK_DIALOG_AUTHENTICATION, gtk.ICON_SIZE_MENU)
            pixbuf = pixbuf.scale_simple(
                height, height, gtk.gdk.INTERP_BILINEAR)
            image = gtk.image_new_from_pixbuf(pixbuf)
            self.__header_box.pack_start(image)
            self.__header_box.show_all()

        playlist_manager.update_playlist_lock_state()

    def locked(self):
        return self.__lock.locked()

    def enable_search(self):
        self.__entry.grab_focus()
        self.__cid = self.__entry.connect(
            "changed", self.__filter_parameters_changed)
        self.__filter_box.set_visible(True)

    def disable_search(self):
        self.__filter_box.set_visible(False)
        try:
            if self.__entry.handler_is_connected(self.__cid):
                self.__entry.disconnect(self.__cid)
        except AttributeError:
            pass
        self.__entry.delete_text(0, -1)
        # If the playlist was filtered, unfilter it. This happens implicitly
        # as we made sure the search entry is empty.
        if self.__mode & MODE_FILTERED:
            self.__filter()

    def sort(self, column_id, sort_order, scroll=False):
        for column in self.__treeview.get_columns():
            if column.id_ == column_id:
                break
        else:
            sort_order = None

        scroll_item, row_align, selected_items = self.__get_selection_and_row()

        items = (self.__items if self.__mode & MODE_FILTERED else
                 self.__all_items)
        if sort_order is None:
            self.__mode &= ~MODE_SORTED
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
                item.uri = uris[item.uri]
            except KeyError:
                pass

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
        current = playlist_manager.current
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
        # TODO: maintain a __stats dict() in each playlist that stores this
        #       info
        return (len(items), self.__size, self.__length)

    def update_icon(self, clear=False):
        model = self.__treeview.get_model()
        path = self.get_path_from_item(playlist_manager.current)
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
        current = playlist_manager.current
        item = self.get_item_from_path(path)
        order = blacfg.getint("general", "play.order")
        if (order == blaconst.ORDER_SHUFFLE and
            current != item and current is not None):
            self.__history.add(item, blaconst.TRACK_NEXT)
        playlist_manager.play_item(item)

    def add_selection_to_playlist(self, playlist, move):
        if not playlist.modification_allowed():
            return

        paths = self.get_selected_paths()
        items = self.get_items(paths, remove=move)
        if not items:
            return
        if not move:
            items = map(copy, items)
        playlist.add_items(items=items, select_rows=True)
        playlist_manager.focus_playlist(playlist)

    def send_to_queue(self):
        queue_n_items = queue.n_items
        if queue_n_items >= blaconst.QUEUE_MAX_ITEMS:
            return

        count = blaconst.QUEUE_MAX_ITEMS - queue_n_items
        model, selection = self.__treeview.get_selection().get_selected_rows()
        queue.queue_items([model[path][0] for path in selection[:count]])

    def remove_from_queue(self, treeview):
        model, selection = treeview.get_selection().get_selected_rows()
        queue.remove_items([model[path][0] for path in selection])

    def jump_to_playing_track(self):
        current = playlist_manager.current
        track = player.get_track()
        if current is None or track is None or current.uri != track.uri:
            return
        self.set_row(self.get_path_from_item(current))

    def set_row(self, path, paths=[], row_align=0.5):
        # Wrap the actual heavy lifting in gobject.idle_add. If we decorate the
        # instance method itself we can't use kwargs anymore which is rather
        # annoying for this particular method.
        @blautil.idle
        def set_row():
            if path is not None:
                self.__scroll_to_cell(path, row_align)
                self.__treeview.set_cursor(path)
            if paths:
                select_path = self.__treeview.get_selection().select_path
                map(select_path, paths)
        set_row()

    def get_selected_uris(self):
        paths = self.get_selected_paths()
        return [item.uri for item in self.get_items(paths)]

class BlaPlaylistManager(gtk.Notebook):
    __metaclass__ = blaview.BlaViewMeta("Playlists")

    __gsignals__ = {
        "play_track": blautil.signal(1),
        "selection_changed": blautil.signal(1)
    }

    def __init__(self):
        super(BlaPlaylistManager, self).__init__()

        self.current = None # Reference to the currently active playlist
        self.clipboard = [] # List of items after a cut/copy operation

        def new_playlist(type_):
            def wrapper(*args):
                self.new_playlist_from_type(type_)
            return wrapper
        actions = [
            ("AddNewPlaylist", None, "Add new playlist", "<Ctrl>T", "",
             lambda *x: self.add_playlist(focus=True)),
            ("RemovePlaylist", None, "Remove playlist", "<Ctrl>W", "",
             lambda *x: self.remove_playlist()),
            ("LockUnlockPlaylist", None, "Lock/Unlock playlist", None, "",
             self.toggle_lock_playlist),
            ("PlaylistFromSelection", None, "Selection", None, "",
             new_playlist(blaconst.PLAYLIST_FROM_SELECTION)),
            ("PlaylistFromArtists", None, "Selected artist(s)", None, "",
             new_playlist(blaconst.PLAYLIST_FROM_ARTISTS)),
            ("PlaylistFromAlbums", None, "Selected album(s)", None, "",
             new_playlist(blaconst.PLAYLIST_FROM_ALBUMS)),
            ("PlaylistFromAlbumArtists", None, "Selected album artist(s)",
             None, "", new_playlist(blaconst.PLAYLIST_FROM_ALBUM_ARTISTS)),
            ("PlaylistFromGenre", None, "Selected genre(s)", None, "",
             new_playlist(blaconst.PLAYLIST_FROM_GENRE)),
            ("Search", None, "_Search...", "<Ctrl>F", "",
             lambda *x: self.enable_search()),
            ("JumpToPlayingTrack", None, "_Jump to playing track", "<Ctrl>J",
             "", lambda *x: self.jump_to_playing_track())
        ]
        ui_manager.add_actions(actions)

        self.set_scrollable(True)

        # Set up DND support for the tab strip.
        self.drag_dest_set(gtk.DEST_DEFAULT_MOTION | gtk.DEST_DEFAULT_DROP,
                           blagui.DND_TARGETS.values(),
                           gtk.gdk.ACTION_COPY)

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
            self.emit("selection_changed", playlist.get_selected_uris())
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
            # overwrite self.current so we'll try to get a new song from a
            # playlist or the queue when we request to start playing again.
            if (state == blaconst.STATE_STOPPED and self.current and
                self.current.playlist is None):
                self.current = None
        player.connect("state_changed", state_changed)
        player.connect_object("get_track", BlaPlaylistManager.get_track, self)

        def library_updated(*args):
            self.get_current_playlist().invalidate_visible_rows()
        library.connect("library_updated", library_updated)

        self.show_all()

        blaplay.bla.register_for_cleanup(self)

    def __call__(self):
        self.save()

    def __drag_data_recv(self, drag_context, x, y, selection_data, info, time):
        # This gets called when DND operations end on the tab strip of the
        # notebook's tab strip.
        resolve = select = False

        # DND from the library browser
        if info == blagui.DND_LIBRARY:
            items = pickle.loads(selection_data.data)

        # DND from another playlist
        elif info == blagui.DND_PLAYLIST:
            paths, idx = pickle.loads(selection_data.data)
            playlist = self.get_nth_page(idx)
            items = playlist.get_items(paths=paths, remove=True)
            select = True

        # DND from the filebrowser or an external source
        elif info == blagui.DND_URIS:
            items = blautil.resolve_uris(selection_data.get_uris())
            # FIXME: Find a better solution than the resolve flag.
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
        elif blagui.is_accel(event, "Escape"):
            self.get_current_playlist().disable_search()
        return False

    def __query_name(self, title, default=""):
        diag = blaguiutils.BlaDialog(title=title)

        vbox = gtk.VBox(spacing=5)
        vbox.set_border_width(10)
        entry = gtk.Entry()
        entry.set_text(default)
        entry.connect("activate", lambda *x: diag.response(gtk.RESPONSE_OK))
        label = gtk.Label("Title:")
        label.set_alignment(xalign=0.0, yalign=0.5)
        vbox.pack_start(label)
        vbox.pack_start(entry)

        diag.vbox.pack_start(vbox)
        diag.show_all()

        # Run the dialog until we got a valid name or the user aborted.
        name = ""
        while True:
            response = diag.run()
            if response == gtk.RESPONSE_OK:
                name = entry.get_text()
                if not name.strip():
                    # FIXME: If this dialog is present when we quit we get a
                    #        weird assertion which doesn't seem to have
                    #        anything to do with this line, followed by a
                    #        segfault.
                    blaguiutils.error_dialog(
                        text="Invalid playlist name",
                        secondary_text="A playlist name must not consist "
                                        "exclusively of whitespace "
                                        "characters.")
                    continue
            break

        diag.destroy()
        return name

    def __rename_playlist(self, playlist):
        name = playlist.get_name()
        new_name = self.__query_name("Rename playlist", name)
        if new_name:
            playlist.set_name(new_name)

    def __open_popup(self, playlist, button, time, all_options=True):
        menu = gtk.Menu()

        items = [
            ("Add new playlist...",
             lambda *x: self.add_playlist(query_name=True, focus=True)),
            ("Remove playlist", lambda *x: self.remove_playlist(playlist)),
            ("Clear playlist", lambda *x: playlist.clear())
        ]

        for label, callback in items:
            m = gtk.MenuItem(label)
            m.connect("activate", callback)
            if not all_options:
                m.set_sensitive(False)
            menu.append(m)

        m = gtk.MenuItem("Rename playlist...")
        m.connect("activate",
                  lambda *x: self.__rename_playlist(playlist))
        if not all_options:
            m.set_sensitive(False)
        menu.append(m)

        try:
            label = "%s playlist" % ("Unlock" if playlist.locked() else "Lock")
        except AttributeError:
            pass
        else:
            m = gtk.MenuItem(label)
            m.connect("activate", lambda *x: playlist.toggle_lock())
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

    def update_playlist_lock_state(self):
        playlist = self.get_current_playlist()
        try:
            label = "%s playlist" % ("Unlock" if playlist.locked() else "Lock")
        except AttributeError:
            return
        self.__lock_button.set_tooltip_text(label)

        ui_manager.get_widget("/Menu/Edit/LockUnlockPlaylist").set_label(label)

    def get_active_playlist(self):
        try:
            playlist = self.current.playlist
        except AttributeError:
            playlist = None
        return playlist

    def get_current_playlist(self):
        return self.get_nth_page(self.get_current_page())

    def enable_search(self):
        if blacfg.getint("general", "view") == blaconst.VIEW_PLAYLISTS:
            self.get_current_playlist().enable_search()

    def open_playlist(self, path):
        name = os.path.basename(blautil.toss_extension(path))
        ext = blautil.get_extension(path).lower()

        if ext == "m3u":
            uris = self.__parse_m3u(path)
        elif ext == "pls":
            uris = self.__parse_pls(path)
        elif ext == "xspf":
            name, uris = self.__parse_xspf(path)
        else:
            blaguiutils.error_dialog(
                "Failed to open playlist \"%s\"" % path,
                "Only M3U, PLS, and XSPF playlists are supported.")
            return False
        if uris is None:
            return False

        uris = library.parse_ool_uris(blautil.resolve_uris(uris))
        if uris is None:
            return False
        playlist = self.add_playlist(focus=True, name=name)
        playlist.add_items(create_items_from_uris(uris))
        return True

    def save(self, path=None, type_="m3u", relative=False):
        @blautil.thread
        def save(path, type_):
            name = self.get_tab_label_text(self.get_current_playlist())
            uris = self.get_current_playlist().get_uris()

            ext = blautil.get_extension(path)
            if ext.lower() != type_:
                path = "%s.%s" % (path, type_)

            if type_.lower() == "pls":
                self.__save_pls(uris, path, relative)
            elif type_.lower() == "xspf":
                self.__save_xspf(uris, path, name)
            else:
                self.__save_m3u(uris, path, relative)

        if path is None:
            # TODO: Save the queue individually.
            print_i("Saving playlists")
            playlists = self.get_playlists()

            active_playlist = self.get_active_playlist()
            if active_playlist:
                current = active_playlist.get_path_from_item(self.current)
                active_playlist = self.page_num(active_playlist)
            else:
                active_playlist = current = None

            uris = set()
            for playlist in playlists:
                uris.update(playlist.get_uris(all_=True))
            library.save_ool_tracks(uris)
            blautil.serialize_to_file(
                (playlists, active_playlist, current, queue.get_queue()),
                blaconst.PLAYLISTS_PATH)
        else:
            save(path, type_)

    def init(self):
        print_i("Restoring playlists")

        try:
            playlists, active_playlist, current, queued_items = (
                blautil.deserialize_from_file(blaconst.PLAYLISTS_PATH))
        except (TypeError, ValueError):
            playlists = []

        if playlists:
            for playlist in playlists:
                self.append_page(playlist, playlist.get_header_box())

            if active_playlist is not None:
                self.set_current_page(active_playlist)
                playlist = self.get_nth_page(active_playlist)
            if current is not None:
                self.current = playlist.get_item_from_path(current)
                self.current.select()
            queue.restore(queued_items)
        else:
            self.add_playlist()

    def add_playlist(self, name=None, query_name=False, focus=False):
        if query_name:
            list_name = self.__query_name("Playlist name")
            if not list_name:
                return
        elif name:
            list_name = name
        else:
            indices = set()
            r = re.compile(r"(^bla \()([0-9]+)\)")
            for playlist in self:
                label = playlist.get_name()

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
        self.append_page(playlist, playlist.get_header_box())
        self.set_tab_reorderable(playlist, True)

        if focus:
            self.focus_playlist(playlist)

        return playlist

    def focus_playlist(self, playlist):
        self.set_current_page(self.page_num(playlist))

    def get_playlist_index(self, playlist):
        idx = self.page_num(playlist)
        if idx == -1:
            idx = None
        return idx

    def remove_playlist(self, playlist=None):
        if playlist is None:
            playlist = self.get_current_playlist()
        if not playlist.modification_allowed(check_filter_state=False):
            return

        if self.get_active_playlist() == playlist:
            try:
                self.current.playlist = None
            except AttributeError:
                pass
        playlist.clear()
        page_num = self.page_num(playlist)
        if page_num != -1:
            self.remove_page(page_num)

        if self.get_n_pages() < 1:
            self.add_playlist()

    def select(self, type_):
        self.get_current_playlist().select(type_)

    def cut(self, *args):
        self.clipboard = self.remove()
        ui_manager.update_menu(blaconst.VIEW_PLAYLISTS)

    def copy(self, *args):
        playlist = self.get_current_playlist()
        paths = playlist.get_selected_paths()
        self.clipboard = map(copy, playlist.get_items(paths))
        ui_manager.update_menu(blaconst.VIEW_PLAYLISTS)

    def paste(self, *args, **kwargs):
        playlist = self.get_current_playlist()
        if not playlist.modification_allowed():
            return
        playlist.add_items(items=self.clipboard, drop_info=-1, select_rows=True)

    def remove(self, *args):
        playlist = self.get_current_playlist()
        paths = playlist.get_selected_paths()
        return playlist.get_items(paths, remove=True)

    def clear(self, *args):
        self.get_current_playlist().clear()

    def toggle_lock_playlist(self, *args):
        self.get_current_playlist().toggle_lock()

    def new_playlist_from_type(self, type_):
        self.get_current_playlist().new_playlist_from_type(type_)

    def remove_duplicates(self):
        self.get_current_playlist().remove_duplicates()

    def remove_invalid_tracks(self):
        self.get_current_playlist().remove_invalid_tracks()

    def send_to_current_playlist(self, uris, resolve=False):
        playlist = self.get_current_playlist()
        if not playlist.modification_allowed():
            return

        if resolve:
            uris = library.parse_ool_uris(uris)
        if not uris:
            return

        try:
            self.current.clear_icon()
        except AttributeError:
            pass
        # Reset self.current to make sure the get_track() method will try to
        # request the next track from the currently visible playlist.
        self.current = None
        playlist.clear()
        playlist.add_items(create_items_from_uris(uris))
        self.get_track(blaconst.TRACK_NEXT, False)
        blaview.set_view(blaconst.VIEW_PLAYLISTS)

    def add_to_current_playlist(self, uris, resolve=False):
        playlist = self.get_current_playlist()
        if not playlist.modification_allowed():
            return

        if resolve:
            uris = library.parse_ool_uris(uris)
        if not uris:
            return

        playlist.add_items(create_items_from_uris(uris), select_rows=True)
        blaview.set_view(blaconst.VIEW_PLAYLISTS)

    def send_to_new_playlist(self, items, name="", resolve=False, select=False):
        # This is also invoked as response to DND operations on the notebook
        # tab strip. In this case we get BlaTrackListItem instances instead of
        # URIs which we need to preserve in order for their id()'s to remain
        # unchanged.

        if resolve:
            items = library.parse_ool_uris(items)
        if not items:
            return

        if not isinstance(items[0], BlaTrackListItem):
            items = create_items_from_uris(items)
        else:
            items = items

        playlist = self.add_playlist(name=name, focus=True)
        playlist.add_items(items, select_rows=select)
        blaview.set_view(blaconst.VIEW_PLAYLISTS)

    def update_statusbar(self, playlist=None):
        # This is called by BlaPlaylist instances to update the statusbar.

        if playlist is None:
            playlist = self.get_current_playlist()
        try:
            count, size, length_seconds = playlist.get_playlist_stats()
        except AttributeError:
            return

        if count == 0:
            info = ""
        else:
            info = parse_track_list_stats(count, size, length_seconds)
        BlaStatusbar.set_view_info(blaconst.VIEW_PLAYLISTS, info)

    def update_uris(self, uris):
        for playlist in self.get_playlists():
            playlist.update_uris(uris)

    def get_track(self, choice, force_advance):
        # This is called in response to BlaPlayer's get_track signal.

        item = None
        if choice not in [blaconst.TRACK_PREVIOUS, blaconst.TRACK_RANDOM]:
            item = queue.get_item()

        if item is None:
            playlist = self.get_active_playlist()
            if not playlist:
                playlist = self.get_current_playlist()
            item = playlist.get_item(choice, force_advance)

        self.play_item(item)

    def play_item(self, item):
        try:
            self.current.clear_icon()
        except AttributeError:
            pass

        self.current = item
        try:
            uri = item.uri
        except AttributeError:
            uri = None
        else:
            if blacfg.getboolean("general", "cursor.follows.playback"):
                item.select()
        self.emit("play_track", uri)

    def get_playlists(self):
        return map(None, self)

    def next(self):
        for playlist in self:
            yield playlist

    def jump_to_playing_track(self):
        playlist = self.get_active_playlist()
        if (blacfg.getint("general", "view") == blaconst.VIEW_PLAYLISTS and
            playlist == self.get_current_playlist()):
            playlist.jump_to_playing_track()

playlist_manager = BlaPlaylistManager()

# Defer importing the queue instance until the BlaPlaylistManager class
# object has been defined. This is necessary right now because the queue in
# turn requires an instance of the playlist manager in its c'tor.
from blaqueue import queue

