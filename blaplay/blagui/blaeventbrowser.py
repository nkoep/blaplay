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

import gobject
import gtk

import blaplay
from blaplay import blautils, blaconst, blafm
from blaplay.blagui import blaguiutils


class BlaEventBrowser(blaguiutils.BlaScrolledWindow):
    # TODO: - design the page a little closer to the original:
    #         http://www.last.fm/events
    #       - cache images

    __gsignals__ = {
        "count_changed": blaplay.signal(2)
    }

    class Event(object):
        def __init__(self, raw):
            pass

        def __get_image(self, images):
            url = blafm.get_image_url(images)
            image, message = urllib.urlretrieve(url)
            return gtk.gdk.pixbuf_new_from_file(image).scale_simple(
                    self.__COVER_SIZE, self.__COVER_SIZE, gtk.gdk.INTERP_HYPER)

    def __init__(self):
        super(BlaEventBrowser, self).__init__()
        self.set_shadow_type(gtk.SHADOW_IN)

#        def cell_data_func_pixbuf(column, renderer, model, iterator):
#            renderer.set_property("pixbuf", model[iterator][0].cover)

#        def cell_data_func_text(column, renderer, model, iterator):
#            release = model[iterator][0]
#            markup = "<b>%s</b>\n%s\nReleased: %s" % (release.release_name,
#                    release.artist_name, release.release_date)
#            renderer.set_property("markup", markup)

#        treeview = blaguiutils.BlaTreeViewBase()
#        treeview.set_headers_visible(False)
#        treeview.set_rules_hint(True)
#        r = gtk.CellRendererPixbuf()
#        column = gtk.TreeViewColumn("covers", r)
#        column.set_cell_data_func(r, cell_data_func_pixbuf)
#        treeview.append_column(column)
#        r = gtk.CellRendererText()
#        r.set_property("ellipsize", pango.ELLIPSIZE_END)
#        column = gtk.TreeViewColumn("text", r)
#        column.set_cell_data_func(r, cell_data_func_text)
#        treeview.append_column(column)
#        treeview.connect("row_activated", self.__row_activated)

#        @blautils.thread
#        def populate():
#            model = gtk.ListStore(gobject.TYPE_PYOBJECT)
#            events = blafm.get_recommended_events(
#                    festivalsonly=False, country="Germany")
#            for event in events:
#                model.append([BlaEventBrowser.Event(event)])
#            treeview.set_model(model)

#        populate()
#        self.add(treeview)
        self.show_all()

    def __row_activated(self, treeview, path, column):
        blautils.open_url(treeview.get_model()[path][0].release_url)

