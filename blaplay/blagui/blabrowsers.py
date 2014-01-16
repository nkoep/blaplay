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
import cPickle as pickle
import time
import re

import gobject
import gtk
import gio
import cairo
import pango
import pangocairo

import blaplay
library = blaplay.bla.library
from blaplay.blacore import blaconst, blacfg
from blaplay import blautil, blagui
from blaplay.formats._identifiers import *
from blawindows import BlaScrolledWindow
from blaplaylist import playlist_manager
from blaqueue import queue
import blaguiutils

PADDING_X, PADDING_Y, PADDING_WIDTH, PADDING_HEIGHT = -2, 0, 4, 0


class BlaCellRenderer(blaguiutils.BlaCellRendererBase):
    __gproperties__ = {
        "text": (gobject.TYPE_STRING, "text", "", "", gobject.PARAM_READWRITE)
    }

    def get_layout(self, *args):
        if len(args) == 1:
            treeview, text = args[0], ""
        else:
            treeview, text = args

        context = treeview.get_pango_context()
        layout = pango.Layout(context)
        fdesc = gtk.widget_get_default_style().font_desc
        layout.set_font_description(fdesc)

        if text:
            layout.set_text(text)
        else:
            try:
                text = self.get_property("text")
            except AttributeError:
                text = ""
        layout.set_text(text)
        return layout

    def on_get_size(self, widget, cell_area):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 0, 0)
        cr = cairo.Context(surface)
        pc_context = pangocairo.CairoContext(cr)
        layout = self.get_layout(widget)
        width, height = layout.get_pixel_size()
        return (0, 0, width, height)

    def on_render(self, window, widget, background_area, cell_area,
                  expose_area, flags):
        style = widget.get_style()
        text_color = str(style.text[gtk.STATE_NORMAL])
        active_text_color = str(style.text[gtk.STATE_SELECTED])
        selected_row_color = str(style.base[gtk.STATE_SELECTED])
        background_color = str(style.base[gtk.STATE_NORMAL])

        # Render background
        cr = window.cairo_create()
        color = gtk.gdk.color_parse(background_color)
        cr.set_source_color(color)

        pc_context = pangocairo.CairoContext(cr)
        pc_context.rectangle(*background_area)
        pc_context.fill()

        # Render active resp. inactive rows
        layout = self.get_layout(widget)
        layout.set_font_description(widget.get_style().font_desc)
        width, height = layout.get_pixel_size()

        use_highlight_color = flags & gtk.CELL_RENDERER_SELECTED
        if use_highlight_color:
            color = gtk.gdk.color_parse(selected_row_color)
        else:
            color = gtk.gdk.color_parse(background_color)
        cr.set_source_color(color)
        pc_context.rectangle(
             cell_area.x + PADDING_X, cell_area.y + PADDING_Y,
             width + PADDING_WIDTH, cell_area.height + PADDING_HEIGHT)
        pc_context.fill()

        # Set font, font color and the text to render
        if use_highlight_color:
            color = gtk.gdk.color_parse(active_text_color)
        else:
            color = gtk.gdk.color_parse(text_color)
        cr.set_source_color(color)
        pc_context.move_to(cell_area.x, cell_area.y)
        pc_context.show_layout(layout)

