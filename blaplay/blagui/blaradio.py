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

import gobject
import gtk
import pango
import urllib

import blaplay
from blaplay import blaconst, blautils, blaplayer, blagui
player = blaplayer.player
from blaplay.formats._blatrack import BlaTrack
from blaplay.formats._identifiers import SAMPLING_RATE, LENGTH
from blaplay.blagui import blaguiutils


def parse_uri(uri):
    stations = []
    ext = blautils.get_extension(uri).lower()
    if ext in ["m3u", "pls", "asx"]:
        f = urllib.urlopen(uri)

        if ext == "m3u":
            for line in f:
                print line

        elif ext == "pls":
            for line in f:
                line = line.strip()
                if line.lower().startswith("file"):
                    try: line = line[line.index("=")+1:].strip()
                    except ValueError: pass
                    else: uris.append(line)

        elif ext == "asx":
            import xml.etree.cElementTree as ETree
            tree = ETree.ElementTree(None, f)
            iterator = tree.getiterator()
            for node in iterator:
                keys = node.keys()
                try: idx = map(str.lower, node.keys()).index("href")
                except ValueError: continue
                location = node.get(keys[idx]).strip()
                stations.append(BlaRadioStation(uri, location))

        f.close()

    else: stations.append(BlaRadioStation(uri, uri))

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
        "count_changed": blaplay.signal(2)
    }

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

        model = gtk.ListStore(gobject.TYPE_PYOBJECT)
        self.__treeview = blaguiutils.BlaTreeViewBase()
        self.__treeview.set_model(model)
        self.__treeview.set_enable_search(True)
        self.__treeview.set_rubber_banding(True)
        self.__treeview.set_property("rules_hint", True)

        def cell_data_func(column, renderer, model, iterator, identifier):
            renderer.set_property("text", model[iterator][0][identifier])

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

        self.__treeview.connect("popup", self.__popup_menu)
        self.__treeview.connect("row_activated", self.__play_station)
        self.__treeview.connect("key_press_event", self.__key_press_event)

        player.connect("state_changed", self.__update_rows)

        gtk.quit_add(0, self.__save_stations)
        self.show_all()

    def __update_rows(self, player):
        if not player.radio: return
        station = player.get_track()
        model = self.__treeview.get_model()
        for row in model:
            if row[0] == station:
                model.row_changed(row.path, row.iter)
                break

    def __add_station(self, uri):
        uri = uri.strip()
        try: stations = parse_uri(uri)
        except IOError:
            blaguiutils.error_dialog(
                    "Invalid URL", "Failed to open location %s." % uri)
        else:
            model = self.__treeview.get_model()
            [model.append([station]) for station in stations]
            self.emit("count_changed",
                    blaconst.VIEW_RADIO, model.iter_n_children(None))

    def __remove_stations(self, *args):
        model, paths = self.__treeview.get_selection().get_selected_rows()
        map(model.remove, map(model.get_iter, paths))

    def __save_stations(self):
        stations = [row[0] for row in self.__treeview.get_model()]
        blautils.serialize_to_file(stations, blaconst.STATIONS_PATH)
        return 0

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

    def __play_station(self, treeview, path, column):
        player.play_station(self.__treeview.get_model()[path][0])

    def __key_press_event(self, treeview, event):
        if blagui.is_accel(event, "Delete"): self.__remove_stations()
        return False

    def restore(self):
        stations = blautils.deserialize_from_file(blaconst.STATIONS_PATH)
        if not stations: return
        model = self.__treeview.get_model()
        [model.append([station]) for station in stations]
        self.emit("count_changed",
                blaconst.VIEW_RADIO, model.iter_n_children(None))

