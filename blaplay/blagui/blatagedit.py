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
from blaplay import blautil, blagui
from blaplay.blagui import blaguiutils
from blaplay.formats._blatrack import BlaTrack
from blaplay.formats._identifiers import *


class BlaTreeView(gtk.TreeView):
    __gsignals__ = {
        "popup": blautil.signal(1),
        "set_value": blautil.signal(2),
        "delete_tags": blautil.signal(1)
    }

    def __init__(self, *args, **kwargs):
        self.__allow_no_selection = kwargs.pop("allow_no_selection", True)
        self.__is_editable = kwargs.pop("is_editable", False)
        super(BlaTreeView, self).__init__(*args, **kwargs)

        if not self.__allow_no_selection: self.set_rubber_banding(True)
        self.set_enable_search(False)
        self.connect_object("button_press_event",
                BlaTreeView.__button_press_event, self)
        self.connect_object("button_release_event",
                BlaTreeView.__button_release_event, self)
        self.connect_object("key_press_event",
                BlaTreeView.__key_press_event, self)
        self.get_selection().set_mode(gtk.SELECTION_MULTIPLE)
        self.__pending_event = None

    def __key_press_event(self, event):
        if blagui.is_accel(event, "Delete"):
            model, paths = self.get_selection().get_selected_rows()
            identifiers = [model[path][0] for path in paths]
            self.emit("delete_tags", identifiers)

    def __button_press_event(self, event):
        selection = self.get_selection()
        x, y = map(int, [event.x, event.y])
        try: path, column, cellx, celly = self.get_path_at_pos(x, y)
        except TypeError:
            if event.button == 3: self.emit("popup", event)
            if self.__allow_no_selection: selection.unselect_all()
            return False

        self.grab_focus()
        if event.button in [1, 2]:

            selection = self.get_selection()
            r = column.get_cell_renderers()[0]

            if ((selection.path_is_selected(path) or
                    event.type == gtk.gdk._2BUTTON_PRESS) and
                    column == self.get_column(1)):
                if not r.get_property("editing"):
                    r.set_property("editable", self.__is_editable and True)
                    self.set_cursor_on_cell(path, focus_column=column,
                        focus_cell=r, start_editing=True)
                    selection.set_select_function(lambda *args: True)
                return True
            else:
                if self.__allow_no_selection:
                    if (event.state &
                            (gtk.gdk.CONTROL_MASK | gtk.gdk.SHIFT_MASK)):
                        self.__pending_event = None
                        selection.set_select_function(lambda *args: True)
                    else:
                        if not r.get_property("editing"):
                            try: text = self.__editable.get_text()
                            except AttributeError: pass
                            else: r.emit("edited", path, text)
                            r.set_property("editable", False)
                elif (selection.path_is_selected(path) and
                        selection.count_selected_rows() == 1 and
                        event.state & gtk.gdk.CONTROL_MASK):
                    return True

        else: # event.button == 3
            if not selection.path_is_selected(path):
                self.set_cursor(path, column, 0)
            else: column.focus_cell(column.get_cell_renderers()[0])
            self.emit("popup", event)
            return True

        return False

    def __button_release_event(self, event):
        try: r = self.get_columns()[1].get_cell_renderers()[0]
        except IndexError: pass
        else: return False

        if self.__pending_event:
            selection = self.get_selection()
            oldevent = self.__pending_event
            self.__pending_event = None
            selection.set_select_function(lambda *x: True)
            safezone = 10
            if not (oldevent[0]-safezone <= event.x <= oldevent[0]+safezone and
                    oldevent[1]-safezone <= event.y <= oldevent[1]+safezone):
                return True
            x, y = map(int, [event.x, event.y])
            try: path, column, cellx, celly = self.get_path_at_pos(x, y)
            except TypeError: return True
            self.set_cursor(path, column, 0)

        return False

    def editing_started(self, renderer, editable, path):
        self.__editable = editable
        if self.get_model()[path][1] is None: self.__editable.set_text("")
        self.__old_value = self.__editable.get_text()
        self.__old_path = path
        return False

    def edited(self, renderer, path, text, tageditor):
        if self.__old_path is None: return False
        if text == self.__old_value: return False
        model = self.get_model()
        row = model[self.__old_path]
        identifier = row[0]
        row[1] = text
        self.emit("set_value", identifier, text)
        self.__old_value = ""
        self.__old_path = None

