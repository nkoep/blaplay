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
player = blaplay.bla.player
from blaplay.blacore import blaconst, blacfg
from blaplay import blautil, blagui, visualizations
from blaplay.blagui import blaguiutils


class BlaVisualization(gtk.DrawingArea):
    __tid = __tid2 = -1
    __rate = 35 # frames per second

    def __init__(self, viewport):
        super(BlaVisualization, self).__init__()

        type(self).__instance = self
        self.__viewport = viewport
        self.__viewport.connect_object(
            "button_press_event", BlaVisualization.__button_press_event,
            self)

        player.connect("track_changed", self.flush_buffers)
        player.connect("seeked", self.flush_buffers)
        self.connect("expose_event", self.__expose)
        def size_allocate(drawingarea, allocation):
            try:
                self.__module.set_width(allocation.width)
            except AttributeError:
                pass
        self.connect("size_allocate", size_allocate)
        self.set_visible(blacfg.getboolean("general", "show.visualization"),
                         quiet=True)
        self.show_all()

    def __disable(self):
        try:
            player.disconnect(self.__cid)
        except AttributeError:
            pass
        map(gobject.source_remove, [self.__tid, self.__tid2])
        try:
            del self.__module
        except AttributeError:
            pass

        self.__module = None
        self.__viewport.set_visible(False)

        # Set the menu item to inactive. This will not create circular calls as
        # the callback for the CheckMenuItem's activate signal only fires if
        # the value actually changes.
        blagui.uimanager.get_widget(
            "/Menu/View/Visualization").set_active(False)

    def __initialize_module(self, identifier, quiet=False):
        try:
            module = visualizations.modules[identifier]
        except KeyError:
            if not visualizations.modules:
                msg = "No visualizations available."
                if not quiet:
                    blaguiutils.error_dialog(msg)
            self.__disable()
        else:
            self.__module = module()
            self.__module.set_width(self.get_allocation().width)
            self.set_size_request(-1, self.__module.height)
            try:
                if player.handler_is_connected(self.__cid):
                    player.disconnect(self.__cid)
            except AttributeError:
                pass
            self.__viewport.set_visible(True)
            self.__cid = player.connect_object(
                "new_buffer", module.new_buffer, self.__module)
            self.__set_timer()

    def __set_timer(self):
        def queue_draw():
            self.queue_draw()
            return True
        gobject.source_remove(self.__tid)
        self.__tid = gobject.timeout_add(int(1000 / self.__rate), queue_draw)
        self.__tid2 = gobject.timeout_add(int(1000 / self.__rate),
                                          self.__module.consume_buffer)

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
            if module == identifier:
                m.set_active(True)

        menu.show_all()
        menu.popup(None, None, None, event.button, event.time)

    def __expose(self, drawingarea, event):
        # This callback does not fire if the main window is hidden which means
        # that nothing is actually calculated in a visualization element which
        # saves some CPU time. This is not the case if the window is just
        # obscured by another one.
        self.__module.draw(self.window.cairo_create(),
                           self.get_pango_context(), self.get_style())

    @classmethod
    def flush_buffers(cls, *args):
        # FIXME: remove this method and every call to it once the buffering
        #        issue of the visualization base class has been worked out
        try:
            cls.__instance.__module.flush_buffers()
        except AttributeError:
            pass

    @classmethod
    def set_visible(cls, state, quiet=False):
        blacfg.setboolean("general", "show.visualization", state)
        if not state:
            return cls.__instance.__disable()

        identifier = blacfg.getstring("general", "visualization")
        if not identifier:
            try:
                identifier = sorted(
                    visualizations.modules.keys(), key=str.lower)[0]
            except IndexError:
                pass
            else:
                blacfg.set("general", "visualization", identifier)
        cls.__instance.__initialize_module(identifier, quiet=quiet)

