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
import shutil
import Queue
import urllib
import json
from email.utils import parsedate_tz as parse_rfc_time
import time
import cPickle as pickle

import gobject
import gtk
import pango

import blaplay
from blaplay import blacfg, blaconst, blautils, blafm
from blaplay.blagui import blaguiutils
from blareleasebrowser import IMAGE_SIZE, BlaCellRendererPixbuf

class BlaEvent(object):
    __EMPTY_PIXBUF = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, True, 8,
                IMAGE_SIZE, IMAGE_SIZE)
    __EMPTY_PIXBUF.fill(0)

    def __init__(self, raw):
        self.__raw = raw
        self.event_name = raw["title"]
        self.event_url = raw["url"]
        self.cancelled = bool(int(raw["cancelled"]))
        self.artists = [raw["artists"]["headliner"]]
        artists = raw["artists"]["artist"]
        if not hasattr(artists, "__iter__"): artists = [artists]
        [self.artists.append(artist) for artist in artists
                if artist not in self.artists]
        try: self.artists.remove(self.event_name)
        except ValueError: pass
        self.date = time.strftime(
                "%A %d %B %Y", parse_rfc_time(raw["startDate"])[:-1])
        self.image = BlaEvent.__EMPTY_PIXBUF
        venue = raw["venue"]
        self.venue = venue["name"]
        self.city = venue["location"]["city"]
        self.country = venue["location"]["country"]

    def get_image(self, restore=False):
        image_base = os.path.join(
                blaconst.EVENTS, ("%s" % self.event_name).replace(" ", "_"))
        pixbuf = path = None
        for ext in ["jpg", "png"]:
            try:
                path = "%s.%s" % (image_base, ext)
                pixbuf = gtk.gdk.pixbuf_new_from_file(path)
                break
            except gobject.GError: pass
        else:
            if not restore:
                url = blafm.get_image_url(self.__raw["image"])
                try:
                    image, message = urllib.urlretrieve(url)
                    path = "%s.%s" % (
                            image_base, blautils.get_extension(image))
                    shutil.move(image, path)
                    pixbuf = gtk.gdk.pixbuf_new_from_file(path)
                except (IOError, gobject.GError): pass

        # resize until the smaller dimension reaches IMAGE_SIZE, then crop
        # IMAGE_SIZE x IMAGE_SIZE pixels from the center of the image in
        # case of a landscape image and from the top in case of a portrait
        try:
            width, height = pixbuf.get_width(), pixbuf.get_height()
            # portrait
            if width < height:
                height = int(height * (IMAGE_SIZE / float(width)))
                width = IMAGE_SIZE
                x = y = 0
            # landscape
            else:
                width = int(width * (IMAGE_SIZE / float(height)))
                height = IMAGE_SIZE
                x = int((width - IMAGE_SIZE) / 2)
                y = 0
            pixbuf = pixbuf.scale_simple(
                    width, height, gtk.gdk.INTERP_HYPER).subpixbuf(
                    x, y, IMAGE_SIZE, IMAGE_SIZE
            )

        except (AttributeError, gobject.GError): pass
        self.image = pixbuf or BlaEvent.__EMPTY_PIXBUF
        return path

