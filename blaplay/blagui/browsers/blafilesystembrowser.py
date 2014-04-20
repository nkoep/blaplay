# blaplay, Copyright (C) 2012-2014  Niklas Koep

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
import time

import gio
import gobject
import gtk
import pango

from blaplay.blacore import blacfg, blaconst
from blaplay import blautil, blagui
from ..blawindows import BlaScrolledWindow
from .blabrowser import BlaBrowser


class _History(gtk.ListStore):
    def __init__(self):
        super(_History, self).__init__(gobject.TYPE_PYOBJECT)
        self._iterator = None

    def add(self, item):
        insert_func = self.insert_after
        self._iterator = insert_func(self._iterator, [item])

    def get(self, next_):
        if next_:
            f = self.iter_next
        else:
            f = self._iter_previous

        try:
            iterator = f(self._iterator)
        except TypeError:
            iterator = None

        if not iterator:
            item = None
        else:
            item = self[iterator][0]
            self._iterator = iterator
        return item

    def _iter_previous(self, iterator):
        path = self.get_path(iterator)
        if path[0] > 0:
            return self.get_iter((path[0]-1,))
        return None

class BlaFilesystemBrowser(BlaBrowser):
    ID = blaconst.BROWSER_FILESYSTEM

    def __init__(self, *args, **kwargs):
        super(BlaFilesystemBrowser, self).__init__(
            "Filesystem", *args, **kwargs)

        self._history = _History()

        self._update_timeout_id = -1
        self._filter_timeout_id = -1
        self._pixbufs = {
            "directory": self._get_pixbuf(gtk.STOCK_DIRECTORY),
            "file": self._get_pixbuf(gtk.STOCK_FILE)
        }

        vbox = gtk.VBox()

        # The toolbar
        table = gtk.Table(rows=1, columns=6, homogeneous=False)

        buttons = [
            (gtk.STOCK_GO_BACK,
             lambda *x: self._update_from_history(backwards=True)),
            (gtk.STOCK_GO_UP,
             lambda *x: self._update_directory(
                os.path.dirname(self._directory))),
            (gtk.STOCK_GO_FORWARD,
             lambda *x: self._update_from_history(backwards=False)),
            (gtk.STOCK_HOME,
             lambda *x: self._update_directory(os.path.expanduser("~")))
        ]

        def add_button(icon, callback, idx):
            button = gtk.Button()
            button.add(
                gtk.image_new_from_stock(icon, gtk.ICON_SIZE_SMALL_TOOLBAR))
            button.set_relief(gtk.RELIEF_NONE)
            button.connect("clicked", callback)
            table.attach(button, idx, idx+1, 0, 1, xoptions=gtk.FILL)

        idx = 0
        for icon, callback in buttons:
            add_button(icon, callback, idx)
            idx += 1

        # Add the entry field separately.
        self._entry = gtk.Entry()
        self._entry.connect(
            "activate",
            lambda *x: self._update_directory(self._entry.get_text()))
        def on_key_press_event_entry(entry, event):
            if (blagui.is_accel(event, "Escape") or
                blagui.is_accel(event, "<Ctrl>L")):
                self._entry.select_region(-1, -1)
                self._treeview.grab_focus()
                return True
            elif (blagui.is_accel(event, "Up") or
                  blagui.is_accel(event, "Down")):
                return True
            return False
        self._entry.connect("key-press-event", on_key_press_event_entry)
        table.attach(self._entry, idx, idx+1, 0, 1)
        idx += 1

        add_button(gtk.STOCK_REFRESH,
                   lambda *x: self._update_directory(refresh=True), idx)

        vbox.pack_start(table, expand=False, fill=False)

        # The treeview
        self._treeview = self.BlaTreeView()
        self._treeview.set_headers_visible(True)
        self._treeview.set_enable_search(True)
        self._treeview.set_search_column(2)
        self._treeview.enable_model_drag_source(
            gtk.gdk.BUTTON1_MASK,
            [blagui.DND_TARGETS[blagui.DND_URIS]],
            gtk.gdk.ACTION_COPY)
        self._treeview.connect_object(
            "drag-data-get", BlaFilesystemBrowser._on_drag_data_get, self)
        def on_key_press_event(treeview, event):
            if blagui.is_accel(event, "<Ctrl>L"):
                self._entry.grab_focus()
                return True
            return False
        self._treeview.connect("key-press-event", on_key_press_event)
        # self._treeview.connect("popup", _popup_menu, self, playlist_manager)
        model_layout = (
            gobject.TYPE_STRING,    # uri
            gtk.gdk.Pixbuf,         # pixbuf
            gobject.TYPE_STRING,    # label
        )
        model = gtk.ListStore(*model_layout)
        self._filt = model.filter_new()
        self._filt.set_visible_func(self._visible_func)
        self._treeview.set_model(self._filt)
        self._directory = blacfg.getstring("general", "filesystem.directory")

        # Name column
        c = gtk.TreeViewColumn("Name")
        c.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        c.set_resizable(True)
        c.set_expand(True)
        c.set_fixed_width(1)

        r = gtk.CellRendererPixbuf()
        r.set_property("xalign", 0.0)
        c.pack_start(r, expand=False)
        c.add_attribute(r, "pixbuf", 1)

        r = gtk.CellRendererText()
        r.set_property("xalign", 0.0)
        c.pack_start(r)
        # TODO: Use a cdf instead.
        c.add_attribute(r, "text", 2)
        r.set_property("ellipsize", pango.ELLIPSIZE_END)

        self._treeview.append_column(c)

        # TODO: Turn this into nemo's size column (for files, display the size,
        #       for directories the number of items)
        # Last modified column
        c = gtk.TreeViewColumn()
        c.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        c.set_resizable(True)

        title = "Last modified"
        label = gtk.Label(title)
        width = label.create_pango_layout(title).get_pixel_size()[0]
        c.set_title(title)

        r = gtk.CellRendererText()
        r.set_property("ellipsize", pango.ELLIPSIZE_END)
        c.pack_start(r)
        c.set_cell_data_func(r, self._last_modified_cb)
        c.set_min_width(width + 12 + r.get_property("xpad"))

        self._treeview.append_column(c)
        self._treeview.connect("row-activated", self._open)
        self._update_directory(self._directory)
        self._treeview.columns_autosize()

        sw = BlaScrolledWindow()
        sw.add(self._treeview)
        vbox.pack_start(sw, expand=True)

        # The search bar
        hbox = gtk.HBox()
        hbox.pack_start(gtk.Label("Filter:"), expand=False, padding=2)

        self._filter_entry = gtk.Entry()
        self._filter_entry.set_icon_from_stock(gtk.ENTRY_ICON_SECONDARY,
                                               gtk.STOCK_CLEAR)
        self._filter_entry.connect(
            "icon-release", lambda *x: x[0].delete_text(0, -1))
        self._filter_entry.connect(
            "changed", self._on_filter_entry_changed)
        self._filter_entry.connect(
            "activate", lambda *x: self._filt.refilter())
        hbox.pack_start(self._filter_entry, expand=True)

        button = gtk.Button()
        button.add(
            gtk.image_new_from_stock(gtk.STOCK_FIND,
                                     gtk.ICON_SIZE_SMALL_TOOLBAR))
        button.connect("clicked", lambda *x: self._filt.refilter())
        hbox.pack_start(button, expand=False)
        vbox.pack_start(hbox, expand=False)

        self.pack_start(vbox)

    def _get_pixbuf(self, icon_name):
        icon_theme = gtk.icon_theme_get_default()
        icon_info = icon_theme.lookup_icon(
            icon_name, gtk.ICON_SIZE_MENU, gtk.ICON_LOOKUP_USE_BUILTIN)
        if not icon_info:
            return None
        pb = icon_info.get_filename()
        try:
            pb = gtk.gdk.pixbuf_new_from_file(pb)
        except gobject.GError:
            pb = icon_info.get_builtin_pixbuf()
        if pb:
            w, h = gtk.icon_size_lookup(gtk.ICON_SIZE_MENU)
            pb = pb.scale_simple(w, h, gtk.gdk.INTERP_HYPER)
        return pb

    def _visible_func(self, model, iterator):
        # FIXME: depending on the number of items in the model this approach is
        #        slow. maybe filter "offline" as we do for playlists and
        #        populate a new model with the result
        try:
            # FIXME: now this is slow as hell as this gets called for every
            #        iterator. it's just temporary though until we refactored
            #        the library browser's treeview code
            tokens = self._filter_entry.get_text().strip().split()
        except AttributeError:
            return True
        if tokens:
            try:
                label = model[iterator][2].lower()
            except AttributeError:
                return True
            for t in tokens:
                if t not in label:
                    return False
        return True

    def _on_filter_entry_changed(self, entry):
        filter_string = self._filter_entry.get_text()
        if (blacfg.getboolean("general", "search.after.timeout") or
            not filter_string):
            gobject.source_remove(self._filter_timeout_id)
            def activate():
                self._filt.refilter()
                return False
            self._filter_timeout_id = gobject.timeout_add(500, activate)

    def _update_directory(self, directory=None, refresh=False,
                          add_to_history=True):
        if not refresh:
            if directory is None:
                print_w("Directory must not be None")
                return False
            directory = os.path.expanduser(directory)
            # Got a relative path?
            if not os.path.isabs(directory):
                directory = os.path.join(self._directory, directory)
            if not os.path.exists(directory):
                blaguiutil.error_dialog(
                    "Could not find \"%s\"." % directory,
                    "Please check the spelling and try again.")
                return False
            self._directory = directory
            self._entry.set_text(self._directory)
            blacfg.set_("general", "filesystem.directory", self._directory)
            if add_to_history:
                self._history.add(self._directory)

        # FIXME: don't use gtk's model filter capabilities
        # TODO: keep the selection after updating the model
        model = self._filt.get_model()
        self._treeview.freeze_child_notify()
        model.clear()

        for dirpath, dirnames, filenames in os.walk(self._directory):
            for d in sorted(dirnames, key=str.lower):
                if d.startswith("."):
                    continue
                path = os.path.join(self._directory, d)
                model.append([path, self._pixbufs["directory"], d])

            for f in sorted(filenames, key=str.lower):
                if f.startswith("."):
                    continue
                path = os.path.join(self._directory, f)
                # TODO: use this instead (profile the overhead first though):
                #         f = gio.File(path)
                #         info = f.query_info("standard::content-type")
                #         mimetype = info.get_content_type()
                mimetype = gio.content_type_guess(path)
                try:
                    pb = self._pixbufs[mimetype]
                except KeyError:
                    icon_names = gio.content_type_get_icon(mimetype)
                    pb = self._pixbufs["file"]
                    if icon_names:
                        for icon_name in icon_names.get_names():
                            pb_new = self._get_pixbuf(icon_name)
                            if pb_new:
                                self._pixbufs[mimetype] = pb_new
                                pb = pb_new
                model.append([path, pb, f])
            break

        try:
            self._monitor.cancel()
        except AttributeError:
            pass

        # FIXME: this seems to cease working after handling an event
        self._monitor = gio.File(self._directory).monitor_directory(
            flags=gio.FILE_MONITOR_NONE)
        self._monitor.connect("changed", self._process_event)

        self._treeview.thaw_child_notify()
        return False

    def _process_event(self, monitor, filepath, other_filepath, type_):
        gobject.source_remove(self._update_timeout_id)
        self._update_timeout_id = gobject.timeout_add(
            2000, lambda *x: self._update_directory(refresh=True,
                                                    add_to_history=False))

    def _update_from_history(self, backwards):
        if backwards:
            path = self._history.get(next_=False)
        else:
            path = self._history.get(next_=True)

        if path:
            self._update_directory(directory=path, add_to_history=False)

    def _open(self, treeview, path, column):
        model = treeview.get_model()
        entry = model[path][0]
        if os.path.isdir(entry):
            model = self._update_directory(entry)
            return True
        return False

    def _last_modified_cb(self, column, renderer, model, iterator):
        path = model[iterator][0]
        try:
            text = time.ctime(os.path.getmtime(path))
        except OSError:
            text = ""
        renderer.set_property("text", text)

    def _on_drag_data_get(self, drag_context, selection_data, info, timestamp):
        model, paths = self._treeview.get_selection().get_selected_rows()
        uris = blautil.filepaths2uris([model[path][0] for path in paths])
        selection_data.set_uris(uris)

