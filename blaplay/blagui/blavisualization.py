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
from blaplay import (blaconst, blacfg, blautils, blaplayer, blagui,
        visualizations)
from blaplay.blagui import blaguiutils
player = blaplayer.player
visualizations.init()


class BlaVisualization(gtk.DrawingArea):
    __tid = -1
    __rate = 35

    def __init__(self, viewport):
        self.__viewport = viewport
        self.__viewport.connect_object("button_press_event",
                BlaVisualization.__button_press_event, self)
        super(BlaVisualization, self).__init__()
        type(self).__instance = self

        player.connect("track_changed", self.flush_buffers)
        player.connect("seek", self.flush_buffers)
        self.connect("expose_event", self.__expose)
        def size_allocate(drawingarea, allocation):
            try: self.__module.set_width(allocation.width)
            except AttributeError: pass
        self.connect("size_allocate", size_allocate)
        self.set_visibility(blacfg.getboolean("general", "show.visualization"),
                quiet=True)
        self.show_all()

    def __disable(self):
        gobject.source_remove(self.__tid)
        try: del self.__module
        except AttributeError: pass
        self.__module = None
        self.__viewport.set_visible(False)
        # set the menu item to inactive. this will not create circular calls as
        # the callback for the CheckMenuItem's activate signal only fires if
        # the value actually changes
        blagui.uimanager.get_widget(
                "/Menu/View/Visualization").set_active(False)

    def __initialize_module(self, identifier, quiet=False):
        try:
            # get module class and check if necessary attributes are present
            module = visualizations.modules[identifier]
            for method in ["set_width", "new_buffer", "flush_buffers", "draw"]:
                method = getattr(module, method)
                if not callable(method): raise AttributeError
            if not hasattr(module, "height"): raise AttributeError
        except (KeyError, AttributeError):
            if not visualizations.modules: msg = "No visualizations available."
            else:
                msg = "Failed to initialize \"%s\" visualization." % identifier
            if not quiet: blaguiutils.error_dialog(msg)
            self.__disable()
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

    def __button_press_event(self, event):
        if (event.button != 3 or event.type in [gtk.gdk._2BUTTON_PRESS,
                gtk.gdk._3BUTTON_PRESS]):
            return False

        def activate(item, identifier):
            blacfg.set("general", "visualization", identifier)
            self.__initialize_module(identifier)

        identifier = blacfg.getstring("general", "visualization")

        menu = gtk.Menu()
        for module in sorted(visualizations.modules.keys(), key=str.lower):
            m = gtk.CheckMenuItem(module)
            m.set_draw_as_radio(True)
            m.connect("activate", activate, module)
            menu.append(m)
            if module == identifier: m.set_active(True)

        menu.show_all()
        menu.popup(None, None, None, event.button, event.time)

    def __expose(self, drawingarea, event):
        # this callback does not fire if the main window is hidden which means
        # that nothing is actually calculated in a visualization element which
        # saves some CPU time. this is not the case if the window is just
        # obscured by another one
        self.__module.draw(self.window.cairo_create(),
                self.get_pango_context(), self.get_style())

    @classmethod
    def flush_buffers(cls, *args):
        try: cls.__instance.__module.flush_buffers()
        except AttributeError: pass

    @classmethod
    def set_visibility(cls, state, quiet=False):
        blacfg.setboolean("general", "show.visualization", state)
        if not state: return cls.__instance.__disable()

        identifier = blacfg.getstring("general", "visualization")
        if not identifier:
            try:
                identifier = sorted(
                        visualizations.modules.keys(), key=str.lower)[0]
                blacfg.set("general", "visualization", identifier)
            except IndexError: pass
        cls.__instance.__initialize_module(identifier, quiet=quiet)

