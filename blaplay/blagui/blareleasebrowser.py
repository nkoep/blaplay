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
import pango
import urllib
from email.utils import parsedate_tz as parse_rfc_time
import time

import blaplay
from blaplay import blautils, blaconst, blafm
from blaplay.blagui import blaguiutils


class BlaReleaseBrowser(blaguiutils.BlaScrolledWindow):
    # TODO: - design the page a little closer to the original:
    #         http://www.last.fm/home/newreleases
    #       - cache images
    #       - add timer to check for new releases every x hours

    __gsignals__ = {
        "count_changed": blaplay.signal(2)
    }

    class Release(object):
        __COVER_SIZE = 65

        def __init__(self, raw):
            self.release_name = raw["name"]
            self.release_url=  raw["url"]
            self.artist_name = raw["artist"]["name"]
            self.artist_url = raw["artist"]["url"]
            release_date = parse_rfc_time(raw["@attr"]["releasedate"])
            self.release_date = time.strftime("%A %d %B %Y", release_date[:-1])
            self.cover = self.__get_cover(raw["image"])

        def __get_cover(self, images):
            pixbuf = None
            url = blafm.get_image_url(images)
            try:
                image, message = urllib.urlretrieve(url)
                pixbuf = gtk.gdk.pixbuf_new_from_file(image).scale_simple(
                        self.__COVER_SIZE, self.__COVER_SIZE,
                        gtk.gdk.INTERP_HYPER
                )
            except (IOError, glib.GError): pass
            else:
                # FIXME: shouldn't this happen automatically considering
                #        urlretrieve works on tempfiles?
                os.unlink(image)
            return pixbuf

    def __init__(self):
        super(BlaReleaseBrowser, self).__init__()
        self.set_shadow_type(gtk.SHADOW_IN)

        def cell_data_func_pixbuf(column, renderer, model, iterator):
            pb = model[iterator][0].cover
            if pb: renderer.set_property("pixbuf", pb)

        def cell_data_func_text(column, renderer, model, iterator):
            release = model[iterator][0]
            markup = "<b>%s</b>\n%s\nReleased: %s" % (release.release_name,
                    release.artist_name, release.release_date)
            renderer.set_property("markup", markup)

        treeview = blaguiutils.BlaTreeViewBase()
        treeview.set_headers_visible(False)
        treeview.set_rules_hint(True)
        r = gtk.CellRendererPixbuf()
        column = gtk.TreeViewColumn("covers", r)
        column.set_cell_data_func(r, cell_data_func_pixbuf)
        treeview.append_column(column)
        r = gtk.CellRendererText()
        r.set_property("ellipsize", pango.ELLIPSIZE_END)
        column = gtk.TreeViewColumn("text", r)
        column.set_cell_data_func(r, cell_data_func_text)
        treeview.append_column(column)
        treeview.connect("row_activated", self.__row_activated)

        @blautils.thread
        def populate():
            model = gtk.ListStore(gobject.TYPE_PYOBJECT)
            releases = blafm.get_new_releases()
            for release in releases:
                model.append([BlaReleaseBrowser.Release(release)])
            self.emit("count_changed", blaconst.VIEW_RELEASES, len(releases))
            treeview.set_model(model)

        populate()
        self.add(treeview)
        self.show_all()

    def __row_activated(self, treeview, path, column):
        blautils.open_url(treeview.get_model()[path][0].release_url)

