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
import cPickle as pickle
import re

import gobject
import gtk

import blaplay
ui_manager = blaplay.bla.ui_manager
from blaplay.blacore import blaconst, blacfg
from blaplay import blagui
from blaplay.formats._identifiers import *
from blawindows import BlaScrolledWindow
from blatracklist import (
    COLUMN_ARTIST, COLUMN_ALBUM, COLUMN_ALBUM_ARTIST, COLUMN_GENRE, popup,
    update_columns, parse_track_list_stats, BlaTreeView, BlaTrackListItem)
from blastatusbar import BlaStatusbar
from blaview import BlaViewMeta
from blaplaylist import playlist_manager


class BlaQueue(BlaScrolledWindow):
    __metaclass__ = BlaViewMeta("Queue")

    __layout = (
        gobject.TYPE_PYOBJECT,  # An instance of BlaTrackListItem
        gobject.TYPE_STRING     # Position in the queue
    )

    def __init__(self):
        super(BlaQueue, self).__init__()

        self.__size = 0
        self.__length = 0
        self.clipboard = []

        self.__treeview = BlaTreeView(view_id=blaconst.VIEW_QUEUE)
        self.__treeview.set_model(gtk.ListStore(*self.__layout))
        self.__treeview.set_enable_search(False)
        self.__treeview.set_property("rules_hint", True)

        self.set_shadow_type(gtk.SHADOW_IN)
        self.add(self.__treeview)

        self.__treeview.enable_model_drag_dest(
            [("queue", gtk.TARGET_SAME_WIDGET, 3)], gtk.gdk.ACTION_COPY)
        self.__treeview.enable_model_drag_source(
            gtk.gdk.BUTTON1_MASK,
            [("queue", gtk.TARGET_SAME_WIDGET, 3)],
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

        # TODO: factor this out so we can use the same for the playlist
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

    def __add_items(self, items, path=None, select_rows=False):
        treeview = self.__treeview
        model = treeview.get_model()
        iterator = None

        try:
            if (not treeview.get_selection().get_selected_rows()[-1] or
                path == -1):
                raise TypeError
            if not path:
                path, column = treeview.get_cursor()
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
            treeview.freeze_notify()
            selection = treeview.get_selection()
            selection.unselect_all()
            select_path = selection.select_path
            map(select_path, xrange(path[0], path[0] + len(items)))
            treeview.thaw_notify()

        self.update_queue_positions()

    def __get_items(self, remove=True):
        treeview = self.__treeview
        model, selections = treeview.get_selection().get_selected_rows()
        if selections:
            get_iter = model.get_iter
            iterators = map(get_iter, selections)
            items = [model[iterator][0] for iterator in iterators]
            if remove:
                remove = model.remove
                map(remove, iterators)
                self.update_queue_positions()
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
            info = parse_track_list_stats(count, self.__size, self.__length)
        BlaStatusbar.set_view_info(blaconst.VIEW_QUEUE, info)

    def select(self, type_):
        treeview = self.__treeview
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

    def update_queue_positions(self):
        model = self.__treeview.get_model()

        # Update the position labels for our own treeview.
        for idx, row in enumerate(model):
            model[row.path][1] = idx+1

        # Invalidate the visible rows of the current playlists so the
        # position labels also get updated in playlists.
        playlist = playlist_manager.get_current_playlist()
        playlist.invalidate_visible_rows()

        # Calculate size and length of the queue and update the statusbar.
        size = length = 0
        for row in model:
            track = row[0].track
            size += track[FILESIZE]
            length += track[LENGTH]
        self.__size, self.__length = size, length
        self.emit("count_changed", blaconst.VIEW_QUEUE, self.n_items)
        self.update_statusbar()

    def get_queue_positions(self, item):
        model = self.__treeview.get_model()
        return [row[1] for row in model if row[0] == item]

    def queue_items(self, items):
        if not items:
            return

        # If any of the items is not an instance of BlaTrackListItem it means
        # all of the items are actually just URIs which stem from the library
        # browser and are not part of a playlist.
        if not isinstance(items[0], BlaTrackListItem):
            items = map(BlaTrackListItem, items)

        count = blaconst.QUEUE_MAX_ITEMS - self.n_items
        self.__add_items(items[:count], path=-1)

    def remove_items(self, items):
        # This is invoked by playlists who want to remove tracks from the
        # queue.
        model = self.__treeview.get_model()
        for row in model:
            if row[0] in items:
                model.remove(row.iter)
        self.update_queue_positions()

    def get_queue(self):
        queue = []
        playlists = playlist_manager.get_playlists()

        for row in self.__treeview.get_model():
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

    def restore(self, items):
        print_i("Restoring the play queue")

        if not items:
            return

        playlists = playlist_manager.get_playlists()

        for idx, item in enumerate(items):
            try:
                playlist_idx, path = item
            except ValueError:
                # Library tracks that are not part of a playlist.
                item = BlaTrackListItem(item)
            else:
                item = playlists[playlist_idx].get_item_from_path(path)
            items[idx] = item

        self.queue_items(items)

    def cut(self, *args):
        self.clipboard = self.__get_items(remove=True)

    def copy(self, *args):
        # We specifically don't create actual copies of items here as it's not
        # desired to have unique ones in the queue. Copied and pasted tracks
        # should still refer to the same BlaTrackListItem instances which are
        # possibly part of a playlist.
        self.clipboard = self.__get_items(remove=False)

    def paste(self, *args, **kwargs):
        self.__add_items(items=self.clipboard, select_rows=True)

    def remove(self, *args):
        self.__get_items(remove=True)

    def clear(self):
        self.__treeview.get_model().clear()
        self.update_queue_positions()

    def get_item(self):
        model = self.__treeview.get_model()
        iterator = model.get_iter_first()
        if iterator:
            item = model[iterator][0]
            model.remove(iterator)
            self.update_queue_positions()
            return item
        return None

    @property
    def n_items(self):
        return len(self.__treeview.get_model())

queue = BlaQueue()

