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

import gobject
import gtk
import pango
from random import randint
import urllib
from ConfigParser import ConfigParser
import xml.etree.cElementTree as ETree

import blaplay
player = blaplay.bla.player
from blaplay.blacore import blacfg, blaconst
from blaplay import blautil, blagui
from blaplay.formats._blatrack import BlaTrack
from blaplay.formats._identifiers import LENGTH, TITLE
from blaplay.blagui import blaguiutils


def parse_uri(uri):
    stations = []
    if isinstance(uri, unicode): uri = uri.encode("utf-8")
    ext = blautil.get_extension(uri).lower()
    if ext in ["m3u", "pls", "asx"]:
        f = urllib.urlopen(uri)

        if ext == "m3u":
            for line in f:
                line = line.strip()
                if line.startswith("http"):
                    stations.append(BlaRadioStation(uri, line))

        elif ext == "pls":
            parser = ConfigParser()
            parser.readfp(f)
            if "playlist" in parser.sections():
                kwargs = dict(parser.items("playlist"))
                entries = [key for key in kwargs.iterkeys()
                        if key.startswith("file")]
                stations.extend([BlaRadioStation(uri, kwargs[e])
                        for e in entries])

        elif ext == "asx":
            try: tree = ETree.ElementTree(None, f)
            except SyntaxError: pass
            else:
                iterator = tree.getiterator()
                for node in iterator:
                    keys = node.keys()
                    try: idx = map(str.lower, keys).index("href")
                    except ValueError: continue
                    location = node.get(keys[idx]).strip()
                    stations.append(BlaRadioStation(uri, location))

        f.close()

    elif uri: stations.append(BlaRadioStation(uri, uri))
    return stations

class BlaRadioStation(BlaTrack):
    def __init__(self, uri, location):
        # don't call BlaTrack's __init__ method as it'd try to parse tags from
        # a file. we just subclass BlaTrack to make sure that all methods and
        # properties any other track instance has are available for stations as
        # well
        self["uri"] = uri
        self["location"] = location
        self[LENGTH] = 0

    uri = property(lambda self: self["uri"])
    location = property(lambda self: self["location"])

