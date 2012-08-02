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

import gtk
import gobject

from blaplay import blaconst, blacfg, blautils, bladb, blaplayer, blagui
player = blaplayer.player
library = bladb.library
from blaplay.formats._identifiers import *


class BlaStatusbar(gtk.Table):
    __instance = None

    __position = "0:00"
    __duration = "0:00"

    __padding = 5
    __lock = blautils.BlaLock()
    __tid = None

    def __init__(self):
        super(BlaStatusbar, self).__init__(rows=1, columns=3, homogeneous=True)
        type(self).__instance = self

        self.__pb = gtk.ProgressBar()
        self.__pb_label = gtk.Label("Scanning library:")

        self.__track_info = gtk.Label("Stopped")

        hbox = gtk.HBox(spacing=10)
        hbox.pack_start(self.__pb_label, expand=False)
        hbox.pack_start(self.__pb, expand=False, fill=True)
        hbox.pack_start(self.__track_info, expand=True)

        self.__playlist_info = gtk.Label("")

        # playback order
        self.__order = gtk.combo_box_new_text()
        map(self.__order.append_text, blaconst.ORDER_LITERALS)
        self.__order.set_active(blacfg.getint("general", "play.order"))
        def order_changed(cb):
            order = cb.get_active()
            states = [False] * len(blaconst.ORDER_LITERALS)
            states[order] = True
            for idx, order in enumerate(blaconst.MENU_ORDER):
                action = blagui.uimanager.get_widget(order)
                action.set_active(states[idx])
        self.__order.connect("changed", order_changed)

        table = gtk.Table(rows=1, columns=2)
        table.attach(gtk.Label("Order:"), 0, 1, 0, 1, xpadding=10)
        table.attach(self.__order, 1, 2, 0, 1)

        count, xalign = 0, 0.0
        for widget in [hbox, self.__playlist_info, table]:
            alignment = gtk.Alignment(xalign, 0.5, 0.0, 0.5)
            alignment.add(widget)
            self.attach(alignment, count, count+1, 0, 1)
            count += 1
            xalign += 0.5

        player.connect("track_changed", self.__track_changed)
        player.connect("state_changed", self.__state_changed)
        library.connect("progress", self.update_progress)

        self.show_all()
        self.set_visibility(blacfg.getboolean("general", "statusbar"))

    def __state_changed(self, player):
        self.__state = player.get_state()
        self.__update_track_status()

    def __track_changed(self, player):
        track = player.get_track()
        self.__format = track[FORMAT]
        self.__bitrate = track.bitrate
        self.__sampling_rate = track.sampling_rate
        self.__channel_mode = track[CHANNEL_MODE]
        self.__duration_nanoseconds = track[LENGTH] * 1e9
        self.__duration = self.__convert_time(self.__duration_nanoseconds)
        self.__update_track_status()

    def __update_track_status(self):
        with self.__lock:
            if self.__state == blaconst.STATE_STOPPED:
                self.__track_info.set_text("Stopped")
            else:
                if self.__state == blaconst.STATE_PAUSED: state = "Paused"
                else: state = "Playing"

                status = "%s | %s |%s %s/%s" % (state, self.__format, "%s",
                        self.__position, self.__duration)
                x = ""
                if self.__bitrate: x += " %s avg. |" % self.__bitrate
                if self.__sampling_rate: x += " %s |" % self.__sampling_rate
                if self.__channel_mode: x += " %s |" % self.__channel_mode
                status %= x

                self.__track_info.set_text(status)

    def __convert_time(self, value):
        s, ns = divmod(value, 1e9)
        m, s = divmod(s, 60)

        if m < 60: return "%d:%02d" % (m, s)
        h, m = divmod(m, 60)
        return "%d:%02d:%02d" % (h, m, s)

    @classmethod
    def set_order(cls, radioaction, current):
        order = current.get_current_value()
        cls.__instance.__order.set_active(order)
        blacfg.set("general", "play.order", order)

    @classmethod
    def update_playlist_info(cls, playlist, length_seconds, track_count):
        if track_count == 0:
            cls.__instance.__playlist_info.set_text("")
            return True

        # calculate the total length of the playlist
        values = [("seconds", 60), ("minutes", 60), ("hours", 24), ("days",)]
        length = {}.fromkeys([v[0] for v in values], 0)
        length["seconds"] = length_seconds

        for idx in xrange(len(values)-1):
            v = values[idx]
            div, mod = divmod(length[v[0]], v[1])
            length[v[0]] = mod
            length[values[idx+1][0]] += div

        labels = []
        keys = ["days", "hours", "minutes", "seconds"]
        for k in keys:
            if length[k] == 1: labels.append(k[:-1])
            else: labels.append(k)

        if length["days"] != 0:
            length = "%d %s %d %s %d %s %d %s" % (
                    length["days"], labels[0], length["hours"], labels[1],
                    length["minutes"], labels[2], length["seconds"], labels[3]
            )
        elif length["hours"] != 0:
            length = "%d %s %d %s %d %s" % (
                    length["hours"], labels[1], length["minutes"], labels[2],
                    length["seconds"], labels[3]
            )
        elif length["minutes"] != 0:
            length = "%d %s %d %s" % (
                    length["minutes"], labels[2], length["seconds"], labels[3])
        elif length["seconds"] != 0:
            length = "%d %s" % (length["seconds"], labels[3])

        if track_count == 1: info = "%s track | %s" % (track_count, length)
        else: info = "%s tracks | %s" % (track_count, length)

        cls.__instance.__playlist_info.set_text(info)

    @classmethod
    def update_position(cls, position):
        if position > cls.__instance.__duration_nanoseconds:
            cls.__instance.__position = cls.__instance.__duration
        else:
            cls.__instance.__position = cls.__instance.__convert_time(position)
        cls.__instance.__update_track_status()

    def set_visibility(self, state, hide_progressbar=True):
        if hide_progressbar:
            self.__pb.set_visible(False)
            self.__pb_label.set_visible(False)
        else:
            self.__pb.set_visible(True)
            self.__pb_label.set_visible(True)

        self.set_visible(state)
        blacfg.setboolean("general", "statusbar", state)

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
            try: gobject.source_remove(self.__tid)
            except TypeError: pass
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
        except TypeError: pass

        if arg == 1.0:
            self.__track_info.set_visible(True)
            self.__pb.set_visible(False)
            self.__pb_label.set_visible(False)
            self.__pb.set_text("")

