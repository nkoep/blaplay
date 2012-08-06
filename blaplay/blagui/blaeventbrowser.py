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

import gobject
import gtk
import pango

import blaplay
from blaplay import blacfg, blaconst, blautils, blafm#, blasongkick
from blaplay.blagui import blaguiutils
from blareleasebrowser import IMAGE_SIZE, BlaCellRendererPixbuf


class BlaEventBrowser(gtk.Notebook):
    __gsignals__ = {
        "count_changed": blaplay.signal(2)
    }
    __count_library = 0
    __count_recommended = 0
    __lock = blautils.BlaLock(strict=True)

    class Event(object):
        def __init__(self, raw):
            self.__raw = raw
            self.event_name = raw["title"]
            self.event_url = raw["url"]
            self.artists = [raw["artists"]["headliner"]]
            artists = raw["artists"]["artist"]
            if not hasattr(artists, "__iter__"): artists = [artists]
            [self.artists.append(artist) for artist in artists
                    if artist not in self.artists]
            try: self.artists.remove(self.event_name)
            except ValueError: pass
            self.date = time.strftime(
                    "%A %d %B %Y", parse_rfc_time(raw["startDate"])[:-1])
            self.image = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, True, 8,
                    IMAGE_SIZE, IMAGE_SIZE)
            self.image.fill(0)
            venue = raw["venue"]
            self.venue = venue["name"]
            self.city = venue["location"]["city"]
            self.country = venue["location"]["country"]

        def get_image(self, image_base, model, iterator):
            pixbuf = path = None
            for ext in ["jpg", "png"]:
                try:
                    path = "%s.%s" % (image_base, ext)
                    pixbuf = gtk.gdk.pixbuf_new_from_file(path)
                    break
                except gobject.GError: pass
            else:
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
            self.image = pixbuf
            model.row_changed(model.get_path(iterator), iterator)
            return path

    def __init__(self):
        super(BlaEventBrowser, self).__init__()
        self.__fetch_country_list()

        sw = blaguiutils.BlaScrolledWindow()
        sw.set_shadow_type(gtk.SHADOW_NONE)

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
        hbox = gtk.HBox(spacing=5)

        label = gtk.Label()
        label.set_markup("<b>Location:</b>")
        location = gtk.Label()
        country = blacfg.getstring("general", "events.country")
        city = blacfg.getstring("general", "events.city")
        if not city: location.set_markup("<i>Unspecified</i>")
        else:
            if country: text = "%s, %s" % (city, country)
            else: text = city
            location.set_text(text)

        button = gtk.Button("Change location")
        button.connect(
                "clicked", self.__change_location, location)

        self.__refresh_button = gtk.Button("Refresh")
        self.__refresh_button.connect_object(
                "clicked", BlaEventBrowser.__update_models, self)

        for widget, padding in [(label, 0), (location, 0), (button, 5),
                (self.__refresh_button, 0)]:
            alignment = gtk.Alignment(0.0, 0.5)
            alignment.add(widget)
            hbox.pack_start(alignment, expand=False, padding=padding)

        vbox.pack_start(hbox, expand=False)

        # type selector
        hbox = gtk.HBox(spacing=5)
        hbox.set_border_width(10)
        items = [
            ("Recommended events", blaconst.EVENTS_RECOMMENDED),
            ("All events", blaconst.EVENTS_ALL)
        ]
        active = blacfg.getint("general", "events.filter")
        radiobutton = None
        for label, type_ in items:
            radiobutton = gtk.RadioButton(radiobutton, label)
            if type_ == active: radiobutton.set_active(True)
            radiobutton.connect("toggled", self.__type_changed, type_)
            hbox.pack_start(radiobutton, expand=False)

        vbox.pack_start(hbox, expand=False)

        # events list
        def cell_data_func_pixbuf(column, renderer, model, iterator):
            event = model[iterator][0]
            try: renderer.set_property("content", event.image)
            except AttributeError: renderer.set_property("content", event)

        def cell_data_func_text(column, renderer, model, iterator):
            # TODO: wrap lines
            event = model[iterator][0]
            try:
                markup = "<b>%s</b>\n%s" % (
                        event.event_name, ", ".join(event.artists[:8]))
            except AttributeError: markup = ""
            renderer.set_property("markup", markup.replace("&", "&amp;"))

        def cell_data_func_text2(column, renderer, model, iterator):
            event = model[iterator][0]
            try: markup = "<b>%s</b>\n%s\n%s" % (
                    event.venue, event.city, event.country)
            except AttributeError: markup = ""
            renderer.set_property("markup", markup.replace("&", "&amp;"))

        self.__treeview = blaguiutils.BlaTreeViewBase(
                set_button_event_handlers=False)
        self.__treeview.set_rules_hint(True)
        self.__treeview.get_selection().set_mode(gtk.SELECTION_SINGLE)
        self.__treeview.set_headers_visible(False)
        r = BlaCellRendererPixbuf()
        column = gtk.TreeViewColumn()
        column.pack_start(r, expand=False)
        column.set_cell_data_func(r, cell_data_func_pixbuf)
        r = gtk.CellRendererText()
        r.set_alignment(0.0, 0.0)