class BlaRadio(gtk.VBox):
    __gsignals__ = {
        "count_changed": blautil.signal(2)
    }
    __current = None

    name = property(lambda self: "Internet Radio")

    def __init__(self):
        super(BlaRadio, self).__init__(spacing=3)

        hbox = gtk.HBox(spacing=3)

        entry = gtk.Entry()
        entry.connect(
                "activate", lambda *x: self.__add_station(entry.get_text()))
        hbox.pack_start(entry, expand=True)

        button = gtk.Button("Add")
        button.connect(
                "clicked", lambda *x: self.__add_station(entry.get_text()))
        hbox.pack_start(button, expand=False)

        button = gtk.Button("Remove")
        button.connect("clicked", self.__remove_stations)
        hbox.pack_start(button, expand=False)

        def open_(*args):
            diag = gtk.FileChooserDialog("Select files",
                    action=gtk.FILE_CHOOSER_ACTION_OPEN,
                    buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                    gtk.STOCK_OPEN, gtk.RESPONSE_OK)
            )
            diag.set_local_only(True)
            response = diag.run()
            filename = diag.get_filename()
            diag.destroy()

            if response == gtk.RESPONSE_OK and filename:
                filename = filename.strip()
                filename and self.__add_station(filename)

        button = gtk.Button("Open...")
        button.connect("clicked", open_)
        hbox.pack_start(button, expand=False)

        model = gtk.ListStore(gobject.TYPE_STRING, gobject.TYPE_PYOBJECT)
        self.__treeview = blaguiutils.BlaTreeViewBase()
        self.__treeview.set_model(model)
        self.__treeview.set_enable_search(True)
        self.__treeview.set_rubber_banding(True)
        self.__treeview.set_property("rules_hint", True)

        # playing column
        r = gtk.CellRendererPixbuf()
        self.__treeview.insert_column_with_attributes(
                -1, "Playing", r, stock_id=0)
        r.set_property("stock-size", gtk.ICON_SIZE_BUTTON)
        r.set_property("xalign", 0.5)
        self.__treeview.get_columns()[-1].set_alignment(0.5)

        # remaining columns
        def cell_data_func(column, renderer, model, iterator, identifier):
            renderer.set_property("text", model[iterator][1][identifier])

        columns = [
            ("Organization", "organization"), ("Station", "station"),
            ("URI", "uri"), ("Location", "location")
        ]
        for header, identifier in columns:
            r = gtk.CellRendererText()
            r.set_property("ellipsize", pango.ELLIPSIZE_END)
            c = gtk.TreeViewColumn(header)
            c.set_resizable(True)
            c.set_expand(True)
            c.pack_start(r)
            c.set_cell_data_func(r, cell_data_func, identifier)
            self.__treeview.append_column(c)

        sw = blaguiutils.BlaScrolledWindow()
        sw.set_shadow_type(gtk.SHADOW_IN)
        sw.add(self.__treeview)

        self.pack_start(hbox, expand=False)
        self.pack_start(sw, expand=True)

        self.__treeview.enable_model_drag_dest([
                ("radio", 0, 0),
                ("text/uri-list", 0, 1),
                ("text/plain", 0, 2),
                ("TEXT", 0, 3),
                ("STRING", 0, 4),
                ("COMPOUND_TEXT", 0, 5),
                ("UTF8_STRING", 0, 6)
                ],
                gtk.gdk.ACTION_COPY
        )
        self.__treeview.enable_model_drag_source(gtk.gdk.BUTTON1_MASK,
                [("radio", gtk.TARGET_SAME_WIDGET, 0)], gtk.gdk.ACTION_MOVE)
        self.__treeview.connect("drag_data_get", self.__drag_data_get)
        self.__treeview.connect("drag_data_received", self.__drag_data_recv)
        self.__treeview.connect("popup", self.__popup_menu)
        self.__treeview.connect("row_activated",
                lambda treeview, path, column: self.__get_station(path))
        self.__treeview.connect("key_press_event", self.__key_press_event)

        player.connect_object("get_station", BlaRadio.__get_station, self)
        player.connect_object("state_changed", BlaRadio.__update_rows, self)

        blaplay.bla.register_for_cleanup(self)
        self.show_all()

    def __call__(self):
        self.__save_stations()

    def __drag_data_get(self, treeview, drag_context, selection_data, info,
            time):
        self.__paths = treeview.get_selection().get_selected_rows()[-1]
        selection_data.set("radio", 8, "")

    def __drag_data_recv(self, treeview, drag_context, x, y,
            selection_data, info, time):
        treeview.grab_focus()
        drop_info = treeview.get_dest_row_at_pos(x, y)
        model = treeview.get_model()

        # in-playlist DND
        if info == 0:
            if drop_info:
                path, pos = drop_info
                iterator = model.get_iter(path)

                if (pos == gtk.TREE_VIEW_DROP_BEFORE or
                            pos == gtk.TREE_VIEW_DROP_INTO_OR_BEFORE):
                    move_before = model.move_before
                    f = lambda it: move_before(it, iterator)
                else:
                    move_after = model.move_after
                    f = lambda it: move_after(it, iterator)
                    self.__paths.reverse()
            else:
                iterator = None
                move_before = model.move_before
                f = lambda it: move_before(it, iterator)

            get_iter = model.get_iter
            iterators = map(get_iter, self.__paths)
            map(f, iterators)
            self.__paths = []
            self.__update_rows()

        # DND from an external location
        else:
            uris = selection_data.data.strip("\n\r\x00")
            resolve_uri = blautil.resolve_uri
            uris = map(resolve_uri, uris.replace("\r", "").split("\n"))
            map(self.__add_station, uris)

    def __update_rows(self):
        if not player.radio:
            model = self.__treeview.get_model()
            for row in model: row[0] = None
        else:
            station = player.get_track()
            model = self.__treeview.get_model()
            state = player.get_state()
            stock = (gtk.STOCK_MEDIA_PLAY if state == blaconst.STATE_PLAYING
                    else gtk.STOCK_MEDIA_PAUSE
                    if state == blaconst.STATE_PAUSED else None
            )
            for row in model:
                if row[1] == station:
                    row[0] = stock
                    model.row_changed(row.path, row.iter)
                    break

    def __add_station(self, uri):
        uri = uri.strip()
        try:
            stations = parse_uri(uri)
            if not stations: return
        except IOError:
            blaguiutils.error_dialog(
                    "Invalid URL", "Failed to open location %s." % uri)
        else:
            model = self.__treeview.get_model()
            iterators = [model.append([None, station])
                    for station in stations]
            self.emit("count_changed",
                    blaconst.VIEW_RADIO, model.iter_n_children(None))
            self.__treeview.set_cursor(model.get_path(iterators[0]))
            select_path = self.__treeview.get_selection().select_path
            map(select_path, map(model.get_path, iterators))

    def __remove_stations(self, *args):
        model, paths = self.__treeview.get_selection().get_selected_rows()
        map(model.remove, map(model.get_iter, paths))

        # check if we removed the current station
        if not self.__current: return
        for row in model:
            if row[1] == self.__current: break
        else: self.__current = None

    def __save_stations(self):
        stations = [row[1] for row in self.__treeview.get_model()]
        blautil.serialize_to_file(
                [self.__current, stations], blaconst.STATIONS_PATH)

    def __popup_menu(self, treeview, event):
        try: path = treeview.get_path_at_pos(*map(int, [event.x, event.y]))
        except TypeError: return False

        menu = gtk.Menu()
        m = gtk.MenuItem("Remove")
        mod, key = gtk.accelerator_parse("Delete")
        m.add_accelerator(
                "activate", blagui.accelgroup, mod, key, gtk.ACCEL_VISIBLE)
        m.connect("activate", self.__remove_stations)
        menu.append(m)
        menu.show_all()
        menu.popup(None, None, None, event.button, event.time)

    def __get_station(self, choice):
        def get_random(old=None):
            idx_max = model.iter_n_children(None)-1
            path = randint(0, idx_max)
            if old is not None and idx_max > 0:
                while path == old[0]: path = randint(0, idx_max)
            return (path,)

        model = self.__treeview.get_model()
        for row in model: row[0] = None
        path = (0,)

        # choice can either be a direction constant as defined in blaconst if
        # the method is invoked as player callback or a treemodel path if it's
        # invoked as row_activated callback on the treeview
        if not isinstance(choice, tuple):
            if not model.iter_n_children(None):
                return player.play_station(None)

            if self.__current:
                for row in model:
                    if row[1] == self.__current:
                        path = row.path
                        break

            order = blacfg.getint("general", "play.order")
            if choice == blaconst.TRACK_RANDOM: path = get_random()
            elif order == blaconst.ORDER_SHUFFLE: path = get_random(path)
            else:
                if choice == blaconst.TRACK_NEXT:
                    iterator = model.iter_next(model.get_iter(path))
                    if not iterator: return player.play_station(None)
                    path = model.get_path(iterator)
                elif choice == blaconst.TRACK_PREVIOUS:
                    if path[0] < 1: return player.play_station(None)
                    path = (path[0]-1,)
        else: path = choice

        self.__treeview.set_cursor(path)
        self.__current = model[path][1]
        player.play_station(self.__current)

    def __key_press_event(self, treeview, event):
        if blagui.is_accel(event, "Delete"): self.__remove_stations()
        return False

    def restore(self):
        try:
            self.__current, stations = blautil.deserialize_from_file(
                  blaconst.STATIONS_PATH)
        except TypeError: return
        model = self.__treeview.get_model()
        [model.append([None, station]) for station in stations]
        if self.__current:
            for row in model:
                if row[1] == self.__current:
                    self.__treeview.set_cursor(row.path)
                    break
        self.emit("count_changed",
                blaconst.VIEW_RADIO, model.iter_n_children(None))

