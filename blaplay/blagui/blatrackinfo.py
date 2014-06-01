# blaplay, Ccpyright (C) 2012-2014  Niklas Koep

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
from collections import OrderedDict
import cgi

import gobject
import gtk
import cairo
import pango

import blaplay
player = blaplay.bla.player
from blaplay import blautil
from blaplay.blacore import blaconst
from blaplay.formats._identifiers import *

COVER_SIZE = 75 # Width and height


class _CoverDisplay(gtk.DrawingArea):
    def __init__(self, metadata_fetcher):
        super(_CoverDisplay, self).__init__()
        self.add_events(gtk.gdk.BUTTON_PRESS_MASK)
        self.set_size_request(COVER_SIZE, COVER_SIZE)

        self._metadata_fetcher = metadata_fetcher
        self._cover = blaconst.COVER
        self._alpha = 1.0
        self._cover_pixbuf = None
        self._border_color = gtk.gdk.color_parse("#808080")
        self._timestamp = 0
        self._fetch_timeout_id = 0
        self._draw_timeout_id = 0

        metadata_fetcher.connect_object(
            "cover", _CoverDisplay._display_cover, self)
        self.connect_object(
            "expose-event", _CoverDisplay._on_expose_event, self)
        self.connect_object(
            "button-press-event",
            _CoverDisplay._on_button_press_event, self)

    def _update_timestamp(self):
        """Updates the timestamp and returns it."""

        self._timestamp = gobject.get_current_time()
        return self._timestamp

    def _on_button_press_event(self, event):
        def open_cover(*args):
            blautil.open_with_filehandler(
                self._cover, "Failed to open image '%s'" % self._cover)
        def open_directory(*args):
            blautil.open_directory(os.path.dirname(self._cover))

        if (event.button == 1 and event.type == gtk.gdk._2BUTTON_PRESS and
            self._cover != blaconst.COVER):
            open_cover()
        elif (event.button == 3 and event.type == gtk.gdk.BUTTON_PRESS):
            menu = gtk.Menu()
            sensitive = self._cover != blaconst.COVER
            options = [
                ("Open cover in image viewer", open_cover),
                ("Open directory", open_directory)
            ]
            for label, callback in options:
                m = gtk.MenuItem(label)
                m.connect("activate", callback)
                m.set_sensitive(sensitive)
                menu.append(m)

            menu.show_all()
            menu.popup(None, None, None, event.button, event.time)

        return True

    def _on_expose_event(self, event):
        cr = self.window.cairo_create()

        if self._cover_pixbuf:
            alpha = blautil.clamp(0.0, 1.0, self._alpha)

            # Draw the new cover on top of the previous one.
            cr.set_source_pixbuf(self._cover_pixbuf, 0, 0)
            cr.paint_with_alpha(alpha)

            # Decrease the alpha value to create a linear fade between covers.
            self._alpha += 0.05

        # Draw an outline. The default cover has a transparent background and
        # therefore looks better without border.
        if self._cover != blaconst.COVER:
            cr.set_source_color(self._border_color)
            cr.rectangle(*event.area)
            cr.stroke()

    def _display_cover(self, timestamp, cover):
        def crossfade():
            if self._alpha < 1.0:
                self.queue_draw()
                return True
            self._draw_timeout_id = 0
            return False

        if timestamp != self._timestamp or cover == self._cover:
            return

        self._cover = cover
        self._cover_pixbuf = self._prepare_cover(cover)
        self._alpha = 0.0
        if self._draw_timeout_id:
            gobject.source_remove(self._draw_timeout_id)
        # Use 25 ms intervals for an update rate of 40 fps.
        self._draw_timeout_id = gobject.timeout_add(25, crossfade)

    def _prepare_cover(self, cover):
        try:
            pb = gtk.gdk.pixbuf_new_from_file(cover)
        except gobject.GError:
            if cover != blaconst.COVER:
                try:
                    os.unlink(cover)
                except OSError:
                    pass
            pb = gtk.gdk.pixbuf_new_from_file(blaconst.COVER)
        height = self.get_allocation()[-1]
        return pb.scale_simple(height, height, gtk.gdk.INTERP_HYPER)

    def update_cover(self, track):
        def fetch_cover():
            self._metadata_fetcher.fetch_cover(track, self._update_timestamp())
            self._fetch_timeout_id = 0

        if track is None:
            self._display_cover(self._update_timestamp(), blaconst.COVER)
        else:
            if self._fetch_timeout_id:
                gobject.source_remove(self._fetch_timeout_id)
            self._fetch_timeout_id = gobject.timeout_add( 250, fetch_cover)

class BlaTrackInfo(gtk.Viewport, blautil.BlaInitiallyHidden):
    def __init__(self, metadata_fetcher):
        super(BlaTrackInfo, self).__init__()
        blautil.BlaInitiallyHidden.__init__(self)
        self.set_shadow_type(gtk.SHADOW_IN)

        self._track = None

        spacing = blaconst.WIDGET_SPACING
        hbox = gtk.HBox(spacing=spacing)
        hbox.set_border_width(spacing)

        # Add the cover display.
        self._cover_display = _CoverDisplay(metadata_fetcher)
        hbox.pack_start(self._cover_display, expand=False)

        # Add the info labels.
        self._label_stack = [gtk.Label() for _ in range(4)]
        table = gtk.Table(rows=len(self._label_stack), columns=1,
                          homogeneous=False)
        for idx, label in enumerate(self._label_stack):
            label.set_ellipsize(pango.ELLIPSIZE_END)
            alignment = gtk.Alignment()
            label.set_alignment(0.0, 0.0)
            table.attach(label, 0, 1, idx, idx+1, yoptions=gtk.FILL)
        hbox.pack_start(table)
        self.add(hbox)

        player.connect("state-changed", self._on_player_state_changed)

        self.show_all()

    def _update_track_info(self, track):
        markup = {
            TITLE: "<span size='larger'><b>%s</b></span>",
            ARTIST: "%s",
            ALBUM: "<i>%s</i>",
            DATE: "%s"
        }
        strings = []
        if track is not None:
            values = OrderedDict([
                (TITLE, track[TITLE] or track.basename),
                (ARTIST, track[ARTIST]),
                (ALBUM, track[ALBUM]),
                (DATE, track[DATE])
            ])
            for key, value in values.items():
                if value:
                    strings.append(markup[key] % cgi.escape(value))
        self._push_strings(strings)

    def _push_strings(self, strings):
        # We treat the labels table like a stack to avoid gaps when a certain
        # field is missing.
        for idx, label in enumerate(self._label_stack):
            try:
                markup = strings[idx]
            except IndexError:
                markup = ""
            label.set_markup(markup)

    def _on_player_state_changed(self, player):
        track = player.get_track()
        if track == self._track:
            return
        state = player.get_state()

        player_stopped = state == blaconst.STATE_STOPPED
        if player_stopped:
            self._track = None
        else:
            self._track = track
        self.set_visible(player_stopped)
        self._cover_display.update_cover(self._track)
        self._update_track_info(self._track)

