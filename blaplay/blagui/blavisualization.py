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

from blaplay.blacore import blaconst
from blaplay import blautil
import blaguiutil


class BlaVisualization(gtk.Viewport, blautil.BlaInitiallyHidden):
    def __init__(self, config, player):
        super(BlaVisualization, self).__init__()
        blautil.BlaInitiallyHidden.__init__(self)

        self._config = config
        self._player = player

        self._draw_timeout_id = 0
        self._consume_buffer_timeout_id = 0
        self._rate = 35 # frames per second

        self._drawing_area = gtk.DrawingArea()
        self.add(self._drawing_area)

        def on_player_state_changed(player):
            self.set_visible(
                player.get_state() != blaconst.STATE_STOPPED and
                config.getboolean("general", "show.visualization"))
        player.connect("state-changed", on_player_state_changed)
        player.connect("track-changed", self.flush_buffers)
        player.connect("seeked", self.flush_buffers)
        self._drawing_area.connect_object(
            "expose-event", BlaVisualization._expose, self)
        def size_allocate(drawingarea, allocation):
            try:
                self._spectrum.set_width(allocation.width)
            except AttributeError:
                pass
        self.connect("size-allocate", size_allocate)

        def on_config_changed(config, section, key):
            if section == "general" and key == "show.visualization":
                self.set_enabled(config.getboolean(section, key))
        config.connect("changed", on_config_changed)

        self.set_enabled(
            config.getboolean("general", "show.visualization"))

    def _enable(self):
        try:
            from blaspectrum import BlaSpectrum
        except ImportError as exc:
            blaguiutil.error_dialog(
                "Failed to enable spectrum visualization", exc.message)
            self._disable()
            return

        self._spectrum = BlaSpectrum()
        self._spectrum.set_width(self.get_allocation().width)
        self._spectrum.update_colors(self._drawing_area.get_style())
        self.set_size_request(-1, self._spectrum.height)
        if self._player.get_state() != blaconst.STATE_STOPPED:
            self.set_visible(True)
        self._callback_id = self._player.connect_object(
            "new-buffer", BlaSpectrum.new_buffer, self._spectrum)

        def queue_draw():
            self._drawing_area.queue_draw()
            return True
        self._draw_timeout_id = gobject.timeout_add(
            int(1000 / self._rate), queue_draw)
        self._consume_buffer_timeout_id = gobject.timeout_add(
            int(1000 / self._rate), self._spectrum.consume_buffer)

        self._config.setboolean("general", "show.visualization", True)

    def _disable(self):
        try:
            self._player.disconnect(self._callback_id)
        except AttributeError:
            pass

        if self._draw_timeout_id:
            gobject.source_remove(self._draw_timeout_id)
            self._draw_timeout_id = 0
        if self._consume_buffer_timeout_id:
            gobject.source_remove(self._consume_buffer_timeout_id)
            self._consume_buffer_timeout_id = 0

        self._spectrum = None
        self.set_visible(False)
        self._config.setboolean("general", "show.visualization", False)

    def _expose(self, event):
        # This callback does not fire if the main window is hidden which means
        # that nothing is actually calculated in a visualization element, in
        # turn saving some CPU time. This is not the case if the window is just
        # obscured by another one.
        drawing_area = self._drawing_area
        try:
            self._spectrum.draw(drawing_area.window.cairo_create(),
                                drawing_area.get_pango_context())

        except AttributeError:
            pass

    def flush_buffers(self, *args):
        # TODO: Remove this method and every call to it once the buffering
        #       issue of the visualization base class has been worked out.
        try:
            self._spectrum.flush_buffers()
        except AttributeError:
            pass

    def set_enabled(self, state):
        if state:
            self._enable()
        else:
            self._disable()

