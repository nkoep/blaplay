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

from copy import copy as copyfunc
import cPickle as pickle
from random import randint
import re

import gobject
import gtk

from blaplay.blacore import blaconst
from blaplay import blagui, blautil
from .blaview import BlaView
from . import blatracklist
from .. import blaguiutil
from blaplay.formats._identifiers import *


# XXX: This class is too tightly bound to the concept of a track list. By
#      abstracting it better we could re-use it for the filesystem browser as
#      well.
class _History(gtk.ListStore):
    def __init__(self, playlist):
        super(_History, self).__init__(gobject.TYPE_PYOBJECT)
        self._playlist = playlist
        self._iterator = None

    def _peek(self):
        try:
            item = self[self._iterator][0]
        except TypeError:
            item = None
        return item

    def add(self, item, choice):
        if self._peek() == item:
            return

        if choice == blaconst.TRACK_NEXT:
            insert_func = self.insert_after
        else:
            insert_func = self.insert_before
        self._iterator = insert_func(self._iterator, [item])

    def get(self, choice):
        if choice == blaconst.TRACK_NEXT:
            f = self.iter_next
        elif choice == blaconst.TRACK_PREVIOUS:
            f = self._iter_previous

        # Iterate through the model until a valid reference to an item
        # in the playlist is found.
        while True:
            try:
                iterator = f(self._iterator)
            except TypeError:
                iterator = None

            if (iterator and
                not self._playlist.get_path_from_item(
                    self[iterator][0], all_=True)):
                self.remove(iterator)
                continue
            break

        if not iterator:
            item = None
        else:
            item = self[iterator][0]
            self._iterator = iterator

        return item

    def clear(self):
        super(_History, self).clear()
        self._iterator = None

    def _iter_previous(self, iterator):
        path = self.get_path(iterator)
        if path[0] > 0:
            return self.get_iter(path[0]-1)
        return None

