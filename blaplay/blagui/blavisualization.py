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
from blaplay import blaconst, blacfg, blautils, blaplayer, visualizations
from blaplay.blagui import blaguiutils
player = blaplayer.player
visualizations.init()


class BlaVisualization(gtk.DrawingArea):
    __tid = -1
    __rate = 35

    def __init__(self, viewport):
        self.__viewport = viewport
        super(BlaVisualization, self).__init__()
        type(self).__instance = self

        player.connect("track_changed", self.flush_buffers)
        player.connect("seek", self.flush_buffers)
        self.connect("expose_event", self.__expose)
        def size_allocate(drawingarea, allocation):
            try: self.__module.set_width(allocation.width)
            except AttributeError: pass
        self.connect("size_allocate", size_allocate)

        self.__initialize_module(blacfg.getint("general", "visualization"))

        self.show_all()

    def __initialize_module(self, element):
        def disable():
            gobject.source_remove(self.__tid)
            try: del self.__module
            except AttributeError: pass
            self.__module = None
            self.__viewport.set_visible(False)

        try:
            if element == blaconst.VISUALIZATION_OFF: return disable()
            module = visualizations.modules[element]
        except KeyError:
            blaguiutils.error_dialog("Failed to initialize the requested "
                    "visualization.")
            disable()
            blacfg.set("general", "visualization", VISUALIZATION_OFF)
        else:
            self.__module = module()
            self.__module.set_width(self.get_allocation().width)
            self.set_size_request(-1, self.__module.height)
            try: player.disconnect(self.__cid)
            except AttributeError: pass
            self.__viewport.set_visible(True)
            self.__cid = player.connect_object(
                    "new_buffer", module.new_buffer, self.__module)
            self.__set_timer()

    def __set_timer(self):
        def queue_draw():
            self.queue_draw()
            return True
        gobject.source_remove(self.__tid)
        self.__tid = gobject.timeout_add(int(1000/self.__rate), queue_draw)

    def __expose(self, drawingarea, event):
        # this callback does not fire if the main window is hidden which means
        # that nothing is actually calculated in a visualization element which
        # saves some CPU time. this is not the case if the window is just
        # obscured by another one
        self.__module.draw(
                self.window.cairo_create(), self.get_pango_context(), self.get_style())

    @classmethod
    def flush_buffers(cls, *args):
        try: cls.__instance.__module.flush_buffers()
        except AttributeError: pass

    @classmethod
    def update_element(cls, radioaction, current):
        element = current.get_current_value()
        blacfg.set("general", "visualization", element)
        cls.__instance.__initialize_module(element)

