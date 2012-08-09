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

import math

import gobject
import gtk
import cairo

from blaplay import blaconst, blacfg, blaplayer
player = blaplayer.player
from blastatusbar import BlaStatusbar
from blaplay.formats._identifiers import *

CMD_PLAYPAUSE, CMD_STOP, CMD_PREVIOUS, CMD_NEXT, CMD_NEXT_RANDOM = xrange(5)


class PositionSlider(gtk.HScale):
    __seek_interval = 100
    __scroll_delay = 10
    __scrollid = None
    __seeking = False
    __changed = False

    def __init__(self):
        super(PositionSlider, self).__init__()

        self.set_draw_value(False)

        self.connect("key_press_event", lambda *x: True)
        self.connect("button_press_event", self.__seek_start)
        self.connect("button_release_event", self.__seek_end)
        self.connect("scroll_event", self.__scroll)
        self.connect("value_changed", self.__value_changed)
        player.connect("state_changed", self.__state_changed)
        player.connect("track_changed", self.__track_changed)

        self.__seekid = gobject.timeout_add(
                self.__seek_interval, self.__update_position)

    def __scroll_timeout(self, direction):
        player.seek(self.get_value())
        self.__seeking = False
        return False

    def __scroll(self, scale, event):
        if self.__seeking or player.get_state() == blaconst.STATE_STOPPED:
            return True
        if self.__scrollid: gobject.source_remove(self.__scrollid)
        self.__seeking = True
        self.__scrollid = gobject.timeout_add(
                self.__scroll_delay, self.__scroll_timeout, event.direction)
        return False

    def __value_changed(self, scale):
        # check for position changes during seeking. the `__changed' attribute
        # is used to signal to the callback function of button_release_event's
        # that it should perform a seek operation on the playback device
        if self.__seeking: self.__changed = True
        BlaStatusbar.update_position(self.get_value())

    def __seek_start(self, scale, event):
        if player.get_state() == blaconst.STATE_STOPPED: return True
        if hasattr(event, "button"): event.button = 2
        self.__seeking = True

    def __seek_end(self, scale, event):
        if player.get_state() == blaconst.STATE_STOPPED: return True
        if hasattr(event, "button"): event.button = 2
        self.__seeking = False
        if self.__changed:
            # the slider length (upper bound of the adjustment) is directly
            # proportional to the track length (in fact, it's the length of the
            # track in nanoseconds). the offset we should add to the position
            # (number of units the slider would move in one update step) can be
            # calculated as 1e6 * __seek_interval.
            player.seek(self.get_value() + 1e6 * self.__seek_interval)
            self.__changed = False

    def __update_position(self):
        state = player.get_state()
        if state == blaconst.STATE_STOPPED:
            self.set_value(0)
        elif (not state == blaconst.STATE_PAUSED and
                not state == blaconst.STATE_STOPPED and
                not self.__seeking):
            position = player.get_position()
            if position != -1:
                self.set_value(position)
                BlaStatusbar.update_position(position)
        return True

    def __state_changed(self, player):
        if player.get_state() == blaconst.STATE_STOPPED or player.radio:
            self.set_sensitive(False)
        else: self.set_sensitive(True)

    def __track_changed(self, player):
        # we need to remove the timer on track changes to make sure the slider
        # really resets properly
        self.set_value(0)
        gobject.source_remove(self.__seekid)
        track = player.get_track()
        duration = track[LENGTH] * 1e9
        self.set_range(0, max(1, duration))
        self.set_increments(-int(duration / 100.), -int(duration / 10.))
        self.__seekid = gobject.timeout_add(
                self.__seek_interval, self.__update_position)

