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

import os
from math import log10

import gobject
import pygst
pygst.require("0.10")
import gst

import blaplay
from blaplay import blaconst, blacfg, blautils

library = None
player = None


def init():
    blaplay.print_i("Initializing the playback device")

    from blaplay import bladb
    global library, player
    library = bladb.library
    player = BlaPlayer()


class BlaPlayer(gobject.GObject):
    __gsignals__ = {
        "get_track": blaplay.signal(2),
        "state_changed": blaplay.signal(0),
        "track_changed": blaplay.signal(0),
        "track_stopped": blaplay.signal(0),
        "new_buffer": blaplay.signal(1)
    }

    __bin = None
    __volume = None
    __equalizer = None
    __uri = None
    __state = blaconst.STATE_STOPPED

    def __init__(self):
        super(BlaPlayer, self).__init__()

    def __init_pipeline(self):
        bin = gst.Bin()

        filt = gst.element_factory_make('capsfilter')
        filt.set_property("caps", gst.caps_from_string(
                "audio/x-raw-float, rate=(int)44100, channels=(int)2"))
        self.__equalizer = gst.element_factory_make("equalizer-10bands")
        tee = gst.element_factory_make("tee")
        queue_vis = gst.element_factory_make("queue")
        queue_vis.set_property("max_size_time", 500 * gst.MSECOND)

        def new_buffer(sink): self.emit("new_buffer", sink.emit("pull_buffer"))
        appsink = gst.element_factory_make("appsink")
        appsink.set_property("drop", False)
        appsink.set_property("sync", True)
        appsink.set_property("emit_signals", True)
        appsink.connect("new_buffer", new_buffer)

        queue_player = gst.element_factory_make("queue")
        queue_player.set_property("max_size_time", 500 * gst.MSECOND)
        sink = gst.element_factory_make("autoaudiosink")

        elements = [filt, self.__equalizer, tee, queue_vis, appsink,
                queue_player, sink]
        map(bin.add, elements)

        pad = elements[0].get_static_pad("sink")
        bin.add_pad(gst.GhostPad("sink", pad))

        gst.element_link_many(filt, self.__equalizer, tee)
        gst.element_link_many(tee, queue_player, sink)
        gst.element_link_many(tee, queue_vis, appsink)

        self.__bin = gst.element_factory_make("playbin2")
        self.__bin.set_property("audio_sink", bin)
        self.__bin.set_property("video_sink", None)
        self.__bin.connect("about_to_finish", self.__about_to_finish)

        bus = self.__bin.get_bus()
        bus.add_signal_watch()
        self.__busid = bus.connect("message", self.__on_message)

        if blacfg.getboolean("player", "muted"): volume = 0.0
        else: volume = blacfg.getfloat("player", "volume")
        self.__bin.set_property("volume", volume)

        self.enable_equalizer(blacfg.getboolean("player", "use.equalizer"))

    def __about_to_finish(self, player):
        # TODO: implement gapless playback
        pass

    @blautils.gtk_thread
    def __on_message(self, bus, message):
        if message.type == gst.MESSAGE_EOS: self.next(force_advance=False)
        elif message.type == gst.MESSAGE_ERROR:
            self.stop()
            err, debug = message.parse_error()
            from blaplay.blagui import blaguiutils
            blaguiutils.error_dialog("Error", "%s" % err)

    def set_equalizer_value(self, band, value):
        if self.__bin:
            if blacfg.getboolean("player", "use.equalizer"):
                self.__equalizer.set_property("band%d" % band, value)

    def enable_equalizer(self, state):
        if self.__bin:
            values = None
            if state:
                try:
                    values = blacfg.getlistfloat("equalizer.profiles",
                            blacfg.getstring("player", "equalizer.profile"))
                except: pass

            if not values: values = [0.0] * blaconst.EQUALIZER_BANDS
            for band, value in enumerate(values):
                self.__equalizer.set_property("band%d" % band, value)

    def set_volume(self, volume):
        if self.__bin:
            volume /= 100.

            if blacfg.getboolean("player", "logarithmic.volume.control"):
                volume_db = 50 * (volume - 1.0)
                if volume_db == -50: volume = 0
                else: volume = pow(10, volume_db / 20.0)

            if volume > 1.0: volume = 1.0
            elif volume < 0.0: volume = 0.0

            self.__bin.set_property("volume", volume)

    def seek(self, pos):
        self.__bin.seek_simple(gst.FORMAT_TIME, gst.SEEK_FLAG_FLUSH, pos)

    def get_position(self):
        try: pos = self.__bin.query_position(gst.FORMAT_TIME, None)[0]
        except: pos = -1
        return pos

    def get_track(self, uri=False):
        if not self.__uri: return None
        elif uri: return self.__uri
        else:
            try: return library[self.__uri]
            except KeyError: return None

    def get_state(self):
        return self.__state

    def play_track(self, playlist, uri):
        if uri:
            self.__uri = uri
            self.play()
        else: self.stop()

    def play(self):
