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
import math
import Queue
import urllib
from email.utils import parsedate as parse_rfc_time
import datetime

import gobject
import gtk
import pango
import pangocairo

import blaplay
from blaplay.blacore import blacfg, blaconst
from blaplay import blautil
from blaplay.blautil import blafm
from blaview import BlaViewMeta
from blawindows import BlaScrolledWindow
import blaguiutils

IMAGE_SIZE = 65


class BlaCellRendererPixbuf(blaguiutils.BlaCellRendererBase):
    __gproperties__ = {
        "content": (gobject.TYPE_PYOBJECT, "", "", gobject.PARAM_READWRITE)
    }

    def __init__(self):
        super(BlaCellRendererPixbuf, self).__init__()

    def __get_layout(self, widget):
        context = widget.get_pango_context()
        layout = pango.Layout(context)
        fdesc = gtk.widget_get_default_style().font_desc
        layout.set_font_description(fdesc)
        layout.set_markup(self.get_property("content"))
        return layout

    def on_get_size(self, widget, cell_area):
        content = self.get_property("content")
        if isinstance(content, str):
            layout = self.__get_layout(widget)
            height = layout.get_pixel_size()[-1]
        else:
            height = IMAGE_SIZE
        return (0, 0, IMAGE_SIZE, height)

    def on_render(self, window, widget, background_area, cell_area,
            expose_area, flags):
        cr = window.cairo_create()
        content = self.get_property("content")
        if isinstance(content, str):
            # Render active resp. inactive rows.
            layout = self.__get_layout(widget)
            layout.set_width((expose_area.width + expose_area.x) * pango.SCALE)
            layout.set_ellipsize(pango.ELLIPSIZE_END)

            style = widget.get_style()
            if (flags == (gtk.CELL_RENDERER_SELECTED |
                          gtk.CELL_RENDERER_PRELIT) or
                flags == gtk.CELL_RENDERER_SELECTED):
                color = style.text[gtk.STATE_SELECTED]
            else:
                color = style.text[gtk.STATE_NORMAL]
            cr.set_source_color(color)

            pc_context = pangocairo.CairoContext(cr)
            pc_context.move_to(expose_area.x + 10, expose_area.y)
            pc_context.show_layout(layout)

            cr.set_line_width(1.0)
            size = layout.get_pixel_size()
            cr.move_to(size[0] + 20,
                    math.ceil(expose_area.y + size[1] / 2) + 0.5)
            cr.line_to(expose_area.x+expose_area.width - 10,
                    math.ceil(expose_area.y + size[1] / 2) + 0.5)
            cr.stroke()
        else:
            if not content:
                return
            cr.set_source_pixbuf(content, expose_area.x, expose_area.y)
            cr.rectangle(*expose_area)
            cr.fill()

class BlaRelease(object):
    __EMPTY_PIXBUF = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, True, 8,
                                    IMAGE_SIZE, IMAGE_SIZE)
    __EMPTY_PIXBUF.fill(0)

    def __init__(self, raw):
        self.__raw = raw
        self.release_name = raw["name"]
        self.release_url = raw["url"]
        self.artist_name = raw["artist"]["name"]
        self.artist_url = raw["artist"]["url"]
        self.date = parse_rfc_time(raw["@attr"]["releasedate"])
        self.cover = BlaRelease.__EMPTY_PIXBUF

    @property
    def release_date(self):
        return blautil.format_date(self.date)

    @property
    def calender_week(self):
        return datetime.date(*self.date[:3]).isocalendar()[:2]

    def get_cover(self, restore=False):
        pixbuf = path = None
        path = ("%s-%s" % (self.artist_name, self.release_name)).replace(
            " ", "_")
        image_base = os.path.join(blaconst.RELEASES, path)
        for ext in ["jpg", "png"]:
            try:
                path = "%s.%s" % (image_base, ext)
                pixbuf = gtk.gdk.pixbuf_new_from_file(path)
            except gobject.GError:
                pass
            else:
                pixbuf = pixbuf.scale_simple(IMAGE_SIZE, IMAGE_SIZE,
                                             gtk.gdk.INTERP_HYPER)
                break
        else:
            if not restore:
                url = blafm.get_image_url(self.__raw["image"])
                try:
                    image, message = urllib.urlretrieve(url)
                    path = "%s.%s" % (image_base, blautil.get_extension(image))
                    shutil.move(image, path)
                    pixbuf = gtk.gdk.pixbuf_new_from_file(path).scale_simple(
                        IMAGE_SIZE, IMAGE_SIZE, gtk.gdk.INTERP_HYPER)
                except (IOError, gobject.GError):
                    pass

        self.cover = pixbuf or BlaRelease.__EMPTY_PIXBUF
        return path

