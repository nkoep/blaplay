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
import pango

import blaplay
player = blaplay.bla.player
from blaplay.blacore import blaconst, blacfg
from blaplay import blautil, blagui, visualizations


class BlaVisualization(gtk.Viewport):
    __metaclass__ = blautil.BlaSingletonMeta

    __tid_draw = __tid_consume = -1
    __rate = 35 # frames per second

    def __init__(self):
        super(BlaVisualization, self).__init__()

        self.__drawing_area = gtk.DrawingArea()
        self.add(self.__drawing_area)

        self.connect_object("button_press_event",
                            BlaVisualization.__button_press_event, self)

        player.connect("track_changed", self.flush_buffers)
        player.connect("seeked", self.flush_buffers)
        self.__drawing_area.connect_object(
            "expose_event", BlaVisualization.__expose, self)
        def size_allocate(drawingarea, allocation):
            try:
                self.__module.set_width(allocation.width)
            except AttributeError:
                pass
        self.connect("size_allocate", size_allocate)
        self.set_visible(blacfg.getboolean("general", "show.visualization"))
        self.show_all()

    def __disable(self):
        try:
            player.disconnect(self.__cid)
        except AttributeError:
            pass
        map(gobject.source_remove, [self.__tid_draw, self.__tid_consume])
        try:
            del self.__module
        except AttributeError:
            pass

        self.__module = None
        gtk.Widget.set_visible(self, False)

        # Set the menu item to inactive. This will not create circular calls as
        # the callback for the CheckMenuItem's activate signal only fires if
        # the value actually changes.
        blaplay.bla.ui_manager.get_widget(
            "/Menu/View/Visualization").set_active(False)

    def __initialize_module(self, identifier):
        try:
            module = visualizations.modules[identifier]
        except KeyError:
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
            gtk.Widget.set_visible(self, True)
            self.__cid = player.connect_object(
                "new_buffer", module.new_buffer, self.__module)
            self.__set_timer()

    def __set_timer(self):
        # TODO: Suspend during paused and stopped states.
        def queue_draw():
            self.__drawing_area.queue_draw()
            return True
        gobject.source_remove(self.__tid_draw)
        self.__tid_draw = gobject.timeout_add(int(1000 / self.__rate),
                                              queue_draw)
        self.__tid_consume = gobject.timeout_add(int(1000 / self.__rate),
                                                 self.__module.consume_buffer)

    def __button_press_event(self, event):
        if event.button != 3 or event.type in (gtk.gdk._2BUTTON_PRESS,
                                               gtk.gdk._3BUTTON_PRESS):
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

    def __expose(self, event):
        # This callback does not fire if the main window is hidden which means
        # that nothing is actually calculated in a visualization element, in
        # turn saving some CPU time. This is not the case if the window is just
        # obscured by another one.
        cr = self.__drawing_area.window.cairo_create()
        pc = self.__drawing_area.get_pango_context()
        try:
            self.__module.draw(cr, pc, self.__drawing_area.get_style())
        except AttributeError:
            fdesc = gtk.widget_get_default_style().font_desc
            try:
                layout = self.__layout
            except AttributeError:
                layout = self.__layout = pango.Layout(pc)
            layout.set_font_description(fdesc)
            cr.move_to(100, 100)
            layout.set_markup("No visualization available")
            cr.show_layout(layout)

    def flush_buffers(self, *args):
        # FIXME: remove this method and every call to it once the buffering
        #        issue of the visualization base class has been worked out
        try:
            self.__module.flush_buffers()
        except AttributeError:
            pass

    def set_visible(self, state):
        blacfg.setboolean("general", "show.visualization", state)
        if not state:
            return self.__disable()

        identifier = blacfg.getstring("general", "visualization")
        if not identifier:
            try:
                identifier = sorted(
                    visualizations.modules.keys(), key=str.lower)[0]
            except IndexError:
                # TODO: Paint "No visualizations available." on the da.
                pass
            else:
                blacfg.set("general", "visualization", identifier)
        self.__initialize_module(identifier)

