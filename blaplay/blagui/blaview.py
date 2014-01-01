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

import gobject
import gtk
import cairo
import pango

import blaplay
player = blaplay.bla.player
library = blaplay.bla.library
from blaplay.blacore import blaconst, blacfg
from blaplay import blautil, blagui
from blaplay.formats._identifiers import *
from blawindows import BlaScrolledWindow
from blastatusbar import BlaStatusbar
from blaplay.blautil import blametadata
import blaguiutils


class BlaSidePane(gtk.VBox):
    track = None

    __MIN_WIDTH = 175
    __DELAY = 100

    __tid = -1
    __timestamp = -1

    class BlaCoverDisplay(gtk.Viewport):
        __alpha = 1.0
        __cover = None
        __pb = None
        __tid = -1
        __timestamp = -1

        def __init__(self):
            super(BlaSidePane.BlaCoverDisplay, self).__init__()
            self.set_shadow_type(gtk.SHADOW_IN)

            # Set up the drawing area.
            self.__is_video_canvas = False
            from blavideo import BlaVideoCanvas
            drawing_area = BlaVideoCanvas()
            self.__cid = drawing_area.connect_object(
                "expose_event",
                BlaSidePane.BlaCoverDisplay.__expose_event, self)
            drawing_area.connect_object(
                "button_press_event",
                BlaSidePane.BlaCoverDisplay.__button_press_event, self)
            self.add(drawing_area)

            # Make sure the cover area is a square.
            def size_allocate(*args):
                height = self.get_allocation()[-1]
                self.set_size_request(height, height)
                if self.__cover is None:
                    self.__cover = blaconst.COVER
                self.__prepare_cover(self.__cover)
            self.connect("size_allocate", size_allocate)

            # We have to guarantee that the drawing_area is realized after
            # startup, even if the side pane is set to hidden in the config.
            def startup_complete(*args):
                drawing_area.realize()
            blaplay.bla.connect("startup_complete", startup_complete)

        def __update_timestamp(self):
            # Update and return the new timestamp.
            self.__timestamp = gobject.get_current_time()
            return self.__timestamp

        def __button_press_event(self, event):
            def open_cover(*args):
                blautil.open_with_filehandler(
                    self.__cover, "Failed to open image '%s'" % self.__cover)

            def fetch_cover(*args):
                BlaSidePane.fetcher.fetch_cover(
                    BlaSidePane.track, self.__update_timestamp(),
                    force_download=True)

            def set_cover(*args):
                diag = gtk.FileChooserDialog(
                    "Select cover",
                    buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                             gtk.STOCK_OPEN, gtk.RESPONSE_OK))
                diag.set_local_only(True)
                response = diag.run()
                path = diag.get_filename()
                diag.destroy()

                if response == gtk.RESPONSE_OK and path:
                    BlaSidePane.fetcher.set_cover(
                        self.__update_timestamp(), path)

            def delete_cover(*args):
                BlaSidePane.fetcher.set_cover(self.__update_timestamp())

            # If the cover art display is used to display video delegate the
            # button event to the default handler.
            if (blacfg.getint("general", "view") != blaconst.VIEW_VIDEO and
                player.video):
                return False

            if (event.button == 1 and event.type == gtk.gdk._2BUTTON_PRESS and
                self.__cover != blaconst.COVER):
                open_cover()
            elif (event.button == 3 and
                  event.type not in [gtk.gdk._2BUTTON_PRESS,
                                     gtk.gdk._3BUTTON_PRESS]):
                menu = gtk.Menu()
                sensitive = self.__cover != blaconst.COVER
                items = [
                    ("Open in image viewer", open_cover, sensitive),
                    ("Open directory", lambda *x: blautil.open_directory(
                     os.path.dirname(self.__cover)), sensitive),
                    None,
                    ("Fetch cover", fetch_cover, True),
                    ("Set cover...",
                     lambda *x: set_cover(self.__update_timestamp()), True),
                    ("Delete cover", delete_cover, sensitive)
                ]
                track = BlaSidePane.track
                if (player.get_state() == blaconst.STATE_STOPPED or
                    not track[ARTIST] or not track[ALBUM]):
                    state = False
                else:
                    state = True

                for item in items:
                    if not item:
                        m = gtk.SeparatorMenuItem()
                    else:
                        label, callback, sensitive = item
                        m = gtk.MenuItem(label)
                        m.connect("activate", callback)
                        m.set_sensitive(sensitive)
                    menu.append(m)

                menu.show_all()
                menu.popup(None, None, None, event.button, event.time)

            return True

        def __prepare_cover(self, cover):
            try:
                pb = gtk.gdk.pixbuf_new_from_file(cover)
            except gobject.GError:
                if cover != blaconst.COVER:
                    try:
                        os.unlink(cover)
                    except OSError:
                        pass
                if self.__cover == blaconst.COVER:
                    return False
                pb = gtk.gdk.pixbuf_new_from_file(blaconst.COVER)

            height = self.get_allocation()[-1]
            pb = pb.scale_simple(height, height, gtk.gdk.INTERP_HYPER)
            self.__pb_prev = self.__pb
            self.__pb = pb
            self.__cover = cover

            return True

        def __expose_event(self, *args):
            # FIXME: If the player is paused and the video canvas gets exposed
            #        the last queued event paints the canvas in pure black
            #        AFTER gstreamer repaints the last active frame of the
            #        video. Obviously, we want the last active frame to be
            #        seen.
            if self.__is_video_canvas and player.video:
                # Be sure to cancel any crossfade animations.
                self.__alpha = 0.0
                return False

            cr = self.child.window.cairo_create()
            cr.set_source_color(self.get_style().bg[gtk.STATE_NORMAL])
            x, y, width, height = self.get_allocation()

            # Fill background.
            cr.rectangle(0, 0, width, height)
            cr.fill()
            if not self.__pb:
                return

            alpha = blautil.clamp(0.0, 1.0, self.__alpha)

            # Draw the old cover.
            cr.set_source_pixbuf(self.__pb_prev, 0, 0)
            cr.paint_with_alpha(alpha)

            # Draw the new cover.
            cr.set_source_pixbuf(self.__pb, 0, 0)
            cr.paint_with_alpha(1.0 - alpha)

            # Decrease the alpha value to create a linear fade between covers.
            self.__alpha -= 0.05

        @blautil.idle
        def update(self, timestamp, cover, force):
            def crossfade():
                if self.__alpha > 0.0:
                    self.child.queue_draw()
                    return True
                return False

            if (timestamp != self.__timestamp or
                cover == self.__cover and not force or
                not self.__prepare_cover(cover)):
                return

            self.__alpha = 1.0
            # Use 25 ms intervals for an update rate of 40 fps.
            gobject.timeout_add(25, crossfade)

        def fetch_cover(self):
            BlaSidePane.fetcher.fetch_cover(
                BlaSidePane.track, self.__update_timestamp())

        def use_as_video_canvas(self, yes):
            if yes:
                if not self.__is_video_canvas:
                    self.__is_video_canvas = True
                    self.__cover = None
                    self.child.queue_draw()
                    player.set_xwindow_id(self.child.window.xid)
            else:
                self.reset()

        def reset(self):
            self.__is_video_canvas = False
            self.update(self.__update_timestamp(), blaconst.COVER, True)

        def get_video_canvas(self):
            return self.child

    def __init__(self, views):
        super(BlaSidePane, self).__init__(spacing=blaconst.WIDGET_SPACING)

        notebook = gtk.Notebook()
        notebook.set_scrollable(True)

        # Set up the lyrics textview.
        self.__tv = gtk.TextView()
        self.__tv.set_size_request(self.__MIN_WIDTH, -1)
        self.__tv.set_editable(False)
        self.__tv.set_cursor_visible(False)
        self.__tv.set_wrap_mode(gtk.WRAP_WORD)
        self.__tv.set_justification(gtk.JUSTIFY_CENTER)

        sw = BlaScrolledWindow()
        sw.set_shadow_type(gtk.SHADOW_NONE)
        sw.add(self.__tv)
        self.__style = self.__tv.get_modifier_style().copy()
        self.__tb = self.__tv.get_buffer()
        self.__tb.create_tag("bold", weight=pango.WEIGHT_BOLD)
        self.__tb.create_tag("large", scale=pango.SCALE_LARGE)
        self.__tb.create_tag("italic", style=pango.STYLE_ITALIC)
        self.__tag = self.__tb.create_tag("color")

        # Set up the bio textview.
        # TODO: give the textviews and textbuffers some more meaningful names
        self.__tv2 = gtk.TextView()
        self.__tv2.set_size_request(self.__MIN_WIDTH, -1)
        self.__tv2.set_editable(False)
        self.__tv2.set_cursor_visible(False)
        self.__tv2.set_wrap_mode(gtk.WRAP_WORD)
        self.__tv2.set_justification(gtk.JUSTIFY_CENTER)

        sw2 = BlaScrolledWindow()
        sw2.set_shadow_type(gtk.SHADOW_NONE)
        sw2.add(self.__tv2)
        self.__tb2 = self.__tv2.get_buffer()
        self.__tb2.create_tag("bold", weight=pango.WEIGHT_BOLD)
        self.__tb2.create_tag("large", scale=pango.SCALE_LARGE)
        self.__tag2 = self.__tb2.create_tag("color")

        # Set up the view selector.
        viewport = gtk.Viewport()
        viewport.set_shadow_type(gtk.SHADOW_IN)
        self.__treeview = blaguiutils.BlaTreeViewBase(multicol=False)
        self.__treeview.get_selection().set_mode(gtk.SELECTION_SINGLE)
        self.__treeview.set_headers_visible(False)
        self.__treeview.set_property("rules_hint", True)
        self.__treeview.connect("popup", self.__popup_menu)
        r = gtk.CellRendererText()
        r.set_property("ellipsize", pango.ELLIPSIZE_END)
        c = gtk.TreeViewColumn()
        c.pack_start(r, expand=True)
        c.add_attribute(r, "text", 0)
        r = gtk.CellRendererText()
        r.set_alignment(1.0, 0.5)
        c.pack_start(r, expand=False)
        def cell_data_func(column, renderer, model, iterator):
            count = model[iterator][1]
            renderer.set_property(
                "markup", "<i>(%d)</i>" % count if count > 0 else "")
        c.set_cell_data_func(r, cell_data_func)
        self.__treeview.append_column(c)
        viewport.add(self.__treeview)
        model = gtk.ListStore(gobject.TYPE_STRING, gobject.TYPE_INT)
        self.__treeview.set_model(model)
        [model.append([view.view_name, 0]) for view in views]
        selection = self.__treeview.get_selection()
        selection.select_path(blacfg.getint("general", "view"))
        self.__treeview.get_selection().connect(
            "changed", self.__selection_changed)

        self.cover_display = BlaSidePane.BlaCoverDisplay()

        hbox = gtk.HBox(spacing=5)
        hbox.pack_start(viewport, expand=True)
        hbox.pack_start(self.cover_display, expand=False, fill=True)

        notebook.append_page(sw, gtk.Label("Lyrics"))
        notebook.append_page(sw2, gtk.Label("Biography"))

        # Add the `modify metadata' button.
        button = gtk.Button()
        button.set_tooltip_text("Edit metadata")
        button.set_relief(gtk.RELIEF_NONE)
        button.set_focus_on_click(False)
        button.add(
            gtk.image_new_from_stock(gtk.STOCK_EDIT, gtk.ICON_SIZE_MENU))
        style = gtk.RcStyle()
        style.xthickness = style.ythickness = 0
        button.modify_style(style)
        button.connect("clicked", lambda *x: print_d("TODO"))
        button.show_all()
        # TODO: implement a widget to edit metadata