#        u = urllib.urlopen("http://www.wdr.de/wdrlive/media/einslive.m3u")
#        s = u.read()
#        u.close()
#        bin.set_property("uri", s)

        if not self.__uri: self.emit("get_track", blaconst.TRACK_PLAY, True)
        else:
            # check if the resource is available. if it's not it's best to stop
            # trying and inform the user about the situation. if we'd just ask
            # for another track we'd potentially end up in an infinite loop
            if (not os.path.exists(self.__uri) or
                    not os.path.isfile(self.__uri)):
                from blaplay.blagui import blaguiutils
                uri = self.__uri
                self.stop()
                blaguiutils.error_dialog("Playback error",
                        "Resource \"%s\" unavailable." % uri)
                return

            # if update returns None it means the track needed updating, but
            # failed to be parsed properly so request another song
            if not library.update_track(self.__uri, return_track=True):
                self.emit("get_track", blaconst.TRACK_PLAY, True)

            if self.__state == blaconst.STATE_STOPPED: self.__init_pipeline()
            self.__bin.set_state(gst.STATE_NULL)
            self.__bin.set_property("uri", "file://%s" % self.__uri)
            self.__bin.set_state(gst.STATE_PLAYING)

            self.__state = blaconst.STATE_PLAYING
            self.emit("track_changed")
            self.emit("state_changed")

    def pause(self):
        if self.__state == blaconst.STATE_PAUSED:
            self.__bin.set_state(gst.STATE_PLAYING)
            self.__state = blaconst.STATE_PLAYING

        elif self.__state == blaconst.STATE_PLAYING:
            self.__bin.set_state(gst.STATE_PAUSED)
            self.__state = blaconst.STATE_PAUSED

        self.emit("state_changed")

    def stop(self):
        if self.__bin:
            self.__bin.set_state(gst.STATE_NULL)
            bus = self.__bin.get_bus()
            bus.disconnect(self.__busid)
            bus.remove_signal_watch()
            self.__bin = None
            self.__equalizer = None
            self.__uri = None

        self.__state = blaconst.STATE_STOPPED
        self.emit("state_changed")
        self.emit("track_stopped")

    def previous(self):
        if self.__bin: self.__bin.set_state(gst.STATE_NULL)
        self.emit("get_track", blaconst.TRACK_PREVIOUS, True)

    def next(self, force_advance=True):
        if self.__bin: self.__bin.set_state(gst.STATE_NULL)
        self.emit("get_track", blaconst.TRACK_NEXT, force_advance)

    def random(self):
        if self.__bin: self.__bin.set_state(gst.STATE_NULL)
        self.emit("get_track", blaconst.TRACK_RANDOM, True)

    def play_pause(self):
        if self.__state == blaconst.STATE_STOPPED: self.play()
        else: self.pause()

