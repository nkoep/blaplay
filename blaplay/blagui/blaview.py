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

import os

import glib
import gobject
import gtk
import cairo
import pango

import blaplay
from blaplay import (blaconst, blacfg, bladb, blaplayer, blametadata, blautils,
        blagui)
player = blaplayer.player
library = bladb.library
from blaplay.blagui import blaguiutils
from blaplaylist import BlaPlaylist, BlaQueue
from blaradio import BlaRadio
from blaeventbrowser import BlaEventBrowser
from blareleasebrowser import BlaReleaseBrowser
from blaplay.formats._identifiers import *


class BlaSidePane(gtk.VBox):
    track = None
    __VIEWS = ["Playlists", "Queue", "Radio", "Recommended events",
            "New releases"]
    __MIN_WIDTH = 175
    __delay = 100
    __tid = -1
    __lock = blautils.BlaLock(strict=True)

    class BlaCoverDisplay(gtk.Viewport):
        __alpha = 1.0
        __cover = None
        __pb = None

        def __init__(self):
            super(BlaSidePane.BlaCoverDisplay, self).__init__()
            self.set_shadow_type(gtk.SHADOW_IN)
            self.connect("realize", lambda *x: self.update_colors())

            self.__da = gtk.DrawingArea()
            self.__da.add_events(gtk.gdk.BUTTON_PRESS_MASK)
            self.__da.connect_object(
                    "expose_event", BlaSidePane.BlaCoverDisplay.__expose, self)
            self.__da.connect_object("button_press_event",
                    BlaSidePane.BlaCoverDisplay.__button_press_event, self)
            self.add(self.__da)

            def size_allocate(*args):
                self.__img_size = self.__da.get_allocation()[-1]
                self.__da.set_size_request(self.__img_size, self.__img_size)
                if self.__cover is None: self.__cover = blaconst.COVER
                self.__prepare_cover(self.__cover)
            self.connect("size_allocate", size_allocate)

        def __button_press_event(self, event):
            def open_cover(*args):
                blautils.open_with_filehandler(self.__cover,
                        "Failed to open image '%s'" % self.__cover)

            def fetch_cover(*args):
                BlaSidePane.fetcher.start(BlaSidePane.track, cover_only=True)

            def set_cover(*args):
                diag = gtk.FileChooserDialog("Select cover",
                        buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                        gtk.STOCK_OPEN, gtk.RESPONSE_OK)
                )
                diag.set_local_only(True)
                response = diag.run()
                path = diag.get_filename()
                diag.destroy()

                if response == gtk.RESPONSE_OK and path:
                    BlaSidePane.fetcher.set_cover(path)

            def delete_cover(*args):
                BlaSidePane.fetcher.set_cover()

            if (event.button == 1 and event.type == gtk.gdk._2BUTTON_PRESS and
                    self.__cover != blaconst.COVER):
                open_cover()
            elif (event.button == 3 and event.type not in
                    [gtk.gdk._2BUTTON_PRESS, gtk.gdk._3BUTTON_PRESS]):
                menu = gtk.Menu()
                sensitive = self.__cover != blaconst.COVER
                items = [
                    ("Open cover", open_cover, sensitive),
                    ("Open directory", lambda *x: blautils.open_directory(
                            os.path.dirname(self.__cover)), sensitive), None,
                    ("Fetch cover", fetch_cover, True),
                    ("Set cover...", set_cover, True),
                    ("Delete cover", delete_cover, sensitive)
                ]
                track = BlaSidePane.track
                if (player.get_state() == blaconst.STATE_STOPPED or
                        not track[ARTIST] or not track[ALBUM]):
                    state = False
                else: state = True

                for item in items:
                    if not item: m = gtk.SeparatorMenuItem()
                    else:
                        label, callback, sensitive = item
                        m = gtk.MenuItem(label)
                        m.connect("activate", callback)
                        m.set_sensitive(sensitive)
                    menu.append(m)

                menu.show_all()
                menu.popup(None, None, None, event.button, event.time)

            return False

        def __prepare_cover(self, cover):
            try: pb = gtk.gdk.pixbuf_new_from_file(cover)
            except glib.GError:
                try:
                    if cover != blaconst.COVER: os.unlink(cover)
                except OSError: pass
                if self.__cover == blaconst.COVER: return False
                pb = gtk.gdk.pixbuf_new_from_file(blaconst.COVER)

            pb = pb.scale_simple(
                    self.__img_size, self.__img_size, gtk.gdk.INTERP_HYPER)
            self.__pb_old = self.__pb
            self.__pb = pb
            self.__cover = cover
            return True

        def __expose(self, *args):
            cr = self.__da.window.cairo_create()
            cr.set_source_color(self.__bg_color)
            x, y, width, height = self.get_allocation()

            # fill background
            cr.rectangle(0, 0, width, height)
            cr.fill()
            if not self.__pb: return

            # draw old cover
            cr.set_source_pixbuf(self.__pb_old, 0, 0)
            cr.paint_with_alpha(self.__alpha)

            # draw new cover
            cr.set_source_pixbuf(self.__pb, 0, 0)
            cr.paint_with_alpha(1.0 - self.__alpha)

        def update(self, cover, force_download):
            def crossfade():
                repeat = False
                if self.__alpha > 0.0:
                    self.__alpha -= 0.05
                    repeat = True
                self.__da.queue_draw()
                return repeat

            if cover == self.__cover and not force_download: return
            if not self.__prepare_cover(cover): return
            self.__alpha = 1.0
            # 25 ms intervals for 40 fps
            gobject.timeout_add(25, crossfade)

        def update_colors(self):
            if blacfg.getboolean("colors", "overwrite"):
                self.__bg_color = gtk.gdk.Color(
                        blacfg.getstring("colors", "background"))
            else: self.__bg_color = self.get_style().bg[gtk.STATE_NORMAL]

    def __init__(self):
        super(BlaSidePane, self).__init__(spacing=5)

        notebook = gtk.Notebook()
        notebook.set_scrollable(True)

        # create the cover art and lyrics display
        self.__tv = gtk.TextView()
        self.__tv.set_size_request(self.__MIN_WIDTH, -1)
        self.__tv.set_editable(False)
        self.__tv.set_cursor_visible(False)
        self.__tv.set_wrap_mode(gtk.WRAP_WORD)
        self.__tv.set_justification(gtk.JUSTIFY_CENTER)

        sw = blaguiutils.BlaScrolledWindow()
        sw.set_shadow_type(gtk.SHADOW_NONE)
        sw.add(self.__tv)
        self.__style = self.__tv.get_modifier_style().copy()
        self.__tb = self.__tv.get_buffer()
        self.__tb.create_tag("bold", weight=pango.WEIGHT_BOLD)
        self.__tb.create_tag("large", scale=pango.SCALE_LARGE)
        self.__tb.create_tag("italic", style=pango.STYLE_ITALIC)
        self.__tag = self.__tb.create_tag("color")

        # create the biography display
        self.__tv2 = gtk.TextView()
        self.__tv2.set_size_request(self.__MIN_WIDTH, -1)
        self.__tv2.set_editable(False)
        self.__tv2.set_cursor_visible(False)
        self.__tv2.set_wrap_mode(gtk.WRAP_WORD)
        self.__tv2.set_justification(gtk.JUSTIFY_CENTER)

        sw2 = blaguiutils.BlaScrolledWindow()
        sw2.set_shadow_type(gtk.SHADOW_NONE)
        sw2.add(self.__tv2)
        self.__tb2 = self.__tv2.get_buffer()
        self.__tb2.create_tag("bold", weight=pango.WEIGHT_BOLD)
        self.__tb2.create_tag("large", scale=pango.SCALE_LARGE)
        self.__tag2 = self.__tb2.create_tag("color")

        # view selector
        viewport = gtk.Viewport()
        viewport.set_shadow_type(gtk.SHADOW_IN)
        self.__treeview = blaguiutils.BlaTreeViewBase(multicol=False)
        self.__treeview.get_selection().set_mode(gtk.SELECTION_SINGLE)
        self.__treeview.set_headers_visible(False)
        self.__treeview.set_property("rules_hint", True)
        self.__treeview.connect("popup", self.__popup_menu)
        r = gtk.CellRendererText()
        r.set_property("ellipsize", pango.ELLIPSIZE_END)
        self.__treeview.insert_column_with_attributes(-1, "View", r, text=0)
        viewport.add(self.__treeview)
        model = gtk.ListStore(gobject.TYPE_STRING)
        self.__treeview.set_model(model)
        [model.append([item]) for idx, item in enumerate(self.__VIEWS)]
        selection = self.__treeview.get_selection()
        selection.select_path(blacfg.getint("general", "view"))
        self.__treeview.get_selection().connect(
                "changed", self.__selection_changed)

        self.__cover_display = BlaSidePane.BlaCoverDisplay()

        hbox = gtk.HBox(spacing=5)
        hbox.pack_start(viewport, expand=True)
        hbox.pack_start(self.__cover_display, expand=False)

        notebook.append_page(sw, gtk.Label("Lyrics"))
        notebook.append_page(sw2, gtk.Label("Biography"))

        self.pack_start(notebook, expand=True)
        self.pack_start(hbox, expand=False)

        self.update_colors()

        type(self).fetcher = blametadata.BlaFetcher()
        self.fetcher.connect_object(
                "lyrics", BlaSidePane.__update_lyrics, self)
        self.fetcher.connect("cover", lambda fetcher, cover, force_download:
                self.__cover_display.update(cover, force_download))
        self.fetcher.connect_object(
                "biography", BlaSidePane.__update_biography, self)

        self.show_all()

        page_num = blacfg.getint("general", "metadata.view")
        if page_num not in [0, 1]: page_num = 0
        notebook.set_current_page(page_num)
        notebook.connect("switch_page",
                lambda *x: blacfg.set("general", "metadata.view", x[-1]))

    def __popup_menu(self, treeview, event):
        menu = gtk.Menu()
        m = gtk.MenuItem("Clear queue")
        m.connect("activate", lambda *x: BlaQueue.clear())
        menu.append(m)
        menu.show_all()
        menu.popup(None, None, None, event.button, event.time)

    def __selection_changed(self, selection):
        view = selection.get_selected_rows()[-1][0][0]
        states = [False] * self.__treeview.get_model().iter_n_children(None)
        states[view] = True
        for idx, view in enumerate(blaconst.MENU_VIEWS):
            action = blagui.uimanager.get_widget(view)
            action.set_active(states[idx])

    def __update_track(self, track):
        begin = self.__tb.get_start_iter()
        begin2 = self.__tb2.get_start_iter()

        # set track name and artist
        title = track[TITLE]
        if not title: title = track.basename
        artist = track[ARTIST]

        self.__tb.insert_with_tags_by_name(
                begin, "\n%s" % title, "bold", "large", "color")
        if artist:
            self.__tb.insert_with_tags_by_name(
                    begin, "\n%s" % artist, "italic", "color")
            self.__tb2.insert_with_tags_by_name(
                    begin2, "\n%s" % artist, "bold", "large", "color")

    def __update_lyrics(self, lyrics):
        if lyrics:
            self.__tb.insert_with_tags_by_name(self.__tb.get_end_iter(),
                    "\n\n%s\n" % lyrics, "color")

    def __update_biography(self, image, biography):
        iterator = self.__tb2.get_end_iter()

        if image:
            try: image = gtk.gdk.pixbuf_new_from_file(image)
            except glib.GError:
                try: os.unlink(image)
                except OSError: pass
            else:
                width = image.get_width()
                if width > self.__MIN_WIDTH:
                    image = image.scale_simple(self.__MIN_WIDTH,
                            int(image.get_height() * (self.__MIN_WIDTH /
                            float(width))), gtk.gdk.INTERP_HYPER
                    )
                self.__tb2.insert(iterator, "\n\n")
                self.__tb2.insert_pixbuf(iterator, image)

        if biography:
            self.__tb2.insert_with_tags_by_name(iterator,
                    "\n\n%s\n" % biography, "color")

    def __clear(self):
        # decorating this with blautils.gtk_thread causes a deadlock so we use
        # a regular lock instead
