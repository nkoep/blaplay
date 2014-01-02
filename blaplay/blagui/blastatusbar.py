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

import blaplay
player = blaplay.bla.player
library = blaplay.bla.library
from blaplay.blacore import blaconst, blacfg
from blaplay import blautil, blagui

from blaplay.formats._identifiers import *


class BlaStatusbar(gtk.Table):
    __instance = None

    __state = blaconst.STATE_STOPPED
    __state_string = "Stopped"
    __format = ""
    __bitrate = ""
    __sampling_rate = ""
    __channel_mode = ""
    __position = "0:00"
    __duration_nanoseconds = 0
    __duration = "0:00"

    __padding = 5
    __lock = blautil.BlaLock()
    __tid = None

    def __init__(self):
        super(BlaStatusbar, self).__init__(rows=1, columns=3, homogeneous=True)
        type(self).__instance = self

        self.__pb = gtk.ProgressBar()
        self.__pb_label = gtk.Label("Scanning library:")

        self.__track_info = gtk.Label(self.__state_string)

        hbox = gtk.HBox(spacing=10)
        hbox.pack_start(self.__pb_label, expand=False)
        hbox.pack_start(self.__pb, expand=False, fill=True)
        hbox.pack_start(self.__track_info, expand=True)

        self.__view_info = gtk.Label("")

        # Playback order
        self.__order = gtk.combo_box_new_text()
        map(self.__order.append_text, blaconst.ORDER_LITERALS)
        self.__order.set_active(blacfg.getint("general", "play.order"))
        def order_changed(cb):
            order = cb.get_active()
            states = [False] * len(blaconst.ORDER_LITERALS)
            states[order] = True
            ui_manager = blaplay.bla.ui_manager
            for idx, order in enumerate(blaconst.MENU_ORDER):
                action = ui_manager.get_widget(order)
                action.set_active(states[idx])
        self.__order.connect("changed", order_changed)

        table = gtk.Table(rows=1, columns=2)
        table.attach(gtk.Label("Order:"), 0, 1, 0, 1, xpadding=10)
        table.attach(self.__order, 1, 2, 0, 1)

        count = 0
        for widget, xalign in [(hbox, 0.0), (self.__view_info, 0.5),
                               (table, 1.0)]:
            alignment = gtk.Alignment(xalign, 0.5, 0.0, 0.5)
            alignment.add(widget)
            self.attach(alignment, count, count+1, 0, 1)
            count += 1

        player.connect("state_changed", self.__changed)
        library.connect("progress", self.update_progress)

        self.show_all()
        # TODO: group these two
        self.__pb.set_visible(False)
        self.__pb_label.set_visible(False)
        self.set_visible(blacfg.getboolean("general", "statusbar"))

    def __changed(self, player):
        self.__state = player.get_state()
        self.__state_string = player.get_state_string()
        if self.__state != blaconst.STATE_STOPPED:
            track = player.get_track()
            self.__format = track[FORMAT]
            self.__bitrate = track.bitrate
            self.__bitrate = ("%s avg." % self.__bitrate if self.__bitrate
                              else "")
            self.__sampling_rate = track.sampling_rate
            self.__channel_mode = track[CHANNEL_MODE]
            self.__duration_nanoseconds = track[LENGTH] * 1e9
            self.__duration = self.__convert_time(self.__duration_nanoseconds)
        self.__update_track_status()

    def __update_track_status(self):
        with self.__lock:
            self.__track_info.set_text(self.__state_string)
            if self.__state != blaconst.STATE_STOPPED:
                status = [self.__state_string]
                items = [self.__format, self.__bitrate, self.__sampling_rate,
                         self.__channel_mode]
                for value in filter(None, items):
                    status.append(value)
                if self.__duration_nanoseconds:
                    status.append("%s/%s" % (self.__position, self.__duration))
                status = " | ".join(status)
                self.__track_info.set_text(status)

    def __convert_time(self, value):
        s, ns = divmod(value, 1e9)
        m, s = divmod(s, 60)

        if m < 60:
            return "%d:%02d" % (m, s)
        h, m = divmod(m, 60)
        return "%d:%02d:%02d" % (h, m, s)

    @classmethod
    def set_view_info(cls, view, string):
        # TODO: get rid of the view argument
        if view == blacfg.getint("general", "view"):
            try:
                cls.__instance.__view_info.set_text(string)
            except AttributeError:
                pass
        return False

    @classmethod
    def set_order(cls, radioaction, current):
        order = current.get_current_value()
        cls.__instance.__order.set_active(order)
        blacfg.set("general", "play.order", order)

    @classmethod
    def update_position(cls, position):
        if position > cls.__instance.__duration_nanoseconds:
            cls.__instance.__position = cls.__instance.__duration
        else:
            cls.__instance.__position = cls.__instance.__convert_time(position)
        cls.__instance.__update_track_status()

    def set_visible(self, yes):
        super(BlaStatusbar, self).set_visible(yes)
        blacfg.setboolean("general", "statusbar", yes)

    def update_progress(self, library, arg):
        def pulse(pb):
            pb.pulse()
            return True

        if arg == "pulse":
            self.__tid = gobject.timeout_add(40, pulse, self.__pb)
            self.__track_info.set_visible(False)
            self.__pb.set_visible(True)
            self.__pb_label.set_visible(True)

        elif arg == "abort":
            gobject.source_remove(self.__tid)
            self.__track_info.set_visible(True)
            self.__pb.set_visible(False)
            self.__pb_label.set_visible(False)
            self.__pb.set_text("")

        elif self.__tid:
            gobject.source_remove(self.__tid)
            self.__tid = None

        try:
            self.__pb.set_fraction(arg)
            self.__pb.set_text("%d %%" % (arg * 100))
        except TypeError:
            pass

        if arg == 1.0:
            self.__track_info.set_visible(True)
            self.__pb.set_visible(False)
            self.__pb_label.set_visible(False)
            self.__pb.set_text("")

