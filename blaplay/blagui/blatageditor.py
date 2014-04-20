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
import re
from time import ctime
from copy import deepcopy

import gobject
import gtk
import pango

import blaplay
library = blaplay.bla.library
from blaplay.blacore import blaconst
from blaplay import blautil, blagui
from blaplay.formats._blatrack import BlaTrack
from blaplay.formats._identifiers import *
from blawindows import BlaWindow, BlaScrolledWindow
import blaguiutil


class BlaMetadataViewer(gtk.VBox):
    __gsignals__= {
        "value_changed": blautil.signal(2)
    }

    class TreeView(blaguiutil.BlaTreeViewBase):
        def __init__(self, *args, **kwargs):
            self.__is_editable = kwargs.pop("is_editable", False)
            super(BlaMetadataViewer.TreeView, self).__init__(*args, **kwargs)

            def row_activated(treeview, path, column):
                if not treeview.get_selection().path_is_selected(path):
                    return True
                treeview.set_cursor(path, treeview.get_columns()[-1],
                                    start_editing=True)
            self.connect("row_activated", row_activated)

        def _button_press_event(self, treeview, event):
            x, y = map(int, [event.x, event.y])
            try:
                path = self.get_path_at_pos(x, y)[0]
            except TypeError:
                path = None

            if (event.button == 1 and event.type == gtk.gdk.BUTTON_PRESS and
                path is not None and
                self.get_selection().path_is_selected(path)):
                return False

            if path is None:
                self.grab_focus()
            return super(BlaMetadataViewer.TreeView, self)._button_press_event(
                treeview, event)

    def __init__(self, is_editable, playlist_manager):
        super(BlaMetadataViewer, self).__init__(
            spacing=blaconst.WIDGET_SPACING)

        model = gtk.ListStore(gobject.TYPE_PYOBJECT, gobject.TYPE_PYOBJECT)

        self._treeview = BlaMetadataViewer.TreeView(
            model, is_editable=is_editable)
        self._treeview.set_reorderable(False)
        self._treeview.set_rubber_banding(True)
        self._treeview.set_property("rules_hint", True)

        # Name column
        r = gtk.CellRendererText()
        self._treeview.insert_column_with_data_func(
            -1, "Name", r, self.__cdf_name)

        # Value column
        r = gtk.CellRendererText()
        r.set_property("ellipsize", pango.ELLIPSIZE_END)
        r.set_property("editable", is_editable)
        self._treeview.insert_column_with_data_func(
            -1, "Value", r, self.__cdf_value)
        if is_editable:
            def editing_started(renderer, editable, path):
                self._treeview.set_cursor(path)
                model = self._treeview.get_model()
                # Remove the "Varies between tracks" label.
                if model[path][1] is None:
                    editable.set_text("")
            r.connect("editing_started", editing_started)
            def edited(renderer, path, text):
                row = self._treeview.get_model()[path]
                identifier = row[0]
                if row[1] != text:
                    row[1] = text
                    self.emit("value_changed", identifier, text)
            r.connect("edited", edited)

        for column in self._treeview.get_columns():
            column.set_sizing(gtk.TREE_VIEW_COLUMN_AUTOSIZE)

        # Wrap the treeview.
        sw = BlaScrolledWindow()
        sw.add(self._treeview)

        self._pb = gtk.ProgressBar()
        self._pb.set_visible(False)

        self.pack_start(sw, expand=True)
        self.pack_start(self._pb, expand=False)

        playlist_manager.connect_object(
            "selection_changed", BlaMetadataViewer._update_model, self)

        self._uris = []

        sw.show_all()
        self.show()

    def _populate_model(self, model):
        pass

    def _update_model(self, uris):
        model = self._treeview.get_model()
        model.clear()

        self._uris = uris
        if not self._uris:
            return

        sw = self.get_children()[0]
        if len(uris) > blaconst.TAG_EDITOR_MAX_ITEMS:
            if sw.child == self._treeview:
                sw.remove(self._treeview)
                viewport = gtk.Viewport()
                viewport.add(gtk.Label("Too many items selected"))
                viewport.set_shadow_type(gtk.SHADOW_NONE)
                viewport.show_all()
                sw.add(viewport)
            return
        else:
            if sw.child != self._treeview:
                sw.remove(sw.child)
                sw.add(self._treeview)

        self._populate_model(model)

    def __cdf_name(self, column, renderer, model, iterator):
        identifier = model[iterator][0]
        try:
            text = IDENTIFIER_LABELS[identifier]
        except TypeError:
            text = "<%s>" % identifier.upper()
        renderer.set_property("text", text)

    def __cdf_value(self, column, renderer, model, iterator):
        value = model[iterator][1]
        if value is None:
            renderer.set_property("markup", "<i>Varies between tracks</i>")
        else:
            renderer.set_property("text", value)