class VolumeControl(gtk.HBox):
    __states = ["muted", "low", "medium", "high"]

    def __init__(self):
        super(VolumeControl, self).__init__(spacing=5)

        self.__volume = int(blacfg.getfloat("player", "volume") * 100)
        state = blacfg.getboolean("player", "muted")
        if not state: volume = self.__volume
        else: volume = 0.0

        # the mute button
        self.__image = gtk.Image()
        mute = gtk.ToggleButton()
        mute.add(self.__image)
        mute.set_relief(gtk.RELIEF_NONE)
        mute.set_active(state)
        mute.connect("toggled", self.__mute_toggled)

        # the scale
        self.__scale = gtk.HScale()
        self.__scale.set_range(0, 100)
        self.__scale.set_increments(-1, -10)
        self.__scale.set_size_request(120, 20)
        self.__scale.set_update_policy(gtk.UPDATE_CONTINUOUS)
        self.__scale.set_draw_value(False)
        self.__scale.set_value(volume)
        self.__scale.connect("value_changed", self.__volume_changed)
        self.__scale.connect("button_press_event", self.__button_press_event)
        self.__scale.connect(
                "button_release_event", self.__button_release_event)
        self.__scale.connect("scroll_event", self.__scroll_event)
        self.__scale.connect("key_press_event", lambda *x: True)
        self.__scale.connect("query_tooltip", self.__query_tooltip)
        self.__scale.set_has_tooltip(True)

        self.__update_icon(state)

        self.pack_start(mute, expand=False)
        self.pack_start(self.__scale, expand=True)

    def __scroll_event(self, scale, event):
        if blacfg.getboolean("player", "muted"): return True

    def __button_press_event(self, scale, event):
        if blacfg.getboolean("player", "muted"): return True
        if hasattr(event, "button"): event.button = 2

    def __button_release_event(self, scale, event):
        if blacfg.getboolean("player", "muted"): return True

        if hasattr(event, "button"): event.button = 2
        self.__volume = self.__scale.get_value()
        player.set_volume(self.__volume)

    def __volume_changed(self, scale):
        state = blacfg.getboolean("player", "muted")

        if state: volume = self.__volume
        else: volume = scale.get_value()

        blacfg.set("player", "volume", volume / 100.)
        player.set_volume(scale.get_value())
        self.__update_icon(state)

    def __mute_toggled(self, button):
        state = button.get_active()
        blacfg.setboolean("player", "muted", state)
        if state:
            self.__volume = self.__scale.get_value()
            self.__scale.set_value(0)
        else: self.__scale.set_value(self.__volume)

    def __update_icon(self, state):
        icon_name = "audio-volume-%s"
        volume = self.__scale.get_value()

        # unmute
        if not state:
            k = int(math.ceil(2.95 * volume / 100.))
            icon_name %= self.__states[k]
        # mute
        else: icon_name %= self.__states[0]
        self.__image.set_from_icon_name(icon_name, gtk.ICON_SIZE_BUTTON)

    def __query_tooltip(self, *args):
        volume = self.__scale.get_value()
        if blacfg.getboolean("player", "logarithmic.volume.scale"):
            if volume == 0: tooltip = "-Inf dB"
            else: tooltip = "%d dB" % (50 * (volume / 100 - 1))
        else: tooltip = "%d%%" % volume
        self.__scale.set_tooltip_text(tooltip)
        return False

class BlaToolbar(gtk.HBox):
    __state = None

    def __init__(self):
        super(BlaToolbar, self).__init__(spacing=10)

        # the button box
        ctrlbar = gtk.Table(rows=1, columns=5, homogeneous=True)
        ctrlbar.set_name("ctrlbar")

        img = gtk.Image()
        play_pause = gtk.Button()
        play_pause.add(img)
        play_pause.set_relief(gtk.RELIEF_NONE)
        play_pause.connect("clicked", self.__ctrl, CMD_PLAYPAUSE)
        ctrlbar.attach(play_pause, 0, 1, 0, 1)

        stop = gtk.Button()
        stop.add(gtk.image_new_from_stock(
                gtk.STOCK_MEDIA_STOP, gtk.ICON_SIZE_BUTTON))
        stop.set_relief(gtk.RELIEF_NONE)
        stop.set_tooltip_text("Stop")
        stop.connect("clicked", self.__ctrl, CMD_STOP)
        ctrlbar.attach(stop, 1, 2, 0, 1)

        previous = gtk.Button()
        previous.add(gtk.image_new_from_stock(
                gtk.STOCK_MEDIA_PREVIOUS, gtk.ICON_SIZE_BUTTON))
        previous.set_relief(gtk.RELIEF_NONE)
        previous.set_tooltip_text("Previous track")
        previous.connect("clicked", self.__ctrl, CMD_PREVIOUS)
        ctrlbar.attach(previous, 2, 3, 0, 1)

        next = gtk.Button()
        next.add(gtk.image_new_from_stock(
                gtk.STOCK_MEDIA_NEXT, gtk.ICON_SIZE_BUTTON))
        next.set_relief(gtk.RELIEF_NONE)
        next.set_tooltip_text("Next track")
        next.connect("clicked", self.__ctrl, CMD_NEXT)
        ctrlbar.attach(next, 3, 4, 0, 1)

        random = gtk.Button()
        random.add(gtk.image_new_from_icon_name(
                "stock_shuffle", gtk.ICON_SIZE_BUTTON))
        random.set_relief(gtk.RELIEF_NONE)
        random.set_tooltip_text("Random track")
        random.connect("clicked", self.__ctrl, CMD_NEXT_RANDOM)
        ctrlbar.attach(random, 4, 5, 0, 1)

        # position slider
        seekbar = PositionSlider()

        # volume control
        volume = VolumeControl()

        self.pack_start(ctrlbar, expand=False)
        self.pack_start(seekbar, expand=True)
        self.pack_start(volume, expand=False)

        player.connect("state_changed", self.__update_state, img, play_pause)
        player.emit("state_changed")

        self.show_all()

    def __update_state(self, player, img, play_pause):
        state = player.get_state()
        if state == self.__state: return

        if state == blaconst.STATE_PLAYING:
            s = gtk.STOCK_MEDIA_PAUSE
            tt = "Pause"
        elif state == blaconst.STATE_PAUSED or state == blaconst.STATE_STOPPED:
            s = gtk.STOCK_MEDIA_PLAY
            tt = "Play"

        img.set_from_stock(s, gtk.ICON_SIZE_BUTTON)
        img.show()
        play_pause.set_tooltip_text(tt)

        self.__state = state

    def __ctrl(self, button, cmd):
        if cmd == CMD_PLAYPAUSE: player.play_pause()
        elif cmd == CMD_STOP: player.stop()
        elif cmd == CMD_PREVIOUS: player.previous()
        elif cmd == CMD_NEXT: player.next()
        elif cmd == CMD_NEXT_RANDOM: player.random()

