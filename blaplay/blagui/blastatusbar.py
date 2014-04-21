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

import gtk
import gobject

from blaplay.blacore import blaconst, blacfg
from blaplay import blagui

from blaplay.formats._identifiers import *


def create_statusbar(library, player, view_managers):
    statusbar = BlaStatusbar()

    library.connect("progress", statusbar.update_progress)
    player.connect("state-changed", statusbar.update_track_info)

    # Register the statusbar as observer for changes to the view.
    view_managers[blaconst.VIEW_PLAYLIST].register_observer(statusbar)

    return statusbar


class _FileScannerBox(gtk.HBox):
    def __init__(self):
        super(_FileScannerBox, self).__init__(spacing=10)

        self._progress_bar = gtk.ProgressBar()
        label = gtk.Label("Scanning files:")
        self.pack_start(label)
        self.pack_start(self._progress_bar)

        # Make sure the box is initially hidden.
        def on_map(*args):
            self.hide_box()
            self.disconnect(callback_id)
        callback_id = self.connect("map", on_map)

    def show_box(self):
        self.set_visible(True)

    def hide_box(self):
        self.set_visible(False)
        self.set_text("")

    def pulse(self):
        self._progress_bar.pulse()

    def set_fraction(self, fraction):
        self._progress_bar.set_fraction(fraction)

    def set_text(self, text):
        self._progress_bar.set_text(text)

class BlaStatusbar(gtk.Table):
    _instance = None

    def __init__(self):
        super(BlaStatusbar, self).__init__(rows=1, columns=3, homogeneous=True)
        type(self)._instance = self

        self._state = blaconst.STATE_STOPPED
        self._state_string = "Stopped"
        self._format = ""
        self._bitrate = ""
        self._sampling_rate = ""
        self._channel_mode = ""
        self._position = "0:00"
        self._duration_nanoseconds = 0
        self._duration = "0:00"
        self._timeout_id = 0

        self._file_scanner_box = _FileScannerBox()
        self._track_info = gtk.Label(self._state_string)

        hbox = gtk.HBox(spacing=10)
        hbox.pack_start(self._file_scanner_box)
        hbox.pack_start(self._track_info)

        self._view_info = gtk.Label("")

        # Playback order
        self._order = gtk.combo_box_new_text()
        map(self._order.append_text, blaconst.ORDER_LITERALS.keys())
        self._order.set_active(blacfg.getint("general", "play.order"))
        def order_changed(cb):
            order = cb.get_active_text()
            blacfg.set_("general",
                        "play.order", blaconst.ORDER_LITERALS[order])
        self._order.connect("changed", order_changed)

        table = gtk.Table(rows=1, columns=2)

        table.attach(gtk.Label("Order:"), 0, 1, 0, 1, xpadding=10)
        table.attach(self._order, 1, 2, 0, 1)

        count = 0
        for widget, xalign in [(hbox, 0.0), (self._view_info, 0.5),
                               (table, 1.0)]:
            alignment = gtk.Alignment(xalign, 0.5, 0.0, 0.5)
            alignment.add(widget)
            self.attach(alignment, count, count+1, 0, 1)
            count += 1

        self.show_all()

    def _convert_time(self, value):
        s, ns = divmod(value, 1e9)
        m, s = divmod(s, 60)

        if m < 60:
            return "%d:%02d" % (m, s)
        h, m = divmod(m, 60)
        return "%d:%02d:%02d" % (h, m, s)

    def _update_track_info_string(self):
        self._track_info.set_text(self._state_string)
        if self._state != blaconst.STATE_STOPPED:
            status = [self._state_string]
            items = [self._format, self._bitrate, self._sampling_rate,
                     self._channel_mode]
            for value in filter(None, items):
                status.append(value)
            if self._duration_nanoseconds:
                status.append("%s/%s" % (self._position, self._duration))
            status = " | ".join(status)
            self._track_info.set_text(status)

    def update_progress(self, library, arg):
        def pulse():
            self._file_scanner_box.pulse()
            return True
        def source_remove():
            if self._timeout_id:
                gobject.source_remove(self._timeout_id)
                self._timeout_id = 0

        if arg == "pulse":
            self._timeout_id = gobject.timeout_add(40, pulse)
            self._file_scanner_box.show_box()
        elif arg == "abort":
            source_remove()
            self._file_scanner_box.hide_box()
        elif self._timeout_id:
            source_remove()

        try:
            self._file_scanner_box.set_fraction(arg)
            self._file_scanner_box.set_text("%d %%" % (arg * 100))
        except TypeError:
            pass

        if arg == 1.0:
            self._file_scanner_box.hide_box()

    def update_track_info(self, player):
        self._state = player.get_state()
        self._state_string = player.get_state_string()
        if self._state != blaconst.STATE_STOPPED:
            track = player.get_track()
            self._format = track[FORMAT]
            self._bitrate = track.bitrate
            self._bitrate = ("%s avg." % self._bitrate if self._bitrate
                             else "")
            self._sampling_rate = track.sampling_rate
            self._channel_mode = track[CHANNEL_MODE]
            self._duration_nanoseconds = track[LENGTH] * 1e9
            self._duration = self._convert_time(self._duration_nanoseconds)
        self._update_track_info_string()

    @classmethod
    def update_position(cls, position):
        if position > cls._instance._duration_nanoseconds:
            cls._instance._position = cls._instance._duration
        else:
            cls._instance._position = cls._instance._convert_time(position)
        cls._instance._update_track_info_string()

    def set_status_message(self, msg):
        self.set_view_info(0, msg)

    # XXX: Get rid of this.
    @classmethod
    def set_view_info(cls, view, string):
        if view == blacfg.getint("general", "view"):
            try:
                cls._instance._view_info.set_text(string)
            except AttributeError:
                pass
        return False

    def _set_status_message_from_view(self, view):
        self.set_status_message(view.get_status_message())

    def notify_status(self, view):
        self._set_status_message_from_view(view)

    def notify_focus(self, view):
        # FIXME: This doesn't always fire when a view receives focus.
        self._set_status_message_from_view(view)