#        with self.__lock:
        self.__tb.delete(
                self.__tb.get_start_iter(), self.__tb.get_end_iter())
        self.__tb2.delete(
                self.__tb2.get_start_iter(), self.__tb2.get_end_iter())

    def update_view(self, view):
        path = self.__treeview.get_selection().get_selected_rows()[-1][0][0]
        if view == path: return True
        self.__treeview.set_cursor((view,))

    def update_colors(self):
        textviews = [(self.__tv, self.__tag), (self.__tv2, self.__tag2)]
        for tv, tag in textviews:
            if blacfg.getboolean("colors", "overwrite"):
                color = gtk.gdk.Color(
                        blacfg.getstring("colors", "background"))
                tv.modify_base(gtk.STATE_NORMAL, color)

                color = gtk.gdk.Color(
                        blacfg.getstring("colors", "selected.rows"))
                tv.modify_base(gtk.STATE_ACTIVE, color)
                tv.modify_base(gtk.STATE_SELECTED, color)

                color = gtk.gdk.Color(
                        blacfg.getstring("colors", "active.text"))
                tv.modify_text(gtk.STATE_SELECTED, color)
                tv.modify_text(gtk.STATE_ACTIVE, color)
                tag.set_property("foreground-gdk", color)
            else:
                tv.modify_style(self.__style)
                tag.set_property("foreground-gdk",
                        self.__style.fg[gtk.STATE_NORMAL])

    def update_track(self):
        def worker(track):
            with self.__lock:
                self.__update_track(track)
                self.fetcher.start(track)
                return False

        gobject.source_remove(self.__tid)

        track = player.get_track()
        state = player.get_state()

        if track == self.track: return
        elif state == blaconst.STATE_STOPPED:
            self.__clear()
            type(self).track = None
            self.__cover_display.update(blaconst.COVER, False)
        else:
            self.__clear()
            self.__tid = gobject.timeout_add(self.__delay, worker, track)
            type(self).track = track

    def update_count(self, widget, view, count):
        model = self.__treeview.get_model()
        model[view][0] = ("%s (%d)" % (self.__VIEWS[view], count) if count > 0
                else self.__VIEWS[view])