class BlaTreeView(blaguiutils.BlaTreeViewBase):
    def __init__(self, parent, multicol, browser_id):
        super(BlaTreeView, self).__init__()

        self.__renderer = 0
        self.__text_column = 1
        self.__multicol = multicol

        self.__parent = parent
        self.__browser_id = browser_id

        self.set_fixed_height_mode(True)
        self.set_reorderable(False)
        self.set_rubber_banding(True)
        self.set_property("rules_hint", True)

        self.connect("key_press_event", self.__key_press_event)
        self.connect_object(
            "button_press_event", BlaTreeView.__button_press_event, self)
        self.connect_object("popup", BlaTreeView.__popup_menu, self)

    def __send_to_queue(self):
        count = blaconst.QUEUE_MAX_ITEMS - queue.n_items
        tracks = self.get_tracks(count=count)
        queue.queue_items(tracks)

    def get_tracks(self, count=-1):
        def get_children(model, iterator):
            children = []

            if model.iter_has_child(iterator):
                child = model.iter_children(iterator)
                while child:
                    if model.iter_has_child(child):
                        children += get_children(model, child)
                    else:
                        children.append(child)

                    child = model.iter_next(child)
            else:
                children.append(iterator)

            return children

        selections = []
        model, paths = self.get_selection().get_selected_rows()

        for p in paths:
            iterator = model.get_iter(p)
            iterators = get_children(model, iterator)
            for it in iterators:
                selections.append(model.get_value(it, 0))
            if count != -1 and len(selections) > count:
                break

        return selections[:count] if count != -1 else selections

    def __key_press_event(self, treeview, event):
        if self.__browser_id == blaconst.BROWSER_FILESYSTEM:
            return False

        if blagui.is_accel(event, "Q"):
            self.__send_to_queue()

        elif (blagui.is_accel(event, "Return") or
              blagui.is_accel(event, "KP_Enter")):
            action = blacfg.getint("library", "return.action")

            selections = self.get_selection().get_selected_rows()[-1]
            if not selections:
                return True
            name = self.get_model()[selections[0]][1]
            tracks = self.get_tracks()

            if action == blaconst.ACTION_SEND_TO_CURRENT:
                playlist_manager.send_to_current_playlist(tracks)
            elif action == blaconst.ACTION_ADD_TO_CURRENT:
                playlist_manager.add_to_current_playlist(tracks)
            elif action == blaconst.ACTION_SEND_TO_NEW:
                playlist_manager.send_to_new_playlist(tracks, name)

        return False

    def __accept_button_event(self, column, path, event, check_expander):
        # TODO: get rid of this method and implement it only where necessary
        #       (i.e. the library browser)
        if (not blacfg.getboolean("library", "custom.browser") or
            self.__multicol or self.__renderer is None):
            return True

        renderer = column.get_cell_renderers()[self.__renderer]
        model = self.get_model()
        iterator = model.get_iter(path)

        layout = renderer.get_layout(
                self, model.get_value(iterator, self.__text_column))
        width = layout.get_pixel_size()[0]
        cell_area = self.get_cell_area(path, column)
        expander_size = self.style_get_property("expander_size")

        # check vertical position of click event
        if not (event.y >= cell_area.y+PADDING_Y and
                event.y <= cell_area.y+cell_area.height):
            return False

        # check for click on expander and if the row has children
        if (check_expander and
            event.x >= cell_area.x+PADDING_X-expander_size and
            event.x <= cell_area.x+PADDING_X and
            model.iter_has_child(iterator) and
            event.type not in [gtk.gdk._2BUTTON_PRESS,
                               gtk.gdk._3BUTTON_PRESS]):
            return True

        # check for click in the highlighted area
        if (event.x >= cell_area.x+PADDING_X and
            event.x <= cell_area.x+width):
            return True

        return False

    def __button_press_event(self, event):
        if self.__browser_id == blaconst.BROWSER_FILESYSTEM:
            return False

        # Return on events that don't require any special treatment.
        if ((event.button == 1 and not (event.type == gtk.gdk._2BUTTON_PRESS or
            event.type == gtk.gdk._3BUTTON_PRESS)) or
            event.type == gtk.gdk._3BUTTON_PRESS or
            (event.button == 2 and event.type == gtk.gdk._2BUTTON_PRESS)):
            return False

        if event.button == 1:
            action = blacfg.getint("library", "doubleclick.action")
        elif event.button == 2:
            action = blacfg.getint("library", "middleclick.action")

        path = self.get_path_at_pos(*map(int, [event.x, event.y]))[0]
        # TODO: remove me
        if False and not self.__accept_button_event(column, path, event,
                                          check_expander=(event.button == 1)):
            self.__allow_selection(True)
            selection.unselect_all()

        # Handle LMB events
        if event.button == 1 and action == blaconst.ACTION_EXPAND_COLLAPSE:
            if self.row_expanded(path):
                self.collapse_row(path)
            else:
                self.expand_row(path, open_all=False)
            return False

        # On middle-clicks we must update the selection due to the way DND is
        # implemented.
        if event.button == 2:
            selection = self.get_selection()
            selection.unselect_all()
            selection.select_path(path)

        model = self.get_model()
        name = model[path][1]
        tracks = self.get_tracks()

        if action == blaconst.ACTION_SEND_TO_CURRENT:
            playlist_manager.send_to_current_playlist(tracks)
        elif action == blaconst.ACTION_ADD_TO_CURRENT:
            playlist_manager.add_to_current_playlist(tracks)
        elif action == blaconst.ACTION_SEND_TO_NEW:
            playlist_manager.send_to_new_playlist(tracks, name)

        return False

    def __popup_menu(self, event):
        model = self.get_model()
        try:
            path = self.get_path_at_pos(*map(int, [event.x, event.y]))[0]
        except TypeError:
            return

        if self.__browser_id == blaconst.BROWSER_FILESYSTEM:
            def dirname(s):
                return s if os.path.isdir(s) else os.path.dirname(s)
            resolve = True
        else:
            dirname = os.path.dirname
            resolve = False

        name = model[path][1]
        # TODO: Defer calling get_tracks() until it's actually needed, i.e.
        #       when an "activate" callback is invoked.
        tracks = self.get_tracks()
        directory = list(set(map(dirname, tracks)))
        if len(directory) == 1 and os.path.isdir(directory[0]):
            directory = directory[0]
        else:
            directory = None

        items = [
            ("Send to current playlist", None,
             lambda *x: playlist_manager.send_to_current_playlist(
             tracks, resolve), True),
            ("Add to current playlist", None,
             lambda *x: playlist_manager.add_to_current_playlist(
             tracks, resolve), True),
            ("Send to new playlist", None,
             lambda *x: playlist_manager.send_to_new_playlist(
             tracks, name, resolve), True),
            None,
            ("Open directory", None, lambda *x:
             blautil.open_directory(directory), bool(directory)),
        ]
        if self.__browser_id == blaconst.BROWSER_LIBRARY:
            items.append(("Add to playback queue", "Q",
                          lambda *x: self.__send_to_queue(), True))

        accel_group = blaplay.bla.ui_manager.get_accel_group()
        menu = gtk.Menu()
        for item in items:
            if item is None:
                m = gtk.SeparatorMenuItem()
            else:
                label, accel, callback, sensitive = item
                m = gtk.MenuItem(label)
                if accel is not None:
                    mod, key = gtk.accelerator_parse(accel)
                    m.add_accelerator("activate", accel_group, mod, key,
                                      gtk.ACCEL_VISIBLE)
                m.connect("activate", callback)
                m.set_sensitive(sensitive)
            menu.append(m)

        menu.show_all()
        menu.popup(None, None, None, event.button, event.time)