class BlaTagedit(blaguiutils.BlaWindow):
    def __init__(self, uris):
        super(BlaTagedit, self).__init__(with_closebutton=False,
                with_cancelbutton=False, close_on_escape=False)
        self.__tracks = {}

        self.connect("key_press_event", self.__key_press_event)
        self.connect("delete_event", self.__apply_and_close)
        self.set_default_size(750, 475)
        self.set_size_request(380, 275)
        self.set_resizable(True)

        def get_label(uri):
            track = library[uri]
            if not track[TITLE]: return track.basename
            return track[TITLE]

        if len(uris) == 1:
            label = "Properties - \"%s\"" % get_label(uris[0])
        elif len(uris) <= 3:
            label = "Properties (%d items) - " % len(uris)
            label = label + "\"%s\", " * (len(uris) - 1) + "\"%s\""
            label = label % tuple(map(get_label, uris))
        else:
            label = "Properties (%d items) - " % len(uris)
            label = label + "\"%s\", " * 2 + "\"%s\", ..."
            label = label % tuple(map(get_label, uris[0:3]))

        self.set_title(label)

        # the notebook and its pages
        notebook = gtk.Notebook()
        sw, self.__treeview_metadata = self.__setup_page(is_editable=True)
        notebook.append_page(sw, gtk.Label("Metadata"))

        sw, self.__treeview_properties = self.__setup_page(is_editable=False)
        notebook.append_page(sw, gtk.Label("Properties"))

        # undo button
        button = gtk.Button("Undo")
        button.connect_object("clicked", BlaTagedit.__undo, self)
        self.buttonbox.pack_start(button)

        # close button
        button = gtk.Button(stock=gtk.STOCK_CLOSE)
        button.connect("clicked", self.__apply_and_close)
        self.buttonbox.pack_start(button)

        button = gtk.Button("Apply")
        button.connect_object("clicked", BlaTagedit.__apply, self)
        self.buttonbox.pack_start(button)

        paned = gtk.HPaned()

        # the file list
        sw = blaguiutils.BlaScrolledWindow()
        sw.set_shadow_type(gtk.SHADOW_OUT)

        self.__file_list = BlaTreeView(allow_no_selection=False)
        self.__file_list.set_rubber_banding(True)
        self.__file_list.set_fixed_height_mode(True)
        self.__file_list.set_enable_search(False)
        self.__file_list.set_property("rules_hint", True)

        r = gtk.CellRendererText()
        r.set_property("ellipsize", pango.ELLIPSIZE_END)
        column = gtk.TreeViewColumn("Files")
        column.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        column.pack_start(r)
        def cell_data_func(column, renderer, model, iterator):
            renderer.set_property("text", os.path.basename(model[iterator][0]))
        column.set_cell_data_func(r, cell_data_func)
        self.__file_list.append_column(column)
        self.__file_list.connect("popup", self.__file_list_popup)

        model = gtk.ListStore(gobject.TYPE_STRING)
        append = model.append
        [append([uri]) for uri in uris]
        self.__file_list.set_model(model)
        selection = self.__file_list.get_selection()
        selection.connect("changed", lambda *x: self.__update_selection())
        selection.select_all()

        sw.add(self.__file_list)
        sw.set_size_request(175, -1)

        paned.pack1(sw, resize=False, shrink=False)
        paned.pack2(notebook, resize=True, shrink=True)
        self.vbox.set_spacing(5)
        self.vbox.pack_start(paned)
        self.__pb = gtk.ProgressBar()
        self.vbox.pack_start(self.__pb, expand=False)
        self.show_all()
        if len(uris) == 1: sw.set_visible(False)
        self.__pb.set_visible(False)

    def __undo(self, uris=None):
        if not uris: uris = [row[0] for row in self.__file_list.get_model()]
        pop = self.__tracks.pop
        [pop(uri, None) for uri in uris]
        self.__update_selection()

    def __file_list_popup(self, treeview, event):
        if not treeview.get_path_at_pos(*map(int, [event.x, event.y])): return

        model, paths = treeview.get_selection().get_selected_rows()
        uris = [model[path][0] for path in paths]

        menu = gtk.Menu()

        m = gtk.MenuItem("Revert changes")
        m.connect("activate", lambda *x: self.__undo(uris))
        menu.append(m)

        menu.show_all()
        menu.popup(None, None, None, event.button, event.time)
        return False

    def __apply_and_close(self, *args):
        response = gtk.RESPONSE_YES
        if self.__tracks:
            response = blaguiutils.question_dialog("There are unsaved "
                    "modifications.", "Save changes?", with_cancel_button=True)
            if response == gtk.RESPONSE_YES: self.__apply()
        if response != gtk.RESPONSE_CANCEL: self.destroy()

    def __apply(self):
        def process():
            try: c = 1.0 / len(self.__tracks)
            except ZeroDivisionError: yield False
            else: self.__pb.set_visible(True)
            idx = 0
            for uri, track in self.__tracks.iteritems():
                self.__pb.set_fraction(c * (idx+1))
                self.__pb.set_text(uri)
                if uri in library: ns["update_library"] = True
                library[uri] = track
                ns["succeeded"] += int(track.save())
                idx += 1
                yield True

            self.__pb.set_fraction(1.0)
            ns["wait"] = False
            yield False

        ns = {"wait": True, "update_library": False, "succeeded": 0}
        text = gtk.Label()
        text.set_alignment(0.0, 0.5)
        text.set_ellipsize(pango.ELLIPSIZE_MIDDLE)
        p = process()
        gobject.idle_add(p.next)

        while ns["wait"]:
            if gtk.events_pending() and gtk.main_iteration(): break

        self.__pb.set_visible(False)
        blaplay.bla.window.update_title()
        from blaplay.blagui.blaplaylist import BlaPlaylistManager
        BlaPlaylistManager.invalidate_visible_rows()
        if ns["update_library"]: library.update_library()
        succeeded = ns["succeeded"]
        l = len(self.__tracks)
        self.__tracks.clear()
        self.__pb.set_visible(False)
        if l > 0 and succeeded != l:
            blaguiutils.warning_dialog("Failed to write tags on %d of %d "
                    "files." % ((l-succeeded), l), "This usually indicates "
                    "missing resources."
            )

    def __update_selection(self):
        model, paths = self.__file_list.get_selection().get_selected_rows()
        uris = [model[path][0] for path in paths]
        cursor = self.__file_list.get_cursor()[0]

        # update metadata
        model = self.__treeview_metadata.get_model()
        self.__treeview_metadata.freeze_child_notify()
        self.__treeview_metadata.set_model(None)
        model.clear()

        tracks = []
        for uri in uris:
            try: track = self.__tracks[uri]
            except KeyError: track = library[uri]
            tracks.append(track)

        # the standard tags
        for identifier in IDENTIFIER_TAGS:
            value = tracks[0][identifier]
            for track in tracks[1:]:
                if value != track[identifier]:
                    value = None
                    break
            if identifier == DATE:
                try: value = value.split("-")[0]
                except AttributeError: pass
            model.append([identifier, value])

        # additional tags
        additional_tags = set()
        update = additional_tags.update
        keys_additional_tags = BlaTrack.keys_additional_tags
        map(update, map(keys_additional_tags, tracks))

        for tag in additional_tags:
            try: value = tracks[0][tag]
            except KeyError: value = None

            for track in tracks[1:]:
                try: next_value = track[tag]
                except KeyError: next_value = None
                if value != next_value:
                    value = None
                    break
            model.append([tag, value])

        self.__treeview_metadata.set_model(model)

        # update properties
        model = self.__treeview_properties.get_model()
        self.__treeview_properties.freeze_child_notify()
        self.__treeview_properties.set_model(None)
        model.clear()

        if cursor is None: uri = uris[0]
        else: uri = self.__file_list.get_model()[cursor][0]
        track = library[uri]

        for identifier in IDENTIFIER_PROPERTIES:
            if not track[identifier] and identifier != MONITORED_DIRECTORY:
                continue
            elif identifier == FILESIZE:
                text = track.get_filesize()
            elif identifier == MTIME:
                text = ctime(track[MTIME])
            elif identifier == LENGTH:
                text = track.duration
            elif identifier == BITRATE:
                text = track.bitrate
            elif identifier == SAMPLING_RATE:
                text = track.sampling_rate
            elif identifier == CHANNELS:
                text = str(track[CHANNELS])
            else:
                text = track[identifier]
            model.append([identifier, text])

        self.__treeview_properties.set_model(model)

        # unfreeze signal emission
        self.__treeview_metadata.thaw_child_notify()
        self.__treeview_properties.thaw_child_notify()

    def __key_press_event(self, treeview, event):
        try:
            r = self.__treeview_metadata.get_column(1).get_cell_renderers()[0]
            if r.get_property("editing"): raise AttributeError
            if blagui.is_accel(event, "Escape"): self.__apply_and_close()
        except AttributeError: pass
        return False

    def __cell_data_func_name(self, column, renderer, model, iterator):
        identifier = model[iterator][0]
        try: text = IDENTIFIER_LABELS[identifier]
        except TypeError: text = "<%s>" % identifier.upper()
        renderer.set_property("text", text)

    def __cell_data_func_value(self, column, renderer, model, iterator):
        value = model[iterator][1]
        if value is None:
            renderer.set_property("markup", "<i>Varies across tracks</i>")
        else: renderer.set_property("text", value)

    def __add_tag(self, *args):
        diag = gtk.Dialog(title="Add tag", buttons=(gtk.STOCK_CANCEL,
                gtk.RESPONSE_CANCEL, gtk.STOCK_OK, gtk.RESPONSE_OK),
                flags=gtk.DIALOG_DESTROY_WITH_PARENT|gtk.DIALOG_MODAL
        )
        diag.set_size_request(250, -1)
        diag.set_resizable(False)

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
            if name and value and name not in IDENTIFIER_TAGS:
                self.__set_value(name, value)
                self.__update_selection()
        diag.destroy()

    def __set_value(self, identifier, value):
        model, paths = self.__file_list.get_selection().get_selected_rows()
        for path in paths:
            uri = model[path][0]
            if not self.__tracks.has_key(uri):
                # copy-on-write
                self.__tracks[uri] = deepcopy(library[uri])
            self.__tracks[uri][identifier] = value

    def __delete_tags(self, identifiers):
        model, paths = self.__file_list.get_selection().get_selected_rows()
        for path in paths:
            uri = model[path][0]
            if not self.__tracks.has_key(uri):
                # copy-on-write
                self.__tracks[uri] = deepcopy(library[uri])
            for identifier in identifiers: del self.__tracks[uri][identifier]

        # update the model and select the tags that survived deletion (i.e.
        # the standard tags)
        self.__update_selection()
        selection = self.__treeview_metadata.get_selection()
        model = self.__treeview_metadata.get_model()
        paths = [r.path for r in model if r[0] in identifiers]
        map(selection.select_path, paths)

    def __capitalize(self, identifiers):
        def capitalize(s):
            return re.sub(r"(^|\s)(\S)",
                    lambda m: m.group(1) + m.group(2).upper(), s)

        model, paths = self.__file_list.get_selection().get_selected_rows()
        for path in paths:
            uri = model[path][0]
            try: track = self.__tracks[uri]
            except KeyError: track = library[uri]
            for identifier in identifiers:
                value = track[identifier]
                value = capitalize(value)

                if value != track[identifier]:
                    if not self.__tracks.has_key(uri):
                        # copy-on-write
                        self.__tracks[uri] = deepcopy(track)
                    self.__tracks[uri][identifier] = value

        self.__update_selection()
        selection = self.__treeview_metadata.get_selection()
        model = self.__treeview_metadata.get_model()
        paths = [r.path for r in model if r[0] in identifiers]
        map(selection.select_path, paths)

    def __setup_page(self, is_editable):
        sw = blaguiutils.BlaScrolledWindow()

        model = gtk.ListStore(gobject.TYPE_PYOBJECT, gobject.TYPE_PYOBJECT)
        tv = BlaTreeView(model, is_editable=is_editable)

        tv.set_enable_search(False)
        tv.set_reorderable(False)
        tv.set_rubber_banding(True)

        tv.set_property("rules_hint", True)
        r = gtk.CellRendererText()
        column = gtk.TreeViewColumn("Name")
        column.pack_start(r)
        column.set_cell_data_func(r, self.__cell_data_func_name)
        tv.append_column(column)

        r = gtk.CellRendererText()
        r.set_property("ellipsize", pango.ELLIPSIZE_END)
        column = gtk.TreeViewColumn("Value")
        column.pack_start(r)
        column.set_cell_data_func(r, self.__cell_data_func_value)
        tv.append_column(column)

        if is_editable:
            r.set_property("editable", True)
            r.connect("editing_started", tv.editing_started)
            r.connect("edited", tv.edited, self)
            tv.connect("popup", self.__popup)
            tv.connect_object("set_value", BlaTagedit.__set_value, self)
            tv.connect_object("delete_tags", BlaTagedit.__delete_tags, self)

        sw.add(tv)
        return sw, tv

    def __popup(self, treeview, event):
        menu = gtk.Menu()
        m = gtk.MenuItem("Add tag...")
        m.connect("activate", self.__add_tag)
        menu.append(m)

        try:
            path, column, x, y = treeview.get_path_at_pos(
                    *map(int, [event.x, event.y]))
        except TypeError: pass
        else:
            model, paths = treeview.get_selection().get_selected_rows()
            identifiers = [model[path][0] for path in paths]
            items = [
                ("Delete tag", "Delete",
                        lambda *x: self.__delete_tags(identifiers)),
                ("Capitalize", None, lambda *x: self.__capitalize(identifiers))
            ]
            for label, accel, callback in items:
                m = gtk.MenuItem(label)
                if accel:
                    mod, key = gtk.accelerator_parse(accel)
                    m.add_accelerator("activate", blagui.accelgroup, mod, key,
                            gtk.ACCEL_VISIBLE)
                m.connect("activate", callback)
                menu.append(m)

        menu.show_all()
        menu.popup(None, None, None, event.button, event.time)