class BlaTagEditor(BlaMetadataViewer):
    def __init__(self, playlist_manager):
        super(BlaTagEditor, self).__init__(is_editable=True,
                                           playlist_manager=playlist_manager)

        def key_press_event(treeview, event):
            if blagui.is_accel(event, "Delete"):
                model, paths = treeview.get_selection().get_selected_rows()
                identifiers = [model[path][0] for path in paths]
                if identifiers:
                    self.__delete_tags(identifiers)

        self._treeview.connect("key_press_event", key_press_event)
        self._treeview.connect_object("popup", BlaTagEditor.__popup, self)
        self.connect_object("value_changed", BlaTagEditor.__set_value, self)

        self.__hbox = gtk.HBox()
        buttons = [
            ("Undo changes", gtk.STOCK_UNDO, BlaTagEditor.__undo),
            ("Apply changes", gtk.STOCK_OK, BlaTagEditor.__apply)
        ]
        for tooltip, stock, callback in buttons:
            button = gtk.Button()
            button.set_tooltip_text(tooltip)
            button.set_relief(gtk.RELIEF_NONE)
            button.set_focus_on_click(False)
            button.add(
                gtk.image_new_from_stock(stock, gtk.ICON_SIZE_MENU))
            style = gtk.RcStyle()
            style.xthickness = style.ythickness = 0
            button.modify_style(style)
            button.connect_object("clicked", callback, self)
            self.__hbox.pack_start(button)
        self.__hbox.set_sensitive(False)

        self._modified = blautil.BlaNotifyDict()
        def callback(dict_):
            self.__hbox.set_sensitive(len(dict_) != 0)
        self._modified.connect(callback)

    def _populate_model(self, model):
        tracks = [self._modified.get(uri, library[uri])
                  for uri in iter(self._uris)]

        # The standard tags
        for identifier in IDENTIFIER_TAGS:
            value = tracks[0][identifier]
            for track in tracks[1:]:
                if value != track[identifier]:
                    value = None
                    break
            if identifier == DATE:
                try:
                    value = value.split("-")[0]
                except AttributeError:
                    pass
            model.append([identifier, value])

        # Additional tags
        additional_tags = set()
        update = additional_tags.update
        keys_additional_tags = BlaTrack.keys_additional_tags
        map(update, map(keys_additional_tags, tracks))

        for tag in additional_tags:
            try:
                value = tracks[0][tag]
            except KeyError:
                value = None

            for track in tracks[1:]:
                try:
                    next_value = track[tag]
                except KeyError:
                    next_value = None
                if value != next_value:
                    value = None
                    break
            model.append([tag, value])

    def __add_tag(self, *args):
        diag = blaguiutil.BlaDialog(title="Add tag")
        diag.set_size_request(250, -1)

        table = gtk.Table(columns=2, rows=2, homogeneous=False)
        entry_name = gtk.Entry()
        entry_value = gtk.Entry()

        idx = 0
        for label, entry in [("Name", entry_name), ("Value", entry_value)]:
            table.attach(gtk.Label("%s:" % label), 0, 1, idx, idx+1)
            table.attach(entry, 1, 2, idx, idx+1, xpadding=5)
            idx += 1
        diag.vbox.set_border_width(10)
        diag.vbox.pack_start(table)
        diag.show_all()
        response = diag.run()

        if response == gtk.RESPONSE_OK:
            name = entry_name.get_text()
            value = entry_value.get_text()
            if name not in IDENTIFIER_TAGS:
                self.__set_value(name, value)
        diag.destroy()

    def __update_model_and_restore_selection(self):
        try:
            cursor_path, column = self._treeview.get_cursor()
        except TypeError:
            cursor_path = column = None
        selection = self._treeview.get_selection()
        model, paths = selection.get_selected_rows()
        ids = [model[path][0] for path in paths]
        # TODO: Only update the model if a field was removed or added.
        self._update_model(self._uris)
        paths = [row.path for row in model if row[0] in ids]
        if cursor_path is not None:
            self._treeview.set_cursor(cursor_path, column)
        map(selection.select_path, paths)

    def __set_value(self, identifier, value):
        for uri in iter(self._uris):
            if not self._modified.has_key(uri):
                # copy-on-write
                self._modified[uri] = deepcopy(library[uri])
            self._modified[uri][identifier] = value

        self.__update_model_and_restore_selection()

    def __delete_tags(self, identifiers):
        for uri in iter(self._uris):
            if not self._modified.has_key(uri):
                # copy-on-write
                self._modified[uri] = deepcopy(library[uri])
            for identifier in identifiers:
                del self._modified[uri][identifier]

        self.__update_model_and_restore_selection()

    def __capitalize(self, identifiers):
        def capitalize(s):
            return re.sub(r"(^|\s)(\S)",
                          lambda m: m.group(1) + m.group(2).upper(), s)

        for uri in iter(self._uris):
            try:
                track = self._modified[uri]
            except KeyError:
                track = library[uri]
            for identifier in identifiers:
                value = capitalize(track[identifier])
                if value != track[identifier]:
                    if not self._modified.has_key(uri):
                        # copy-on-write
                        self._modified[uri] = deepcopy(track)
                    self._modified[uri][identifier] = value

        self.__update_model_and_restore_selection()

    def __popup(self, event):
        menu = gtk.Menu()
        m = gtk.MenuItem("Add tag...")
        m.connect("activate", self.__add_tag)
        menu.append(m)

        try:
            path, column, x, y = self._treeview.get_path_at_pos(
                *map(int, [event.x, event.y]))
        except TypeError:
            pass
        else:
            model, paths = self._treeview.get_selection().get_selected_rows()
            identifiers = [model[path][0] for path in paths]
            items = [
                ("Delete tag", "Delete",
                 lambda *x: self.__delete_tags(identifiers)),
                ("Capitalize", None, lambda *x: self.__capitalize(identifiers))
            ]
            accel_group = blagui.get_accelerator_group(self)
            for label, accel, callback in items:
                m = gtk.MenuItem(label)
                if accel:
                    mod, key = gtk.accelerator_parse(accel)
                    m.add_accelerator("activate", accel_group, mod, key,
                                      gtk.ACCEL_VISIBLE)
                m.connect("activate", callback)
                menu.append(m)

        menu.show_all()
        menu.popup(None, None, None, event.button, event.time)

    def __apply(self):
        if len(self._modified) == 0:
            return

        self._pb.set_visible(True)
        unit = 1.0 / len(self._modified)
        idx = 0
        succeeded = 0
        for uri, track in self._modified.iteritems():
            self._pb.set_fraction(unit * (idx+1))
            self._pb.set_text(uri)
            library[uri] = track
            succeeded += int(track.save())
            idx += 1
        self._pb.set_visible(False)

        library.sync()

        self._update_model(self._uris)

        n_modified = len(self._modified)
        if n_modified > 0 and succeeded != n_modified:
            blaguiutil.warning_dialog(
                "Failed to write tags for %d of %d files." %
                ((n_modified-succeeded), n_modified))
        self._modified.clear()

    def __undo(self):
        self._modified.clear()
        self.__update_model_and_restore_selection()

    def get_control_widget(self):
        return self.__hbox

class BlaProperties(BlaMetadataViewer):
    def __init__(self, playlist_manager):
        super(BlaProperties, self).__init__(is_editable=False,
                                            playlist_manager=playlist_manager)

    def _populate_model(self, model):
        def get_value(track, identifier):
            if not track[identifier] and identifier != MONITORED_DIRECTORY:
                return None
            elif identifier == FILESIZE:
                value = track.get_filesize()
            elif identifier == MTIME:
                value = ctime(track[MTIME])
            elif identifier == LENGTH:
                value = track.duration
            elif identifier == BITRATE:
                value = track.bitrate
            elif identifier == SAMPLING_RATE:
                value = track.sampling_rate
            elif identifier == CHANNELS:
                value = str(track[CHANNELS])
            else:
                value = track[identifier]
            return value

        tracks = [library[uri] for uri in iter(self._uris)]

        for identifier in IDENTIFIER_PROPERTIES:
            value = get_value(tracks[0], identifier)
            for track in tracks[1:]:
                if value != get_value(track, identifier):
                    value = None
                    break
            model.append([identifier, value])