class BlaQuery(object):
    def __init__(self, filter_string):
        # TODO: if bool(tokens) is False, don't instantiate this at all
        if filter_string:
            filter_string = filter_string.decode("utf-8")
            flags = re.UNICODE | re.IGNORECASE
            self.__res = [re.compile(t, flags)
                          for t in map(re.escape, filter_string.split())]
            self.query = self.__query
        else:
            self.query = lambda *x: True

    def __query(self, uri):
        track = library[uri]
        strings = [track[identifier] for identifier in (ARTIST, TITLE, ALBUM)]

        if (blacfg.getint("library", "organize.by") ==
            blaconst.ORGANIZE_BY_DIRECTORY):
            strings.append(track.basename)

        for r in self.__res:
            search = r.search
            for string in strings:
                if search(string):
                    break
            else:
                return False
        return True

class BlaLibraryBrowser(gtk.VBox):
    __layout = (
        gobject.TYPE_STRING,    # uri
        gobject.TYPE_STRING     # leaf label
    )
    __cid = -1
    __fid = -1
    __expanded_rows = []

    class LibraryModel(gtk.TreeStore):
        __gsignals__ = {
            "populated": blautil.signal(0)
        }

        def populate(self, view, filter_string):
            start_time = time.time()

            if view == blaconst.ORGANIZE_BY_DIRECTORY:
                cb = self.__organize_by_directory
            elif view == blaconst.ORGANIZE_BY_ARTIST:
                cb = self.__organize_by_artist
            elif view == blaconst.ORGANIZE_BY_ARTIST_ALBUM:
                cb = self.__organize_by_artist_album
            elif view == blaconst.ORGANIZE_BY_ALBUM:
                cb = self.__organize_by_album
            elif view in (blaconst.ORGANIZE_BY_GENRE,
                          blaconst.ORGANIZE_BY_YEAR):
                def cb(uri, comps):
                    return self.__organize_by_genre_year(uri, comps, view=view)
            else:
                raise NotImplementedError("Invalid library view")

            count = 0
            yield_interval = 25

            list_ = []
            append = list_.append
            library_filter = self.__get_filter()
            query = BlaQuery(filter_string).query
            def filt(*args):
                return library_filter(*args) and query(*args)
            for uri in filter(filt, library):
                comps = tuple(map(unicode, cb(uri, library[uri])))
                append((comps, uri))
                count = count+1
                if count % yield_interval == 0:
                    yield True

            iterators = {}
            append = self.append
            def key(item):
                return map(unicode.lower, item[0])
            for comps, uri in sorted(list_, key=key):
                for idx in xrange(len(comps)-1):
                    comps_init = comps[:idx+1]
                    iterator = iterators.get(comps_init, None)
                    if iterator is None:
                        parent = iterators.get(comps_init[:-1], None)
                        iterators[comps_init] = iterator = append(
                            parent, (None, comps_init[-1]))
                append(iterator, (uri, comps[-1]))
                count = count+1
                if count % yield_interval == 0:
                    yield True

            print_d("Populated library model in %.2f seconds" %
                    (time.time() - start_time))
            self.emit("populated")
            yield False

        @staticmethod
        def __get_filter():
            # This returns a filter function which URIs have to pass in order
            # for them to be considered in the library browser.
            def get_regexp(string):
                tokens = [t.replace(".", "\.").replace("*", ".*")
                          for t in map(str.strip, string.split(","))]
                return re.compile(r"(%s)" % "|".join(tokens))

            restrict_re = get_regexp(
                blacfg.getstring("library", "restrict.to").strip())
            exclude_string = blacfg.getstring("library", "exclude").strip()
            if exclude_string:
                exclude_re = get_regexp(exclude_string)
                def filt(s):
                    return restrict_re.match(s) and not exclude_re.match(s)
            else:
                filt = restrict_re.match
            return filt

        @staticmethod
        def __get_track_label(track):
            # ValueError is raised if the int() call fails. We hazard the
            # possible performance hit to avoid bogus TRACK properties.
            try:
                label = "%02d." % int(track[TRACK].split("/")[0])
            except ValueError:
                label = ""
            else:
                try:
                    label = "%d.%s " % (int(track[DISC].split("/")[0]), label)
                except ValueError:
                    label = "%s " % label
            artist = (track[ALBUM_ARTIST] or track[PERFORMER] or
                      track[ARTIST] or track[COMPOSER])
            if track[ARTIST] and artist != track[ARTIST]:
                label += "%s - " % track[ARTIST]
            return "%s%s" % (label, track[TITLE] or track.basename)

        @staticmethod
        def __organize_by_directory(uri, track):
            try:
                md = track[MONITORED_DIRECTORY]
            except KeyError:
                raise ValueError("Trying to include track in the library "
                                 "browser that has no monitored directory")
            directory = track.uri[len(md)+1:]
            return tuple(["bla"] + directory.split("/"))

        @classmethod
        def __organize_by_artist(cls, uri, track):
            return (track[ARTIST] or "?", track[ALBUM] or "?",
                    cls.__get_track_label(track))

        @classmethod
        def __organize_by_artist_album(cls, uri, track):
            artist = (track[ALBUM_ARTIST] or track[PERFORMER] or
                      track[ARTIST] or "?")
            return ("%s - %s" % (artist, track[ALBUM] or "?"),
                    cls.__get_track_label(track))

        @classmethod
        def __organize_by_album(cls, uri, track):
            return (track[ALBUM] or "?", cls.__get_track_label(track))

        @classmethod
        def __organize_by_genre_year(cls, uri, track, view):
            if view == blaconst.ORGANIZE_BY_GENRE:
                key = GENRE
            else:
                key = DATE
            organizer = track[key].capitalize() or "?"
            if key == DATE:
                organizer = organizer.split("-")[0]
            label = "%s - %s" % (
                track[ALBUM_ARTIST] or track[ARTIST], track[ALBUM] or "?")
            return (organizer, label, cls.__get_track_label(track))

    def __init__(self, parent):
        super(BlaLibraryBrowser, self).__init__()

        self.__treeview = BlaTreeView(parent=parent, multicol=False,
                                      browser_id=blaconst.BROWSER_LIBRARY)
        self.__treeview.set_headers_visible(False)
        column = gtk.TreeViewColumn()
        column.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        self.__treeview.append_column(column)
        self.__treeview.connect("row_collapsed", self.__row_collapsed)
        self.__treeview.connect("row_expanded", self.__row_expanded)

        self.__treeview.enable_model_drag_source(
            gtk.gdk.BUTTON1_MASK,
            [blagui.DND_TARGETS[blagui.DND_LIBRARY]],
            gtk.gdk.ACTION_COPY)
        self.__treeview.connect_object(
            "drag_data_get", BlaLibraryBrowser.__drag_data_get, self)

        sw = BlaScrolledWindow()
        sw.add(self.__treeview)

        hbox = gtk.HBox()

        cb = gtk.combo_box_new_text()
        for label in ["directory", "artist", "artist - album", "album",
                      "genre", "year"]:
            cb.append_text(label)
        cb.set_active(blacfg.getint("library", "organize.by"))
        cb.connect("changed", self.__organize_by_changed)

        alignment = gtk.Alignment()
        alignment.add(gtk.Label("Organize by:"))
        table = gtk.Table(rows=2, columns=1, homogeneous=False)
        table.attach(alignment, 0, 1, 0, 1, xpadding=2, ypadding=2)
        table.attach(cb, 0, 1, 1, 2)
        hbox.pack_start(table, expand=False)

        def queue_model_update(*args):
            self.__queue_model_update(blacfg.getint("library", "organize.by"))

        self.__entry = gtk.Entry()
        self.__entry.set_icon_from_stock(gtk.ENTRY_ICON_SECONDARY,
                                         gtk.STOCK_CLEAR)
        self.__entry.connect(
            "icon_release", lambda *x: x[0].delete_text(0, -1))
        self.__entry.connect("changed", self.__filter_parameters_changed)
        self.__entry.connect("activate", queue_model_update)

        button = gtk.Button()
        button.add(
            gtk.image_new_from_stock(gtk.STOCK_FIND, gtk.ICON_SIZE_BUTTON))
        button.connect("clicked", queue_model_update)

        alignment = gtk.Alignment()
        alignment.add(gtk.Label("Filter:"))
        table = gtk.Table(rows=2, columns=1, homogeneous=False)
        table.attach(alignment, 0, 1, 0, 1, xpadding=2, ypadding=2)
        hbox2 = gtk.HBox()
        hbox2.pack_start(self.__entry, expand=True)
        hbox2.pack_start(button, expand=False)
        table.attach(hbox2, 0, 1, 1, 2)
        hbox.pack_start(table)

        self.pack_start(sw, expand=True)
        self.pack_start(hbox, expand=False)

        self.update_treeview_style()
        self.update_tree_lines()
        def config_changed(cfg, section, key):
            if section == "library":
                if key == "custom.browser":
                    self.update_treeview_style()
                elif key == "draw.tree.lines":
                    self.update_tree_lines()
        blacfg.connect("changed", config_changed)

        library.connect("library_updated", queue_model_update)
        queue_model_update()

    def __queue_model_update(self, view):
        print_d("Updating library browser...")
        model = BlaLibraryBrowser.LibraryModel(*self.__layout)

        def populated(model):
            self.__expanded_rows = []
            self.__treeview.set_model(model)
            organize_by = blacfg.getint("library", "organize.by")
            if (organize_by == blaconst.ORGANIZE_BY_DIRECTORY and
                model.get_iter_first()):
                self.__treeview.expand_row((0,), open_all=False)
            try:
                self.window.set_cursor(None)
            except AttributeError:
                pass
        model.connect("populated", populated)

        gobject.source_remove(self.__cid)
        self.__cid = gobject.idle_add(
            model.populate(view, self.__entry.get_text().strip()).next)
        try:
            self.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
        except AttributeError:
            pass

    def __filter_parameters_changed(self, entry):
        filter_string = self.__entry.get_text()
        if (blacfg.getboolean("playlist", "search.after.timeout") or
            not filter_string):
            gobject.source_remove(self.__fid)
            def activate():
                self.__entry.activate()
                return False
            self.__fid = gobject.timeout_add(500, activate)

    def __drag_data_get(self, drag_context, selection_data, info, timestamp):
        data = self.__treeview.get_tracks()
        # TODO: We could use set_uris() here as well which would allow DND
        #       from the library to external applications like file managers.
        data = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
        selection_data.set("", 8, data)

    def __row_collapsed(self, treeview, iterator, path):
        try:
            self.__expanded_rows.remove(path)
        except ValueError:
            pass

    def __row_expanded(self, treeview, iterator, path):
        def expand_row(model, path, iterator):
            if path in self.__expanded_rows:
                treeview.expand_row(path, open_all=False)

        if self.__expanded_rows:
            treeview.get_model().foreach(expand_row)
        if not path in self.__expanded_rows:
            self.__expanded_rows.append(path)

    def __organize_by_changed(self, combobox):
        view = combobox.get_active()
        blacfg.set("library", "organize.by", view)
        self.__queue_model_update(view)

    def update_treeview_style(self):
        column = self.__treeview.get_column(0)
        column.clear()

        if blacfg.getboolean("library", "custom.browser"):
            renderer = BlaCellRenderer()
        else:
            renderer = gtk.CellRendererText()

        def cdf(column, renderer, model, iterator):
            n_children = model.iter_n_children(iterator)
            if n_children > 0:
                text = "%s (%d)" % (model[iterator][1], n_children)
            else:
                text = model[iterator][1]
            renderer.set_property("text", text)
        column.pack_start(renderer)
        column.set_cell_data_func(renderer, cdf)

    def update_tree_lines(self):
        self.__treeview.set_enable_tree_lines(
            blacfg.getboolean("library", "draw.tree.lines"))