class BlaView(gtk.HPaned):
    def __init__(self):
        super(BlaView, self).__init__()
        type(self).views = [BlaPlaylist(), BlaQueue(), BlaRadio(),
                BlaEventBrowser(), BlaReleaseBrowser()]
        type(self).__container = gtk.Viewport()
        self.__container.set_shadow_type(gtk.SHADOW_NONE)
        type(self).__side_pane = BlaSidePane()

        player.connect(
                "state_changed", lambda *x: self.__side_pane.update_track())
        [self.views[view].connect("count_changed",
                self.__side_pane.update_count) for view in
                [blaconst.VIEW_PLAYLISTS, blaconst.VIEW_QUEUE,
                blaconst.VIEW_EVENTS, blaconst.VIEW_RELEASES]
        ]

        self.show_all()
        self.__container.show_all()
        self.__side_pane.show()

        self.pack1(self.__container, resize=True, shrink=False)
        self.pack2(self.__side_pane, resize=False, shrink=False)

        self.views[blaconst.VIEW_PLAYLISTS].restore()

        self.update_view(blacfg.getint("general", "view"))
        self.set_show_side_pane(blacfg.getboolean("general", "side.pane"))

    def set_show_side_pane(self, state):
        self.__side_pane.set_visible(state)
        blacfg.setboolean("general", "side.pane", state)

    @classmethod
    def update_view(cls, view):
        child = cls.__container.get_child()
        if child is not None: cls.__container.remove(child)
        child = cls.views[view]
        if child.get_parent() is not None: child.unparent()
        cls.__container.add(child)

        # not all menu items are available for all views so update them
        # accordingly
        blagui.update_menu(view)
        cls.__side_pane.update_view(view)
        blacfg.set("general", "view", view)

    @classmethod
    def update_colors(cls):
        cls.__side_pane.update_colors()

    @classmethod
    def clear(cls, *args):
        view = blacfg.getint("general", "view")
        if view in [blaconst.VIEW_PLAYLISTS, blaconst.VIEW_QUEUE]:
            cls.views[view].clear()

    @classmethod
    def select(cls, type_):
        view = blacfg.getint("general", "view")
        if view in [blaconst.VIEW_PLAYLISTS, blaconst.VIEW_QUEUE]:
            cls.views[view].select(type_)

    @classmethod
    def cut(cls, *args):
        view = blacfg.getint("general", "view")
        if view in [blaconst.VIEW_PLAYLISTS, blaconst.VIEW_QUEUE]:
            cls.views[view].cut()

    @classmethod
    def copy(cls, *args):
        view = blacfg.getint("general", "view")
        if view in [blaconst.VIEW_PLAYLISTS, blaconst.VIEW_QUEUE]:
            cls.views[view].copy()

    @classmethod
    def paste(cls, *args):
        view = blacfg.getint("general", "view")
        if view in [blaconst.VIEW_PLAYLISTS, blaconst.VIEW_QUEUE]:
            cls.views[view].paste()

    @classmethod
    def remove(cls, *args):
        view = blacfg.getint("general", "view")
        if view in [blaconst.VIEW_PLAYLISTS, blaconst.VIEW_QUEUE]:
            cls.views[view].remove()

