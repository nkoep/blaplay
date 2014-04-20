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
from blaplay.blacore import blacfg
import blaguiutils


class BlaVisualization(gtk.Viewport):
    def __init__(self):
        super(BlaVisualization, self).__init__()

        self._draw_timeout_id = -1
        self._consume_buffer_timeout_id = -1
        # TODO: Make this configurable in the preferences dialog.
        self._rate = 35 # frames per second

        self.__drawing_area = gtk.DrawingArea()
        self.add(self.__drawing_area)

        player.connect("track_changed", self.flush_buffers)
        player.connect("seeked", self.flush_buffers)
        self.__drawing_area.connect_object(
            "expose_event", BlaVisualization.__expose, self)
        def size_allocate(drawingarea, allocation):
            try:
                self.__spectrum.set_width(allocation.width)
            except AttributeError:
                pass
        self.connect("size_allocate", size_allocate)

        self.show_all()

        def on_config_changed(cfg, section, key):
            if section == "general" and key == "show.visualization":
                self.set_visible(blacfg.getboolean(section, key))
        blacfg.connect("changed", on_config_changed)

        def startup_complete(*args):
            self.set_visible(
                blacfg.getboolean("general", "show.visualization"))
        blaplay.bla.connect("startup_complete", startup_complete)

    def __set_visible(self, state):
        super(BlaVisualization, self).set_visible(state)

    def __enable(self):
        try:
            from blaspectrum import BlaSpectrum
        except ImportError as exc:
            blaguiutils.error_dialog(
                "Failed to enable spectrum visualization", exc.message)
            self.__disable()
            return

        self.__spectrum = BlaSpectrum()
        self.__spectrum.set_width(self.get_allocation().width)
        self.__spectrum.update_colors(self.__drawing_area.get_style())
        self.set_size_request(-1, self.__spectrum.height)
        self.__set_visible(True)
        self._callback_id = player.connect_object(
            "new_buffer", BlaSpectrum.new_buffer, self.__spectrum)

        # TODO: Suspend during paused and stopped states.
        def queue_draw():
            self.__drawing_area.queue_draw()
            return True
        gobject.source_remove(self._draw_timeout_id)
        self._draw_timeout_id = gobject.timeout_add(
            int(1000 / self._rate), queue_draw)
        self._consume_buffer_timeout_id = gobject.timeout_add(
            int(1000 / self._rate), self.__spectrum.consume_buffer)

        blacfg.setboolean("general", "show.visualization", True)

    def __disable(self):
        try:
            player.disconnect(self._callback_id)
        except AttributeError:
            pass
        map(gobject.source_remove,
            (self._draw_timeout_id, self._consume_buffer_timeout_id))
        self.__spectrum = None
        self.__set_visible(False)
        blacfg.setboolean("general", "show.visualization", False)

    def __expose(self, event):
        # This callback does not fire if the main window is hidden which means
        # that nothing is actually calculated in a visualization element, in
        # turn saving some CPU time. This is not the case if the window is just
        # obscured by another one.
        drawing_area = self.__drawing_area
        try:
            self.__spectrum.draw(drawing_area.window.cairo_create(),
                                 drawing_area.get_pango_context())

        except AttributeError:
            pass

    def flush_buffers(self, *args):
        # TODO: Remove this method and every call to it once the buffering
        #       issue of the visualization base class has been worked out.
        try:
            self.__spectrum.flush_buffers()
        except AttributeError:
            pass

    def set_visible(self, state):
        if state:
            self.__enable()
        else:
            self.__disable()