class BlaEventBrowser(blaguiutils.BlaScrolledWindow):
    __gsignals__ = {
        "count_changed": blaplay.signal(2)
    }
    __count_recommended = 0
    __count_all = 0
    __lock = blautils.BlaLock(strict=True)

    def __init__(self):
        super(BlaEventBrowser, self).__init__()
        self.set_shadow_type(gtk.SHADOW_NONE)

        vbox = gtk.VBox()
        vbox.set_border_width(10)

        # heading
        hbox = gtk.HBox()
        items = [
            ("<b><span size=\"xx-large\">Events</span></b>",
             0.0, 0.5, 0),
            ("<b><span size=\"x-small\">powered by</span></b>",
             1.0, 1.0, 5)
        ]
        for markup, xalign, yalign, padding in items:
            label = gtk.Label()
            label.set_markup(markup)
            alignment = gtk.Alignment(xalign, yalign)
            alignment.add(label)
            hbox.pack_start(alignment, expand=True, fill=True, padding=padding)

        image = gtk.image_new_from_file(blaconst.LASTFM_LOGO)
        alignment = gtk.Alignment(1.0, 0.5)
        alignment.add(image)
        hbox.pack_start(alignment, expand=False)
        vbox.pack_start(hbox, expand=False)

        # location
        hbox_location = gtk.HBox(spacing=5)

        label = gtk.Label()
        label.set_markup("<b>Location:</b>")
        location = gtk.Label()
        country = blacfg.getstring("general", "events.country")
        city = blacfg.getstring("general", "events.city")
        if not city: location.set_markup("<i>Unspecified</i>")
        else:
            location.set_text(
                    ", ".join([city, country] if country else [city]))

        button = gtk.Button("Change location")
        button.connect(
                "clicked", self.__change_location, location)

        for widget, padding in [(label, 0), (location, 0), (button, 5)]:
            alignment = gtk.Alignment(0.0, 0.5)
            alignment.add(widget)
            hbox_location.pack_start(alignment, expand=False, padding=padding)
        vbox.pack_start(hbox_location, expand=False)

        # type selector
        self.__hbox = gtk.HBox(spacing=5)
        self.__hbox.set_border_width(10)
        items = [
            ("Recommended events", blaconst.EVENTS_RECOMMENDED),
            ("All events", blaconst.EVENTS_ALL)
        ]
        active = blacfg.getint("general", "events.filter")
        radiobutton = None
        for label, filt in items:
            radiobutton = gtk.RadioButton(radiobutton, label)
            if filt == active: radiobutton.set_active(True)
            radiobutton.connect(
                    "toggled", self.__filter_changed, filt, hbox_location)
            self.__hbox.pack_start(radiobutton, expand=False)

        self.__refresh_button = gtk.Button("Refresh")
        self.__refresh_button.connect_object(
                "clicked", BlaEventBrowser.__update_models, self)
        self.__hbox.pack_start(self.__refresh_button, expand=False)
        vbox.pack_start(self.__hbox, expand=False)

        hbox = gtk.HBox(spacing=5)
        hbox.pack_start(gtk.Label("Maximum number of results:"), expand=False)
        limit = blacfg.getint("general", "events.limit")
        adjustment = gtk.Adjustment(limit, 1.0, 100.0, 1.0, 5.0, 0.0)
        spinbutton = gtk.SpinButton(adjustment)
        spinbutton.set_numeric(True)
        spinbutton.connect("value_changed", lambda sb: blacfg.set(
                "general", "events.limit", sb.get_value()))
        hbox.pack_start(spinbutton, expand=False)
        vbox.pack_start(hbox, expand=False)

        # events list
        def cell_data_func_pixbuf(column, renderer, model, iterator):
            event = model[iterator][0]
            try: renderer.set_property("content", event.image)
            except AttributeError: renderer.set_property("content", event)

        def cell_data_func_text(column, renderer, model, iterator):
            event = model[iterator][0]
            try:
                limit = 8
                markup = "<b>%s</b>\n%%s" % event.event_name
                artists = ", ".join(event.artists[:limit])
                if len(event.artists) > limit: artists += ", and more"
                markup %= artists
            except AttributeError: markup = ""
            renderer.set_property("markup", markup.replace("&", "&amp;"))

        def cell_data_func_text2(column, renderer, model, iterator):
            event = model[iterator][0]
            try:
                markup = "<b>%s</b>\n%s\n%s" % (
                        event.venue, event.city, event.country)
            except AttributeError: markup = ""
            renderer.set_property("markup", markup.replace("&", "&amp;"))

        def cell_data_func_text3(column, renderer, model, iterator):
            event = model[iterator][0]
            try:
                if event.cancelled:
                    markup = "<span size=\"x-large\"><b>Cancelled</b></span>"
                else: raise AttributeError
            except AttributeError: markup = ""
            renderer.set_property("markup", markup.replace("&", "&amp;"))

        self.__treeview = blaguiutils.BlaTreeViewBase(
                set_button_event_handlers=False)
        self.__treeview.set_rules_hint(True)
        self.__treeview.get_selection().set_mode(gtk.SELECTION_SINGLE)
        self.__treeview.set_headers_visible(False)

        # image
        r = BlaCellRendererPixbuf()
        column = gtk.TreeViewColumn()
        column.pack_start(r, expand=False)
        column.set_cell_data_func(r, cell_data_func_pixbuf)

        # title and artists
        r = gtk.CellRendererText()
        r.set_alignment(0.0, 0.0)
        r.set_property("wrap_mode", pango.WRAP_WORD)
        r.set_property("wrap_width", 350)
        column.pack_start(r, expand=False)
        column.set_cell_data_func(r, cell_data_func_text)

        # location
        r = gtk.CellRendererText()
        r.set_alignment(0.0, 0.0)
        r.set_property("ellipsize", pango.ELLIPSIZE_END)
        column.pack_start(r)
        column.set_cell_data_func(r, cell_data_func_text2)

        # status
        r = gtk.CellRendererText()
        r.set_property("ellipsize", pango.ELLIPSIZE_END)
        column.pack_start(r)
        column.set_cell_data_func(r, cell_data_func_text3)

        self.__treeview.append_column(column)
        self.__treeview.connect("row_activated", self.__row_activated)
        self.__treeview.connect(
                "button_press_event", self.__button_press_event)
        self.__models = [
                gtk.ListStore(gobject.TYPE_PYOBJECT) for x in xrange(2)]
        self.__treeview.set_model(self.__models[active])
        vbox.pack_start(self.__treeview, expand=True, padding=10)

        self.add_with_viewport(vbox)
        self.show_all()
        if active == blaconst.EVENTS_RECOMMENDED:
            hbox_location.set_visible(False)

        gtk.quit_add(0, self.__save)

    def __save(self):
        events = [row[0] for row in self.__treeview.get_model()]
        blautils.serialize_to_file(events, blaconst.EVENTS_PATH)
        return 0

    def __change_location(self, button, location):
        diag = gtk.Dialog(title="Change location",
                buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                gtk.STOCK_OK, gtk.RESPONSE_OK),
                flags=gtk.DIALOG_DESTROY_WITH_PARENT|gtk.DIALOG_MODAL
        )
        diag.set_resizable(False)

        # country list
        country = blacfg.getstring("general", "events.country")
        entry1 = gtk.Entry()
        entry1.set_text(country)

        city = blacfg.getstring("general", "events.city")
        entry2 = gtk.Entry()
        entry2.set_text(city)

        table = gtk.Table(rows=2, columns=2, homogeneous=False)
        table.set_border_width(10)

        items = [("Country", entry1), ("City", entry2)]
        for idx, (label, entry) in enumerate(items):
            entry.connect(
                    "activate", lambda *x: diag.response(gtk.RESPONSE_OK))
            label = gtk.Label("%s:" % label)
            label.set_alignment(xalign=0.0, yalign=0.5)
            table.attach(label, idx, idx+1, 0, 1)
            table.attach(entry, idx, idx+1, 1, 2)

        diag.vbox.pack_start(table)
        diag.show_all()
        response = diag.run()

        if response == gtk.RESPONSE_OK:
            country = entry1.get_text()
            city = entry2.get_text()
        diag.destroy()

        if not city: location.set_markup("<i>Unspecified</i>")
        else:
            location.set_text(
                    ", ".join([city, country] if country else [city]))
        blacfg.set("general", "events.country", country)
        blacfg.set("general", "events.city", city)

    @blautils.gtk_thread
    @blautils.thread
    def __update_models(self):
        if self.__lock.locked(): return True
        self.__lock.acquire()
        def set_sensitive(state):
            self.__refresh_button.set_sensitive(state)
            self.__hbox.set_sensitive(state)
            self.__treeview.set_sensitive(state)
            return False
        gobject.idle_add(set_sensitive, False)

        def worker():
            while True:
                event = queue.get()
                path = event.get_image()
                if path: images.add(path)
                queue.task_done()
        images = set()
        queue = Queue.Queue()
        threads = []
        for x in xrange(3):
            t = blautils.BlaThread(target=worker)
            t.daemon = True
            threads.append(t)
            t.start()

        active = blacfg.getint("general", "events.filter")
        limit = blacfg.getint("general", "events.limit")
        country = blacfg.getstring("general", "events.country")
        city = blacfg.getstring("general", "events.city")

        # FIXME: an exception is raised in this thread if the interpreter shuts
        #        down immediately after startup when we're fetching events
        events = (
            blafm.get_events(limit=limit, recommended=True),
            blafm.get_events(limit=limit, recommended=False, country=country,
                    city=city)
        )
        if events[0]: self.__count_recommended = len(events[0])
        if events[1]: self.__count_all = len(events[1])
        items = [
            (blaconst.EVENTS_RECOMMENDED, events[0] or []),
            (blaconst.EVENTS_ALL, events[1] or [])
        ]
        for filt, events in items:
            model = gtk.ListStore(gobject.TYPE_PYOBJECT)
            previous_date = None
            for event in events:
                event = BlaEvent(event)
                date = event.date
                if previous_date != date:
                    previous_date = date
                    model.append(["\n<span size=\"larger\"><b>%s</b></span>\n"
                            % date])
                model.append([event])
                queue.put(event)
            self.__models[filt] = model

        # wait until all items are processed and kill the worker threads
        queue.join()
        map(blautils.BlaThread.kill, threads)

        # get rid of images for event that don't show up in the list anymore
        for f in set(blautils.discover(blaconst.EVENTS)).difference(images):
            try: os.unlink(f)
            except OSError: pass

        # changes to any gtk elements should be done in the main thread so wrap
        # the respective calls in idle_add's
        gobject.idle_add(set_sensitive, True)
        # TODO: only set the model when we verified that we successfully
        #       retrieved event information. this avoids that we delete a
        #       restored model
        gobject.idle_add(self.__treeview.set_model, self.__models[active])

        if active == blaconst.EVENTS_RECOMMENDED:
            count = self.__count_recommended
        else: count = self.__count_all
        gobject.idle_add(
                self.emit, "count_changed", blaconst.VIEW_EVENTS, count)

        self.__lock.release()
        return True

    def __filter_changed(self, radiobutton, filt, hbox):
        # the signal of the new active radiobutton arrives last so only change
        # the config then
        if radiobutton.get_active():
            blacfg.set("general", "events.filter", filt)
            self.__treeview.set_model(self.__models[filt])
            if filt == blaconst.EVENTS_RECOMMENDED: hbox.set_visible(False)
            else: hbox.set_visible(True)
            if filt == blaconst.EVENTS_RECOMMENDED:
                count = self.__count_recommended
            else: count = self.__count_all
            self.emit("count_changed", blaconst.VIEW_EVENTS, count)

    def __row_activated(self, treeview, path, column):
        blautils.open_url(treeview.get_model()[path][0].event_url)

    def __button_press_event(self, treeview, event):
        try: path = treeview.get_path_at_pos(*map(int, [event.x, event.y]))[0]
        except TypeError: return False

        model = treeview.get_model()
        event_ = model[path][0]
        if not isinstance(event_, BlaEvent): return True
        if event.button in [1, 2]:
            if event.type in [gtk.gdk._2BUTTON_PRESS, gtk.gdk._3BUTTON_PRESS]:
                return True
            return False

        model = treeview.get_model()
        event_url = event_.event_url
        menu = gtk.Menu()
        m = gtk.MenuItem("View event page")
        m.connect("activate", lambda *x: blautils.open_url(event_url))
        menu.append(m)
        menu.show_all()
        menu.popup(None, None, None, event.button, event.time)

        return False

    def restore(self):
        events = blautils.deserialize_from_file(blaconst.EVENTS_PATH)
        if events:
            model = gtk.ListStore(gobject.TYPE_PYOBJECT)
            # pixbufs aren't initialized when they're unpickled so we need to
            # instantiate them while restoring. to speed up restoring we force
            # the use of possibly cached images by passing True as `restore'
            # kwarg
            for event in events:
                try: event.get_image(restore=True)
                except AttributeError: pass
            [model.append([event]) for event in events]
            self.__treeview.set_model(model)

        # check for new events now and every two hours
        self.__update_models()
        gobject.timeout_add(2 * 3600 * 1000, self.__update_models)