#        notebook.set_action_widget(button, gtk.PACK_END)

        self.pack_start(notebook, expand=True)
        self.pack_start(hbox, expand=False)

        # Hook up the metadata callbacks.
        BlaSidePane.fetcher = blametadata.BlaFetcher()
        self.fetcher.connect_object(
            "lyrics", BlaSidePane.__update_lyrics, self)
        self.fetcher.connect_object(
            "biography", BlaSidePane.__update_biography, self)
        self.fetcher.connect_object(
            "cover", type(self.cover_display).update, self.cover_display)

        page_num = blacfg.getint("general", "metadata.view")
        notebook.set_current_page(page_num)
        notebook.connect(
            "switch_page",
            lambda notebook, child, page_num: blacfg.set(
                "general", "metadata.view", page_num))

    def __popup_menu(self, treeview, event):
        from blaplaylist import BlaQueue

        menu = gtk.Menu()
        m = gtk.MenuItem("Clear queue")
        m.connect("activate", lambda *x: BlaQueue.clear())
        menu.append(m)
        menu.show_all()
        menu.popup(None, None, None, event.button, event.time)

    def __selection_changed(self, selection):
        view = selection.get_selected_rows()[-1][0][0]
        states = [False] * len(self.__treeview.get_model())
        states[view] = True
        for idx, view in enumerate(blaconst.MENU_VIEWS):
            action = blagui.uimanager.get_widget(view)
            action.set_active(states[idx])

    @blautil.idle
    def __update_track(self, track):
        iterator = self.__tb.get_iter_at_mark(self.__tb.get_insert())

        # Set track name and artist.
        title = track[TITLE]
        if not title:
            title = track.basename
        artist = track[ARTIST]

        self.__tb.insert_with_tags_by_name(
            iterator, "\n%s" % title, "bold", "large", "color")
        if artist:
            self.__tb.insert_with_tags_by_name(
                iterator, "\n%s" % artist, "italic", "color")

            iterator = self.__tb2.get_iter_at_mark(self.__tb2.get_insert())
            self.__tb2.insert_with_tags_by_name(
                iterator, "\n%s" % artist, "bold", "large", "color")

    @blautil.idle
    def __update_lyrics(self, timestamp, lyrics):
        if timestamp == self.__timestamp and lyrics:
            self.__tb.insert_with_tags_by_name(self.__tb.get_iter_at_mark(
                self.__tb.get_insert()), "\n\n%s\n" % lyrics, "color")

    @blautil.idle
    def __update_biography(self, timestamp, image, biography):
        if timestamp != self.__timestamp:
            return

        iterator = self.__tb2.get_iter_at_mark(self.__tb2.get_insert())

        if image:
            try:
                image = gtk.gdk.pixbuf_new_from_file(image)
            except gobject.GError:
                try:
                    os.unlink(image)
                except OSError:
                    pass
            else:
                width = image.get_width()
                if width > self.__MIN_WIDTH:
                    height = int(image.get_height() *
                                 (self.__MIN_WIDTH / float(width)))
                    image = image.scale_simple(
                        self.__MIN_WIDTH, height, gtk.gdk.INTERP_HYPER)
                self.__tb2.insert(iterator, "\n\n")
                self.__tb2.insert_pixbuf(iterator, image)

        if biography:
            self.__tb2.insert_with_tags_by_name(iterator,
                "\n\n%s\n" % biography, "color")

    @blautil.idle
    def __clear(self):
        self.__tb.delete(
            self.__tb.get_start_iter(), self.__tb.get_end_iter())
        self.__tb2.delete(
            self.__tb2.get_start_iter(), self.__tb2.get_end_iter())

    def update_view(self, view):
        path = self.__treeview.get_selection().get_selected_rows()[-1][0][0]
        if view == path:
            return True
        self.__treeview.set_cursor((view,))

    def update_count(self, widget, view, count):
        model = self.__treeview.get_model()
        model[view][1] = count

    def update_track(self):
        def worker(track):
            self.__update_track(track)
            self.fetcher.fetch_lyrics_and_bio(track, self.__timestamp)
            self.cover_display.fetch_cover()
            return False

        gobject.source_remove(self.__tid)

        track = player.get_track()
        state = player.get_state()

        if track == self.track:
            return

        self.__clear()
        self.__timestamp = gobject.get_current_time()

        if state == blaconst.STATE_STOPPED or player.radio:
            BlaSidePane.track = None
            self.cover_display.reset()
        else:
            self.__tid = gobject.timeout_add(self.__DELAY, worker, track)
            BlaSidePane.track = track