class BlaReleaseBrowser(BlaScrolledWindow):
    __metaclass__ = BlaViewMeta("New Releases")

    __count_library = 0
    __count_recommended = 0
    __lock = blautil.BlaLock(strict=True)

    def __init__(self):
        super(BlaReleaseBrowser, self).__init__()
        self.set_shadow_type(gtk.SHADOW_NONE)

        vbox = gtk.VBox()
        vbox.set_border_width(10)

        # Heading
        hbox = gtk.HBox()
        items = [
            ("<b><span size=\"xx-large\">New releases</span></b>",
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

        # Type selector
        self.__hbox = gtk.HBox(spacing=5)
        self.__hbox.set_border_width(10)
        items = [
            ("From artists in your library",
             blaconst.NEW_RELEASES_FROM_LIBRARY),
            ("Recommended by Last.fm", blaconst.NEW_RELEASES_RECOMMENDED)
        ]
        active = blacfg.getint("general", "releases.filter")
        radiobutton = None
        for label, filt in items:
            radiobutton = gtk.RadioButton(radiobutton, label)
            if filt == active:
                radiobutton.set_active(True)
            radiobutton.connect("toggled", self.__filter_changed, filt)
            self.__hbox.pack_start(radiobutton, expand=False)
        button = gtk.Button("Refresh")
        button.set_focus_on_click(False)
        button.connect_object(
            "clicked", BlaReleaseBrowser.__update_models, self)
        self.__hbox.pack_start(button, expand=False, padding=5)
        vbox.pack_start(self.__hbox, expand=False)

        # Releases list
        def cell_data_func_pixbuf(column, renderer, model, iterator):
            release = model[iterator][0]
            try:
                renderer.set_property("content", release.cover)
            except AttributeError:
                renderer.set_property("content", release)

        def cell_data_func_text(column, renderer, model, iterator):
            release = model[iterator][0]
            try:
                markup = "<b>%s</b>\n%s\nReleased: %s" % (
                    release.release_name, release.artist_name,
                    release.release_date)
            except AttributeError:
                markup = ""
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
        r.set_property("ellipsize", pango.ELLIPSIZE_END)
        column.pack_start(r)
        column.set_cell_data_func(r, cell_data_func_text)
        self.__treeview.append_column(column)
        self.__treeview.connect("row_activated", self.__row_activated)
        self.__treeview.connect(
            "button_press_event", self.__button_press_event)
        self.__models = map(gtk.ListStore, [gobject.TYPE_PYOBJECT] * 2)
        self.__treeview.set_model(self.__models[active])
        vbox.pack_start(self.__treeview, expand=True, padding=10)

        self.add_with_viewport(vbox)
        self.show_all()

        blaplay.bla.register_for_cleanup(self)

    def __call__(self):
        self.__save()

    def __save(self):
        releases = [row[0] for row in self.__treeview.get_model()]
        blautil.serialize_to_file(releases, blaconst.RELEASES_PATH)

    @blautil.thread
    def __update_models(self):
        def set_sensitive(state):
            self.__hbox.set_sensitive(state)
            self.__treeview.set_sensitive(state)
            return False
        gobject.idle_add(set_sensitive, False)

        with self.__lock:
            images = set()
            # FIXME: These don't always seem to timeout properly.
            releases = (blafm.get_new_releases(),
                        blafm.get_new_releases(recommended=True))
            active = blacfg.getint("general", "releases.filter")
            if releases[0]:
                self.__count_library = len(releases[0])
            if releases[1]:
                self.__count_recommended = len(releases[1])
            items = [
                (blaconst.NEW_RELEASES_FROM_LIBRARY, releases[0] or []),
                (blaconst.NEW_RELEASES_RECOMMENDED, releases[1] or [])
            ]
            current_week = datetime.date.today().isocalendar()[:2]
            for filt, releases in items:
                model = gtk.ListStore(gobject.TYPE_PYOBJECT)
                previous_week = None
                for release in releases:
                    release = BlaRelease(release)
                    week = release.calender_week
                    if previous_week != week:
                        previous_week = week
                        date = self.__cw_to_start_end_day(*week)
                        date = "%s - %s" % (date[0].strftime("%a %d %b"),
                                            date[1].strftime("%a %d %b"))
                        datestring = "\n<span size=\"larger\"><b>%s\n"
                        if week == current_week:
                            datestring %= "This week</b></span> (%s)" % date
                        else:
                            datestring %= "Week of %s</b></span>" % date
                        model.append([datestring])
                    model.append([release])
                    path = release.get_cover()
                    if path:
                        images.add(path)
                self.__models[filt] = model

            # Get rid of covers for releases that don't show up anymore.
            for image in set(blautil.discover(blaconst.RELEASES)).difference(
                images):
                try:
                    os.unlink(image)
                except OSError:
                    pass

            gobject.idle_add(set_sensitive, True)
            gobject.idle_add(self.__treeview.set_model, self.__models[active])

            if active == blaconst.NEW_RELEASES_FROM_LIBRARY:
                count = self.__count_library
            else:
                count = self.__count_recommended
            gobject.idle_add(
                self.emit, "count_changed", blaconst.VIEW_RELEASES, count)
            return True

    def __filter_changed(self, radiobutton, filt):
        # The signal of the new active radiobutton arrives last so only change
        # the config then.
        if radiobutton.get_active():
            blacfg.set("general", "releases.filter", filt)
            self.__treeview.set_model(self.__models[filt])
            if filt == blaconst.NEW_RELEASES_FROM_LIBRARY:
                count = self.__count_library
            else:
                count = self.__count_recommended
            self.emit("count_changed", blaconst.VIEW_RELEASES, count)

    def __row_activated(self, treeview, path, column):
        blautil.open_url(treeview.get_model()[path][0].release_url)

    def __button_press_event(self, treeview, event):
        try:
            path = treeview.get_path_at_pos(*map(int, [event.x, event.y]))[0]
        except TypeError:
            return False

        model = treeview.get_model()
        release = model[path][0]
        if not isinstance(release, BlaRelease):
            return True
        if event.button in (1, 2):
            if event.type in (gtk.gdk._2BUTTON_PRESS, gtk.gdk._3BUTTON_PRESS):
                return True
            return False

        release_url = release.release_url
        artist_url = release.artist_url

        items = [
            ("View release page", lambda *x: blautil.open_url(release_url)),
            ("View artist profile", lambda *x: blautil.open_url(artist_url))
        ]

        user = blacfg.getstring("lastfm", "user")
        if user:
            artist_history_url = os.path.basename(release.artist_url)
            artist_history_url = (
                "http://www.last.fm/user/%s/library/music/%s" %
                (user, artist_history_url))
            items.append(("View artist history",
                          lambda *x: blautil.open_url(artist_history_url)))

        menu = gtk.Menu()
        for label, callback in items:
            m = gtk.MenuItem(label)
            m.connect("activate", callback)
            menu.append(m)

        menu.show_all()
        menu.popup(None, None, None, event.button, event.time)
        return False

    def __cw_to_start_end_day(self, year, week):
        # FIXME: This is not working as it's supposed to.
        date = datetime.date(year, 1, 1)
        timedelta = datetime.timedelta(days=(week-1)*7+1)
        return date + timedelta, date + timedelta + datetime.timedelta(days=6)

    def init(self):
        releases = blautil.deserialize_from_file(blaconst.RELEASES_PATH)
        if releases:
            model = gtk.ListStore(gobject.TYPE_PYOBJECT)
            # Pixbufs aren't initialized when they're unpickled so we need to
            # instantiate them while restoring. To speed up restoring we force
            # the use of possibly cached images by passing `restore=True'.
            for release in releases:
                try:
                    release.get_cover(restore=True)
                except AttributeError:
                    pass
            [model.append([release]) for release in releases]
            self.__treeview.set_model(model)

        # Check for new releases now and every two hours
        self.__update_models()
        gobject.timeout_add(2 * 3600 * 1000, self.__update_models)