class BlaPlaylist(blatracklist.BlaTrackList):
    ID = blaconst.VIEW_PLAYLIST

    def _configure_treeview(self):
        treeview = self._treeview
        treeview.connect_object(
            "drag-data-get", BlaPlaylist._on_drag_data_get, self)
        treeview.connect_object(
            "drag-data-received", BlaPlaylist._on_drag_data_received, self)
        treeview.connect("key-press-event", self._on_key_press_event)
        treeview.connect("popup", self._on_popup)
        def on_row_activated(treeview, path, column):
            self._play_item_at_path(path)
        treeview.connect("row-activated", on_row_activated)
        treeview.connect_object("sort-column", BlaPlaylist.sort, self)

        def on_column_layout_changed(_, column_ids):
            # XXX: Ugly, _config should be treated as "private" to the manager.
            self.manager._config.set_(
                "general", "columns.playlist", ", ".join(map(str, column_ids)))
            self.manager.update_playlist_layout()
        treeview.connect("column-layout-changed", on_column_layout_changed)

        # DND between playlists (includes playlist-internal DND)
        treeview.enable_model_drag_source(
            gtk.gdk.BUTTON1_MASK,
            [blagui.DND_TARGETS[blagui.DND_PLAYLIST],
             blagui.DND_TARGETS[blagui.DND_URIS]],
            gtk.gdk.ACTION_COPY)

        # Receive drag and drop
        treeview.enable_model_drag_dest(
            [blagui.DND_TARGETS[blagui.DND_LIBRARY]], gtk.gdk.ACTION_COPY)
        # XXX: We take this out for the time being.
        # treeview.enable_model_drag_dest(
        #     blagui.DND_TARGETS.values(), gtk.gdk.ACTION_COPY)

        treeview.set_model(gtk.ListStore(*self._MODEL_LAYOUT))

    def __init__(self, name, *args, **kwargs):
        super(BlaPlaylist, self).__init__(name, *args, **kwargs)

        self._state_icon = None
        self._history = _History(self)

        self._configure_treeview()
        self.refresh_column_layout()

        self.show()

    def __contains__(self, item):
        return item in self._all_items

    def _on_drag_data_get(self, drag_context, selection_data, info, time):
        paths = self.get_selected_paths()
        # if info == blagui.DND_PLAYLIST:
        #     # The `get_items' method already checks if we are allowed to modify
        #     # a playlist.
        #     items = self.get_items(paths=paths, remove=True)
        #     data = pickle.dumps(items, pickle.HIGHEST_PROTOCOL)
        #     selection_data.set("", 8, data)
        # elif info == blagui.DND_URIS:
        if info == blagui.DND_URIS:
            items = self.get_items_from_paths(paths)
            uris = blautil.filepaths2uris([item.uri for item in items])
            selection_data.set_uris(uris)

    def _on_drag_data_received(self, drag_context, x, y, selection_data, info,
                               time):
        if not self.can_modify():
            return

        data = None
        self._treeview.grab_focus()
        drop_info = self._treeview.get_dest_row_at_pos(x, y)

        # DND from the library browser
        if info == blagui.DND_LIBRARY:
            uris = pickle.loads(selection_data.data)
            items = self.manager.create_items_from_uris(uris)

        # # DND between playlists (this case includes playlist-internal DND)
        # elif info == blagui.DND_PLAYLIST:
        #     items = pickle.loads(selection_data.data)
        #     if drop_info:
        #         path, pos = drop_info
        #         item = self.get_item_from_path(path)
        #         # if (path in paths and
        #         #     idx == self.manager.get_playlist_index(self)):
        #         #     return
        #         path = self.get_path_from_item(item)
        #         drop_info = (path, pos)

        # DND from the filesystem browser or an external location
        elif info == blagui.DND_URIS:
            # XXX: Ugly!!
            uris = self.manager._library.parse_ool_uris(
                blautil.resolve_uris(selection_data.get_uris()))
            items = self.manager.create_items_from_uris(uris)

        # FIXME: If we don't add anything here GTK issues an assertion warning
        #        about a scrolling issue.
        if items:
            self.add_items(items, drop_info=drop_info, select_rows=True)

    def _create_new_playlist_from_type(self, type_):
        paths = self.get_selected_paths()
        items = self.get_items_from_paths(paths)

        if type_ == blaconst.PLAYLIST_FROM_SELECTION:
            uris = [item.uri for item in items]
        else:
            if type_ == blaconst.PLAYLIST_FROM_ARTISTS:
                column_id = blatracklist.COLUMN_ARTIST
            elif type_ == blaconst.PLAYLIST_FROM_ALBUMS:
                column_id = blatracklist.COLUMN_ALBUM
            elif type_ == blaconst.PLAYLIST_FROM_ALBUM_ARTISTS:
                column_id = blatracklist.COLUMN_ALBUM_ARTIST
            else:
                column_id = blatracklist.COLUMN_GENRE

            eval_ = blatracklist.COLUMNS[column_id].eval_track
            values = set()
            for item in items:
                values.add(eval_(item.track).lower())
            if not values:
                return

            r = re.compile(r"^(%s)$" % "|".join(values),
                           re.UNICODE | re.IGNORECASE)
            uris = [item.uri for item in self._get_visible_items()
                    if r.match(eval_(item.track))]

        self.manager.send_uris_to_new_playlist(uris)

    def _move_selection_to_playlist(self, playlist):
        if not playlist.can_modify():
            return
        paths = self.get_selected_paths()
        items = self.get_items(paths, remove=True)
        if not items:
            return
        playlist.add_items(items=items, select_rows=True)
        self.manager.request_focus_for_view(playlist)

    def _add_selection_to_playlist(self, playlist):
        if not playlist.can_modify():
            return
        paths = self.get_selected_paths()
        items = self.get_items(paths, remove=False)
        if not items:
            return
        items = map(copyfunc, items)
        playlist.add_items(items=items, select_rows=True)
        self.manager.request_focus_for_view(playlist)

    # def _queue_selection(self):
    #     queue_n_items = queue.n_items
    #     if queue_n_items >= blaconst.QUEUE_MAX_ITEMS:
    #         return
    #     limit = blaconst.QUEUE_MAX_ITEMS - queue_n_items
    #     paths = self.get_selected_paths()
    #     if paths:
    #         queue.add_items(self.get_items(paths[:limit]))

    # def _unqueue_selection(self):
    #     paths = self.get_selected_paths()
    #     if paths:
    #         queue.remove_items(self.get_items(paths[:limit]))

    def _add_context_menu_options(self, menu):
        # New playlist from...
        submenu = blaguiutil.BlaMenu()
        items = [
            ("selection", blaconst.PLAYLIST_FROM_SELECTION),
            ("selected artist(s)", blaconst.PLAYLIST_FROM_ARTISTS),
            ("selected album(s)", blaconst.PLAYLIST_FROM_ALBUMS),
            ("selected album artist(s)", blaconst.PLAYLIST_FROM_ALBUM_ARTISTS),
            ("selected genre(s)", blaconst.PLAYLIST_FROM_GENRE)
        ]
        for label, type_ in items:
            submenu.append_item(
                label, self._create_new_playlist_from_type, type_)
        menu.append_submenu("New playlist from...", submenu)

        playlists = self.manager.views
        multiple_playlists = len(playlists) > 1

        # Move to playlist
        submenu = blaguiutil.BlaMenu()
        for playlist in playlists:
            if playlist == self:
                continue
            submenu.append_item(
                playlist.name, self._move_selection_to_playlist, playlist)
        m = menu.append_submenu("Move to playlist...", submenu)
        m.set_sensitive(multiple_playlists)

        # Add to playlist
        submenu = blaguiutil.BlaMenu()
        for playlist in playlists:
            if playlist == self:
                continue
            submenu.append_item(
                playlist.name, self._add_selection_to_playlist, playlist)
        m = menu.append_submenu("Copy to playlist...", submenu)
        m.set_sensitive(multiple_playlists)

        menu.append_separator()

        # TODO
        # # Append queue-specific options.
        # items = [
        #     ("Add to queue", "Q", lambda *x: target.send_to_queue()),
        #     ("Remove from queue", "R",
        #      lambda *x: target.remove_from_queue(treeview)),
        # ]
        # for label, accel, callback in items:
        #     m = menu.append_item(label, callback)
        #     mod, key = gtk.accelerator_parse(accel)
        #     m.add_accelerator("activate", accel_group, mod, key,
        #                       gtk.ACCEL_VISIBLE)

    def _on_key_press_event(self, treeview, event):
        # TODO: Call this in the base class instead and let subclasses
        #       implement a self.remove method.
        def delete():
            paths = self.get_selected_paths()
            items = self.get_items(paths, remove=True)
            if self.manager.current_item in items:
                self.manager.current_item = None
        accels = [
            ("Delete", delete),
            # ("Q", lambda: self.send_to_queue()),
            # ("R", lambda: self.remove_from_queue(self._treeview)),
        ]
        for accel, callback in accels:
            if blagui.is_accel(event, accel):
                callback()
                return True
        return super(BlaPlaylist, self)._on_key_press_event(
            treeview, event)

    def _update_state_icon(self):
        model = self._treeview.get_model()
        path = self.get_path_from_item(self.manager.current_item)
        try:
            model[path][1] = self._state_icon
        except TypeError:
            pass
        self._header.set_icon_from_stock(self._state_icon)

    def refresh_column_layout(self):
        # XXX: Ugly, config considered "private" to the manager.
        column_ids = self.manager._config.getlistint(
            "general", "columns.playlist")
        if column_ids is None:
            # Define a sensible default column layout for playlists.
            names = ("PLAYING", "TRACK", "ARTIST", "TITLE", "ALBUM",
                     "DURATION")
            column_ids = [getattr(blatracklist, "COLUMN_%s" % name)
                          for name in names]
        self._treeview.add_columns(column_ids)

    def can_modify(self, check_filter_state=True):
        if self.locked():
            text = "The playlist is locked"
            secondary_text = "Unlock it first to modify its contents."
        elif check_filter_state and self._mode & blatracklist.MODE_FILTERED:
            text = "Error"
            secondary_text = "Cannot modify filtered playlists."
        else:
            text = secondary_text = ""

        if text and secondary_text:
            # Opening an error dialog after a double-click onto a row in the
            # library browser has a weird effect in that the treeview will
            # initiate a DND operation of the row once the dialog is destroyed.
            # Handling the dialog with gobject.idle_add resolves the issue.
            gobject.idle_add(blaguiutil.error_dialog, text, secondary_text)
            return False
        return True

    def sort(self, column_id, sort_order, scroll=False):
        for column in self._treeview.get_columns():
            if column.ID == column_id:
                break
        else:
            sort_order = None

        scroll_item, row_align, selected_items = self._get_selection_and_row()

        items = (self._items if self._mode & blatracklist.MODE_FILTERED else
                 self._all_items)
        if sort_order is None:
            self._mode &= ~blatracklist.MODE_SORTED
            sort_indicator = False
        else:
            self._mode |= blatracklist.MODE_SORTED
            sort_indicator = True

            reverse = sort_order == gtk.SORT_DESCENDING
            eval_ = blatracklist.COLUMNS[column_id].eval_track

            self._all_sorted = sorted(
                self._all_items,
                key=lambda item: eval_(item.track).lower(),
                reverse=reverse)
            items = sorted(
                items,
                key=lambda item: eval_(item.track).lower(),
                reverse=reverse)
            self._sorted = items

        if sort_order is not None:
            self._sort_parameters = (column_id, sort_order, sort_indicator)
        else:
            self._sort_parameters = None

        self._populate_model(scroll_item, row_align, selected_items)

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

        # XXX: Ugly!!
        order = self.manager._config.getint("general", "play.order")
        model = self._treeview.get_model()

        # Remove the playing icon from the old row.
        current_item = self.manager.current_item
        path = self.get_path_from_item(current_item)
        if path is not None:
            model[path][1] = None

        # If there are no tracks in the playlist, return.
        if not model.get_iter_first():
            return None

        item = None

        # Play the last active track (this applies to ORDER_REPEAT, too).
        if ((choice == blaconst.TRACK_PLAY or
            (order == blaconst.ORDER_REPEAT and not force_advance)) and
            current_item is not None):
            item = current_item
            self._history.add(item, choice)

        # Play request, but we didn't play a track from this playlist yet.
        elif choice == blaconst.TRACK_PLAY:
            if order == blaconst.ORDER_SHUFFLE:
                item = get_random()
                self._history.add(item, choice)
            else:
                item = model[0][0]

        elif choice == blaconst.TRACK_RANDOM:
            item = get_random()
            self._history.add(item, blaconst.TRACK_NEXT)

        # This is either TRACK_NEXT or TRACK_PREVIOUS with ORDER_SHUFFLE.
        elif order == blaconst.ORDER_SHUFFLE:
            item = self._history.get(choice)
            if item is None:
                item = get_random(current_item)
                self._history.add(item, choice)

        # This is either TRACK_NEXT or TRACK_PREVIOUS with ORDER_NORMAL.
        else:
            path = self.get_path_from_item(current_item)
            if path is None:
                path = (0,)
            else:
                if choice == blaconst.TRACK_NEXT:
                    path = (path[0]+1,)
                else:
                    path = (path[0]-1,) if path[0] > 0 else None

            item = self.get_item_from_path(path)

        return item

    def set_state_icons(self, stock_id):
        self._state_icon = stock_id
        self._update_state_icon()

    def jump_to_track(self, item):
        self.set_row(self.get_path_from_item(item))