def BlaViewMeta(view_name):
    # This returns a metaclass which automatically -- among other things --
    # attaches a view_name property that always returns the `view_name'
    # argument. We use a metaclass for defining view classes for the main view
    # outlet as it appears to be the most flexible way to add default
    # properties and signals. The __gsignals__ attribute gets stripped from a
    # class's __dict__ by gobject.GObjectMeta so we can't check for the
    # existence of the `count_changed' signal except with a custom metaclass.
    class _BlaViewMeta(blautil.BlaSingletonMeta):
        def __new__(cls, name, bases, dct):
            # Make sure at least one baseclass inherits from gobject.GObject.
            if not any([issubclass(base, gobject.GObject) for base in bases]):
                raise TypeError("%s does not inherit from gobject.GObject" %
                                name)

            # Add the view_name property.
            if "view_name" in dct:
                raise ValueError("View class %s already defines an attribute "
                                 "'view_name'" % name)
            dct["view_name"] = property(lambda self: view_name)

            # Add the count_changed signal.
            signals = dct.get("__gsignals__", {})
            if "count_changed" in signals or "count-changed" in signals:
                raise ValueError("Class %s already defines a 'count_changed' "
                                 "signal" % name)
            signals["count_changed"] = blautil.signal(2)
            dct["__gsignals__"] = signals

            # Add the init-function stub.
            if "init" not in dct:
                dct["init"] = lambda self: None

            # Add default behavior for `update_statusbar()'.
            if "update_statusbar" not in dct:
                dct["update_statusbar"] = lambda s: BlaStatusbar.set_view_info(
                    blacfg.getint("general", "view"), "")

            return super(_BlaViewMeta, cls).__new__(cls, name, bases, dct)

    return _BlaViewMeta