class BlaFileBrowser(gtk.VBox):
    __layout = (
        gobject.TYPE_STRING,    # uri
        gtk.gdk.Pixbuf,         # pixbuf
        gobject.TYPE_STRING,    # label
    )

    __fid = -1
    __uid = -1

    class History(object):
        def __init__(self):
            super(BlaFileBrowser.History, self).__init__()
            self.__model = gtk.ListStore(gobject.TYPE_PYOBJECT)
            self.__iterator = None

        def add(self, item):
            insert_func = self.__model.insert_after
            self.__iterator = insert_func(self.__iterator, [item])

        def get(self, next):
            if next:
                f = self.__model.iter_next
            else:
                f = self.__iter_previous

            try:
                iterator = f(self.__iterator)
            except TypeError:
                iterator = None

            if not iterator:
                item = None
            else:
                item = self.__model[iterator][0]
                self.__iterator = iterator
            return item

        def __iter_previous(self, iterator):
            path = self.__model.get_path(iterator)
            if path[0] > 0:
                return self.__model.get_iter((path[0]-1,))
            return None

    def __init__(self, parent):
        super(BlaFileBrowser, self).__init__()

        self.__pixbufs = {
            "directory": self.__get_pixbuf(gtk.STOCK_DIRECTORY),
            "file": self.__get_pixbuf(gtk.STOCK_FILE)
        }

        self.__history = BlaFileBrowser.History()

        vbox = gtk.VBox()

        # The toolbar
        table = gtk.Table(rows=1, columns=6, homogeneous=False)

        buttons = [
            (gtk.STOCK_GO_BACK,
             lambda *x: self.__update_from_history(backwards=True)),
            (gtk.STOCK_GO_UP,
             lambda *x: self.__update_directory(
                os.path.dirname(self.__directory))),
            (gtk.STOCK_GO_FORWARD,
             lambda *x: self.__update_from_history(backwards=False)),
            (gtk.STOCK_HOME,
             lambda *x: self.__update_directory(os.path.expanduser("~")))
        ]

        def add_button(icon, callback, idx):
            button = gtk.Button()
            button.add(gtk.image_new_from_stock(icon, gtk.ICON_SIZE_BUTTON))
            button.set_relief(gtk.RELIEF_NONE)
            button.connect("clicked", callback)
            table.attach(button, idx, idx+1, 0, 1, xoptions=not gtk.EXPAND)

        idx = 0
        for icon, callback in buttons:
            add_button(icon, callback, idx)
            idx += 1

        # Add the entry field separately.
        self.__entry = gtk.Entry()
        self.__entry.connect(
            "activate",
            lambda *x: self.__update_directory(self.__entry.get_text()))
        def key_press_event_entry(entry, event):
            if (blagui.is_accel(event, "Escape") or
                blagui.is_accel(event, "<Ctrl>L")):
                self.__entry.select_region(-1, -1)
                self.__treeview.grab_focus()
                return True
            elif (blagui.is_accel(event, "Up") or
                  blagui.is_accel(event, "Down")):
                return True
            return False
        self.__entry.connect("key_press_event", key_press_event_entry)
        table.attach(self.__entry, idx, idx+1, 0, 1)
        idx += 1

        add_button(gtk.STOCK_REFRESH,
                   lambda *x: self.__update_directory(refresh=True), idx)

        vbox.pack_start(table, expand=False, fill=False)

        # The treeview
        self.__treeview = BlaTreeView(parent=parent, multicol=True,
                                      browser_id=blaconst.BROWSER_FILESYSTEM)
        self.__treeview.set_enable_search(True)
        self.__treeview.set_search_column(2)
        self.__treeview.enable_model_drag_source(
            gtk.gdk.BUTTON1_MASK,
            [blagui.DND_TARGETS[blagui.DND_URIS]],
            gtk.gdk.ACTION_COPY)
        self.__treeview.connect_object(
            "drag_data_get", BlaFileBrowser.__drag_data_get, self)
        def key_press_event(treeview, event):
            if blagui.is_accel(event, "<Ctrl>L"):
                self.__entry.grab_focus()
                return True
            return False
        self.__treeview.connect("key_press_event", key_press_event)
        model = gtk.ListStore(*self.__layout)
        self.__filt = model.filter_new()
        self.__filt.set_visible_func(self.__visible_func)
        self.__treeview.set_model(self.__filt)
        self.__directory = blacfg.getstring("general", "filesystem.directory")

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

        self.__treeview.append_column(c)

        # TODO: turn this into nemo's size column (for files, display the size,
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
        c.set_cell_data_func(r, self.__last_modified_cb)
        c.set_min_width(width + 12 + r.get_property("xpad"))

        self.__treeview.append_column(c)
        self.__treeview.connect("row_activated", self.__open)
        self.__update_directory(self.__directory)
        self.__treeview.columns_autosize()

        sw = BlaScrolledWindow()
        sw.add(self.__treeview)
        vbox.pack_start(sw, expand=True)

        # The search bar
        hbox = gtk.HBox()
        hbox.pack_start(gtk.Label("Filter:"), expand=False, padding=2)

        self.__filter_entry = gtk.Entry()
        self.__filter_entry.set_icon_from_stock(gtk.ENTRY_ICON_SECONDARY,
                                                gtk.STOCK_CLEAR)
        self.__filter_entry.connect(
            "icon_release", lambda *x: x[0].delete_text(0, -1))
        self.__filter_entry.connect(
            "changed", self.__filter_parameters_changed)
        self.__filter_entry.connect(
            "activate", lambda *x: self.__filt.refilter())
        hbox.pack_start(self.__filter_entry, expand=True)

        button = gtk.Button()
        button.add(
            gtk.image_new_from_stock(gtk.STOCK_FIND, gtk.ICON_SIZE_BUTTON))
        button.connect("clicked", lambda *x: self.__filt.refilter())
        hbox.pack_start(button, expand=False)
        vbox.pack_start(hbox, expand=False)

        self.pack_start(vbox)

    def __get_pixbuf(self, icon_name):
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

    def __visible_func(self, model, iterator):
        # FIXME: depending on the number of items in the model this approach is
        #        slow. maybe filter "offline" as we do for playlists and
        #        populate a new model with the result
        try:
            # FIXME: now this is slow as hell as this gets called for every
            #        iterator. it's just temporary though until we refactored
            #        the library browser's treeview code
            tokens = self.__filter_entry.get_text().strip().split()
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

    def __filter_parameters_changed(self, entry):
        filter_string = self.__filter_entry.get_text()
        if (blacfg.getboolean("general", "search.after.timeout") or
            not filter_string):
            gobject.source_remove(self.__fid)
            def activate():
                self.__filt.refilter()
                return False
            self.__fid = gobject.timeout_add(500, activate)

    def __update_directory(self, directory=None, refresh=False,
                           add_to_history=True):
        if not refresh:
            if directory is None:
                print_w("Directory must not be None")
                return False
            directory = os.path.expanduser(directory)
            # Got a relative path?
            if not os.path.isabs(directory):
                directory = os.path.join(self.__directory, directory)
            if not os.path.exists(directory):
                blaguiutils.error_dialog(
                    "Could not find \"%s\"." % directory,
                    "Please check the spelling and try again.")
                return False
            self.__directory = directory
            self.__entry.set_text(self.__directory)
            blacfg.set("general", "filesystem.directory", self.__directory)
            if add_to_history:
                self.__history.add(self.__directory)

        # FIXME: don't use gtk's model filter capabilities
        # TODO: keep the selection after updating the model
        model = self.__filt.get_model()
        self.__treeview.freeze_child_notify()
        model.clear()

        for dirpath, dirnames, filenames in os.walk(self.__directory):
            for d in sorted(dirnames, key=str.lower):
                if d.startswith("."):
                    continue
                path = os.path.join(self.__directory, d)
                model.append([path, self.__pixbufs["directory"], d])

            for f in sorted(filenames, key=str.lower):
                if f.startswith("."):
                    continue
                path = os.path.join(self.__directory, f)
                # TODO: use this instead (profile the overhead first though):
                #         f = gio.File(path)
                #         info = f.query_info("standard::content-type")
                #         mimetype = info.get_content_type()
                mimetype = gio.content_type_guess(path)
                try:
                    pb = self.__pixbufs[mimetype]
                except KeyError:
                    icon_names = gio.content_type_get_icon(mimetype)
                    pb = self.__pixbufs["file"]
                    if icon_names:
                        for icon_name in icon_names.get_names():
                            pb_new = self.__get_pixbuf(icon_name)
                            if pb_new:
                                self.__pixbufs[mimetype] = pb_new
                                pb = pb_new
                model.append([path, pb, f])
            break

        try:
            self.__monitor.cancel()
        except AttributeError:
            pass

        # FIXME: this seems to cease working after handling an event
        self.__monitor = gio.File(self.__directory).monitor_directory(
            flags=gio.FILE_MONITOR_NONE)
        self.__monitor.connect("changed", self.__process_event)

        self.__treeview.thaw_child_notify()
        return False

    def __process_event(self, monitor, filepath, other_filepath, type_):
        gobject.source_remove(self.__uid)
        self.__uid = gobject.timeout_add(
            2000, lambda *x: self.__update_directory(refresh=True,
                                                     add_to_history=False))

    def __update_from_history(self, backwards):
        if backwards:
            path = self.__history.get(next=False)
        else:
            path = self.__history.get(next=True)

        if path:
            self.__update_directory(directory=path, add_to_history=False)

    def __open(self, treeview, path, column):
        model = treeview.get_model()
        entry = model[path][0]
        if os.path.isdir(entry):
            model = self.__update_directory(entry)
            return True
        return False

    def __last_modified_cb(self, column, renderer, model, iterator):
        path = model[iterator][0]
        try:
            text = time.ctime(os.path.getmtime(path))
        except OSError:
            text = ""
        renderer.set_property("text", text)

    def __drag_data_get(self, drag_context, selection_data, info, timestamp):
        model, paths = self.__treeview.get_selection().get_selected_rows()
        uris = blautil.filepaths2uris([model[path][0] for path in paths])
        selection_data.set_uris(uris)

class BlaBrowsers(gtk.Notebook):
    def __init__(self):
        super(BlaBrowsers, self).__init__()

        type(self).__library_browser = BlaLibraryBrowser(self)
        self.__file_browser = BlaFileBrowser(self)
        self.append_page(self.__library_browser, gtk.Label("Library"))
        self.append_page(self.__file_browser, gtk.Label("Filesystem"))

        self.show_all()

        page_num = blacfg.getint("general", "browser.view")
        if page_num not in (0, 1):
            page_num = 0
        self.set_current_page(page_num)
        self.connect("switch_page",
                     lambda *x: blacfg.set("general", "browser.view", x[-1]))

