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
from blaplay.formats._identifiers import TITLE

library = None
player = None


def init():
    print_i("Initializing the playback device")

    from blaplay import bladb
    global library, player

    fluendo, mad = map(gst.element_factory_find, ["flump3dec", "mad"])
    if fluendo and mad:
        fluendo.set_rank(min(fluendo.get_rank(), max(mad.get_rank() - 1, 0)))

    library = bladb.library
    player = BlaPlayer()


class BlaPlayer(gobject.GObject):
    __gsignals__ = {
        "get_track": blaplay.signal(2),
        "get_station": blaplay.signal(1),
        "state_changed": blaplay.signal(0),
        "track_changed": blaplay.signal(0),
        "track_stopped": blaplay.signal(0),
        "new_buffer": blaplay.signal(1),
        "seek": blaplay.signal(0)
    }

    __bin = None
    __volume = None
    __equalizer = None
    __uri = None
    __station = None
    __state = blaconst.STATE_STOPPED

    def __init__(self):
        super(BlaPlayer, self).__init__()

    def __init_pipeline(self):
        bin = gst.Bin()

        filt = gst.element_factory_make("capsfilter")
        filt.set_property("caps", gst.caps_from_string(
                "audio/x-raw-float, rate=(int)44100, channels=(int)2, "
                "width=(int)32, depth=(int)32, endianness=(int)1234")
        )
        self.__equalizer = gst.element_factory_make("equalizer-10bands")
        tee = gst.element_factory_make("tee")
        queue = gst.element_factory_make("queue")
        queue.set_property("silent", True)

        def new_buffer(sink): self.emit("new_buffer", sink.emit("pull_buffer"))
        appsink = gst.element_factory_make("appsink")
        appsink.set_property("drop", True)
        appsink.set_property("sync", True)
        appsink.set_property("emit_signals", True)
        appsink.connect("new_buffer", new_buffer)

        sink = gst.element_factory_make("autoaudiosink")

        elements = [filt, self.__equalizer, tee, queue, appsink, sink]
        map(bin.add, elements)

        pad = elements[0].get_static_pad("sink")
        bin.add_pad(gst.GhostPad("sink", pad))

        gst.element_link_many(filt, self.__equalizer, tee)
        gst.element_link_many(tee, sink)
        gst.element_link_many(tee, queue, appsink)

        self.__bin = gst.element_factory_make("playbin2")
        self.__bin.set_property("audio_sink", bin)
        self.__bin.set_property("buffer_duration", 500 * gst.MSECOND)
        self.__bin.set_property("video_sink", None)
        GST_PLAY_FLAG_VIDEO = 1 << 0
        GST_PLAY_FLAG_TEXT = 1 << 2
        flags = self.__bin.get_property("flags")
        flags &= ~(GST_PLAY_FLAG_VIDEO | GST_PLAY_FLAG_TEXT)
        self.__bin.set_property("flags", flags)
        self.__bin.connect("about_to_finish", self.__about_to_finish)
        self.__bin.set_state(gst.STATE_READY)

        bus = self.__bin.get_bus()
        bus.add_signal_watch()
        self.__busid = bus.connect("message", self.__on_message)

        if blacfg.getboolean("player", "muted"): volume = 0
        else: volume = blacfg.getfloat("player", "volume") * 100
        self.set_volume(volume)

        self.enable_equalizer(blacfg.getboolean("player", "use.equalizer"))

    def __about_to_finish(self, player):
        # TODO: implement gapless playback
        pass

    @blautils.gtk_thread
    def __on_message(self, bus, message):
        if message.type == gst.MESSAGE_EOS:
            self.next(force_advance=False)
        elif message.type == gst.MESSAGE_TAG:
            self.__parse_tags(message.parse_tag())
        elif message.type == gst.MESSAGE_BUFFERING:
            # we can't import from blastatusbar on module level as it'd create
            # circular imports
            from blaplay.blagui.blastatusbar import BlaStatusbar
            percentage = message.parse_buffering()
            s = "Buffering: %d %%" % percentage
            gobject.idle_add(
                    BlaStatusbar.set_view_info, blaconst.VIEW_RADIO, s)
            if percentage == 0: print_d("Start buffering...")
            elif percentage == 100:
                self.__bin.set_state(gst.STATE_PLAYING)
                self.__state = blaconst.STATE_PLAYING
                self.emit("track_changed")
                self.emit("state_changed")
                gobject.timeout_add(2000,
                        BlaStatusbar.set_view_info, blaconst.VIEW_RADIO, "")
                print_d("Finished buffering")
        elif message.type == gst.MESSAGE_ERROR:
            self.stop()
            err, debug = message.parse_error()
            from blaplay.blagui import blaguiutils
            blaguiutils.error_dialog("Error", "%s" % err)

    def __parse_tags(self, tags):
        MAPPING = {
            "location": "station",
            "organization": "organization",
            "title": TITLE
        }

        if not self.radio: return
        for key in tags.keys():
            value = tags[key]
            try: value = value.encode("utf-8")
            except AttributeError: pass
            if key in ["organization", "location", "title"]:
                self.__station[MAPPING[key]] = value
        gobject.idle_add(self.emit, "state_changed")

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

            if blacfg.getboolean("player", "logarithmic.volume.scale"):
                volume_db = 50 * (volume - 1.0)
                if volume_db == -50: volume = 0
                else: volume = pow(10, volume_db / 20.0)

            if volume > 1.0: volume = 1.0
            elif volume < 0.0: volume = 0.0

            self.__bin.set_property("volume", volume)

    def seek(self, pos):
        self.__bin.seek_simple(gst.FORMAT_TIME, gst.SEEK_FLAG_FLUSH, pos)
        self.emit("seek")

    def get_position(self):
        if self.radio: return 0
        try: return self.__bin.query_position(gst.FORMAT_TIME, None)[0]
        except gst.QueryError: return 0

    def get_track(self):
        try: return self.__station or library[self.__uri]
        except KeyError: pass
        return None

    def get_state(self):
        return self.__state

    def play_track(self, playlist, uri):
        if uri:
            self.__uri = uri
            self.play()
        else: self.stop()

    def play(self):
        # TODO: if we quit with a radio station playing emit a get_station
        #       signal instead
        if not self.__uri:
            self.emit("get_track", blaconst.TRACK_PLAY, True)
            return

        # check if the resource is available. if it's not it's best to stop
        # trying and inform the user about the situation. if we'd just ask
        # for another track we'd potentially end up exceeding python's
        # recursion limit if lots of tracks turn out to be invalid
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
        self.__station = None

        self.__state = blaconst.STATE_PLAYING
        self.emit("track_changed")
        self.emit("state_changed")

    def play_station(self, station):
        if not station: return self.stop()
        if self.__state == blaconst.STATE_STOPPED: self.__init_pipeline()
        self.__station = station
        self.__uri = None
        self.__bin.set_state(gst.STATE_NULL)
        self.__bin.set_property("uri", "%s" % self.__station.location)
        self.__bin.set_state(gst.STATE_PAUSED)
        self.__state = blaconst.STATE_PAUSED
        self.emit("track_changed")
        self.emit("state_changed")

    radio = property(lambda self: bool(self.__station))

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
            self.__station = None

        self.__state = blaconst.STATE_STOPPED
        self.emit("state_changed")
        self.emit("track_stopped")

    def previous(self):
        if self.__bin: self.__bin.set_state(gst.STATE_NULL)
        if self.radio: args = ("get_station", blaconst.TRACK_PREVIOUS)
        else: args = ("get_track", blaconst.TRACK_PREVIOUS, True)
        self.emit(*args)

    def next(self, force_advance=True):
        if self.__bin: self.__bin.set_state(gst.STATE_NULL)
        if self.radio: args = ("get_station", blaconst.TRACK_NEXT)
        else: args = ("get_track", blaconst.TRACK_NEXT, force_advance)
        self.emit(*args)

    def random(self):
        if self.__bin: self.__bin.set_state(gst.STATE_NULL)
        self.emit("get_track", blaconst.TRACK_RANDOM, True)

    def play_pause(self):
        if self.__state == blaconst.STATE_STOPPED: self.play()
        else: self.pause()