#        r.set_property("ellipsize", pango.ELLIPSIZE_END)
        r.set_property("wrap_mode", pango.WRAP_WORD)
        r.set_property("wrap_width", 350)
        column.pack_start(r, expand=False)
        column.set_cell_data_func(r, cell_data_func_text)
        r = gtk.CellRendererText()
        r.set_alignment(0.0, 0.0)
        r.set_property("ellipsize", pango.ELLIPSIZE_END)
        column.pack_start(r)
        column.set_cell_data_func(r, cell_data_func_text2)
        self.__treeview.append_column(column)
        self.__treeview.connect("row_activated", self.__row_activated)
        self.__treeview.connect(
                "button_press_event", self.__button_press_event)
        self.__models = {}
        for key in [blaconst.EVENTS_RECOMMENDED, blaconst.EVENTS_ALL,
                blaconst.EVENTS_SONGKICK]:
            self.__models[key] = gtk.ListStore(gobject.TYPE_PYOBJECT)
        if active == blaconst.EVENTS_LASTFM:
            self.__treeview.set_model(
                    self.__models[blacfg.getint("general", "events.filter")])
        else: self.__treeview.set_model(self.__models[active])
        vbox.pack_start(self.__treeview, expand=True, padding=10)

        # check for new events now and every two hours
        self.__update_models()
        gobject.timeout_add(2 * 3600 * 1000, self.__update_models)
        sw.add_with_viewport(vbox)
        sw.get_children()[0].set_shadow_type(gtk.SHADOW_NONE)

        self.append_page(sw, gtk.Label("last.fm"))
        self.show_all()

    def __fetch_country_list(self):
        # TODO: - catch errors
        #       - keep an offline copy of the list
        # FIXME: geonames isn't free... should we just use an entry box?
        url = "http://api.geonames.org/countryInfoJSON?username=demo"
        f = urllib.urlopen(url)
        countries = json.loads(f.read())
        f.close()

        self.__countries = [""]
        return
        append = self.__countries.append
        for country in countries["geonames"]: append(country["countryName"])

        # this allows proper sorting of unicode strings
        import locale
        locale.setlocale(locale.LC_ALL, "")
        self.__countries.sort(cmp=locale.strcoll)

    def __change_location(self, button, location):
        diag = gtk.Dialog(title="Change location",
                buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                gtk.STOCK_OK, gtk.RESPONSE_OK),
                flags=gtk.DIALOG_DESTROY_WITH_PARENT|gtk.DIALOG_MODAL
        )
        diag.set_resizable(False)

        # country list
        country = blacfg.getstring("general", "events.country")
        cbe1 = gtk.combo_box_entry_new_text()
        append_text = cbe1.append_text
        map(append_text, self.__countries)
        try: cbe1.set_active(self.__countries.index(country))
        except ValueError: cbe1.child.set_text(country)

        # city entry
        city = blacfg.getstring("general", "events.city")
        cbe2 = gtk.combo_box_entry_new_text()
        # TODO