class BlaView(gtk.HPaned):
    def __init__(self):
        super(BlaView, self).__init__()

        from blaplaylist import BlaPlaylistManager, BlaQueue
        from blavideo import BlaVideo
        from blaradio import BlaRadio
        from blaeventbrowser import BlaEventBrowser
        from blareleasebrowser import BlaReleaseBrowser
        type(self).views = [
            BlaPlaylistManager(), BlaQueue(), BlaRadio(), BlaVideo(),
            BlaEventBrowser(), BlaReleaseBrowser()]

        type(self).__container = gtk.Viewport()
        self.__container.set_shadow_type(gtk.SHADOW_NONE)
        type(self).__side_pane = BlaSidePane(self.views)

        player.connect(
            "state_changed", lambda *x: self.__side_pane.update_track())
        # The sync handler gets called every time gstreamer needs an xwindow
        # for rendering video.
        def sync_handler():
            view = blacfg.getint("general", "view")
            if view == blaconst.VIEW_VIDEO:
                element = self.views[blaconst.VIEW_VIDEO]
            else:
                element = self.__side_pane.cover_display
                # Coerce the cover display into a video canvas.
                element.use_as_video_canvas(True)
            canvas = element.get_video_canvas()
            if canvas.get_realized():
                return canvas.window.xid
            print_w("Drawing area for video playback not yet realized")
            return 0
        player.set_sync_handler(sync_handler)

        for view in self.views:
            view.connect("count_changed", self.__side_pane.update_count)
            view.init()

        self.show()
        self.__container.show_all()
        self.__side_pane.show_all()

        self.pack1(self.__container, resize=True, shrink=False)
        self.pack2(self.__side_pane, resize=False, shrink=False)

        self.set_show_side_pane(blacfg.getboolean("general", "side.pane"))

    def set_show_side_pane(self, state):
        self.__side_pane.set_visible(state)
        blacfg.setboolean("general", "side.pane", state)

    @classmethod
    def update_view(cls, view, init=False):
        view_prev = blacfg.getint("general", "view")
        blacfg.set("general", "view", view)

        if player.video:
            # If the previous view was the video view coerce the cover art
            # display into acting as new video canvas.
            cls.__side_pane.cover_display.use_as_video_canvas(
                view != blaconst.VIEW_VIDEO)

        child = cls.__container.get_child()
        if child is not None:
            cls.__container.remove(child)
        child = cls.views[view]
        if child.get_parent() is not None:
            child.unparent()
        cls.__container.add(child)
        child.update_statusbar()

        # Not all menu items are available for all views so update them
        # accordingly.
        blagui.update_menu(view)
        cls.__side_pane.update_view(view)

    @classmethod
    def __mediator(cls, method_name, *args):
        view = blacfg.getint("general", "view")
        if view in (blaconst.VIEW_PLAYLISTS, blaconst.VIEW_QUEUE):
            getattr(cls.views[view], method_name)(*args)

    @classmethod
    def clear(cls, *args):
        cls.__mediator("clear")

    @classmethod
    def select(cls, type_):
        cls.__mediator("select", type_)

    @classmethod
    def cut(cls, *args):
        cls.__mediator("cut")

    @classmethod
    def copy(cls, *args):
        cls.__mediator("copy")

    @classmethod
    def paste(cls, *args):
        cls.__mediator("paste")

    @classmethod
    def remove(cls, *args):
        cls.__mediator("remove")

    @classmethod
    def remove_duplicates(cls, *args):
        cls.__mediator("remove_duplicates")

    @classmethod
    def remove_invalid_tracks(cls, *args):
        cls.__mediator("remove_invalid_tracks")