#        append_text = cbe2.append_text
#        map(append_text, self.__countries)
        try: raise ValueError#cbe2.set_active(self.__cities.index(country))
        except ValueError: cbe2.child.set_text(city)

        table = gtk.Table(rows=2, columns=2, homogeneous=False)
        table.set_border_width(10)

        items = [("Country", cbe1), ("City", cbe2)]
        for idx, (label, entry) in enumerate(items):
            entry.child.connect(
                    "activate", lambda *x: diag.response(gtk.RESPONSE_OK))
            label = gtk.Label("%s:" % label)
            label.set_alignment(xalign=0.0, yalign=0.5)
            table.attach(label, idx, idx+1, 0, 1)
            table.attach(entry, idx, idx+1, 1, 2)

        diag.vbox.pack_start(table)
        diag.show_all()
        response = diag.run()

        if response == gtk.RESPONSE_OK:
            country = cbe1.child.get_text()
            city = cbe2.child.get_text()
        diag.destroy()

        if not city: location.set_markup("<i>Unspecified</i>")
        else:
            if country: text = "%s, %s" % (city, country)
            else: text = city
            location.set_text(text)

        blacfg.set("general", "events.country", country)
        blacfg.set("general", "events.city", city)

    @blautils.thread
    def __update_models(self):
        # TODO

        if self.__lock.locked(): return True
        self.__lock.acquire()
        self.__refresh_button.set_sensitive(False)

        def worker():
            while True:
                event, model, iterator = queue.get()
                image_base = os.path.join(blaconst.EVENTS, ("%s" %
                        event.event_name).replace(" ", "_"))
                path = event.get_image(image_base, model, iterator)
                if path: images.add(path)
                queue.task_done()
        images = set()
        queue = Queue.Queue()

        blaplay.print_d("Starting worker threads to fetch images for events")
        threads = []
        for x in xrange(3):
            t = blautils.BlaThread(target=worker)
            t.daemon = True
            threads.append(t)
            t.start()

        # TODO: do this in one function call
        country = blacfg.getstring("general", "events.country")
        city = blacfg.getstring("general", "events.city")
        events = (blafm.get_events(recommended=True, country=country,
                city=city, festivalsonly=False), blafm.get_events(
                recommended=False, country=country, city=city,
                festivalsonly=False)
        )

#        active = blacfg.getint("general", "new.releases")
#        releases_library, releases_recommended = releases
#        self.__count_library = len(releases_library)
#        self.__count_recommended = len(releases_recommended)

#        if active == blaconst.NEW_RELEASES_FROM_LIBRARY:
#            count = self.__count_library
#        else: count = self.__count_recommended
#        self.emit("count_changed", blaconst.VIEW_RELEASES, count)

        items = [
            (blaconst.EVENTS_RECOMMENDED, events[0]),
            (blaconst.EVENTS_ALL, events[1])
        ]

        for type_, events in items:
            model = self.__models[type_]
            previous_date = None
            for event in events:
                event = BlaEventBrowser.Event(event)
                date = event.date
                if previous_date != date:
                    previous_date = date
                    model.append(["\n<span size=\"larger\"><b>%s</b></span>\n"
                            % date])
                iterator = model.append([event])
                queue.put((event, model, iterator))
        queue.join()
        map(blautils.BlaThread.kill, threads)

        # get rid of images for event that don't show up in the list anymore
        for f in set(blautils.discover(blaconst.EVENTS)).difference(images):
            try: os.unlink(f)
            except OSError: pass
        self.__lock.release()
        self.__refresh_button.set_sensitive(True)
        return True

    def __type_changed(self, radiobutton, type_):
        # the signal of the new active radiobutton arrives last so only change
        # the config then
        if radiobutton.get_active():
            blacfg.set("general", "events.filter", type_)
            self.__treeview.set_model(self.__models[type_])
            # TODO
#            if type_ == blaconst.NEW_RELEASES_FROM_LIBRARY:
#                count = self.__count_library
#            else: count = self.__count_recommended
#            self.emit("count_changed", blaconst.VIEW_EVENTS, count)

    def __row_activated(self, treeview, path, column):
        blautils.open_url(treeview.get_model()[path][0].event_url)

    def __button_press_event(self, treeview, event):
        try: path = treeview.get_path_at_pos(*map(int, [event.x, event.y]))[0]
        except TypeError: return False

        model = treeview.get_model()
        event_ = model[path][0]
        if not isinstance(event_, BlaEventBrowser.Event): return True
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

