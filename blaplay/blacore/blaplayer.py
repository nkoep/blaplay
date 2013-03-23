# blaplay, Copyright (C) 2012-2013  Niklas Koep

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
try:
    import pygst
    try:
        pygst.require("0.10")
    except pygst.RequiredVersionError:
        raise ImportError
    import gst
except ImportError:
    class gst(object):
        class ElementNotFoundError(Exception):
            pass

        @classmethod
        def element_factory_find(cls, element):
            return None

        @classmethod
        def element_factory_make(cls, element):
            raise gst.ElementNotFoundError

import blaplay
library = blaplay.bla.library
from blaplay.blacore import blaconst, blacfg
from blaplay import blautil
from blaplay.formats._identifiers import TITLE

BlaStatusbar = None
gstreamer_is_working = None


def init():
    def test_gstreamer_setup():
        try:
            gst.Bin()
        except AttributeError:
            return False
        for element in "capsfilter tee appsink autoaudiosink".split():
            try:
                gst.element_factory_make(element)
            except gst.ElementNotFoundError:
                return False
        return True

    print_i("Initializing the playback device")

    global gstreamer_is_working
    gstreamer_is_working = test_gstreamer_setup()

    # Make sure mad is used for decoding mp3s if both the mad and fluendo
    # decoder are available on the system as mad should be faster.
    fluendo, mad = map(gst.element_factory_find, ["flump3dec", "mad"])
    if fluendo and mad:
        fluendo.set_rank(min(fluendo.get_rank(), max(mad.get_rank() - 1, 0)))

    player = BlaPlayer()
    return player


class BlaPlayer(gobject.GObject):
    __gsignals__ = {
        "get_track": blautil.signal(2),
        "get_station": blautil.signal(1),
        "state_changed": blautil.signal(0),
        "track_changed": blautil.signal(0),
        "track_stopped": blautil.signal(0),
        "new_buffer": blautil.signal(1),
        "seek": blautil.signal(0),
        "get_xid": blautil.signal(0)
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
        if not gstreamer_is_working:
            self.stop()
            from blaplay.blagui import blaguiutils
            blaguiutils.error_dialog(
                "Error", "Failed to construct GStreamer pipeline. Make sure "
                "GStreamer 0.10, its Python bindings, and gst-plugins-base "
                "and gst-plugins-good are installed.")
            return False

        # TODO: rename bin_ to audio_sink
        bin_ = gst.Bin()

        filt = gst.element_factory_make("capsfilter")
        filt.set_property(
            "caps", gst.caps_from_string("audio/x-raw-float, "
                                         "rate=(int)44100, "
                                         "channels=(int)2, "
                                         "width=(int)32, "
                                         "depth=(int)32, "
                                         "endianness=(int)1234"))
        self.__equalizer = gst.element_factory_make("equalizer-10bands")
        tee = gst.element_factory_make("tee")
        queue = gst.element_factory_make("queue")
        queue.set_property("silent", True)

        def new_buffer(sink):
            self.emit("new_buffer", sink.emit("pull_buffer"))
        appsink = gst.element_factory_make("appsink")
        appsink.set_property("drop", True)
        appsink.set_property("sync", True)
        appsink.set_property("emit_signals", True)
        appsink.connect("new_buffer", new_buffer)

        sink = gst.element_factory_make("autoaudiosink")

        self.__volume = gst.element_factory_make("volume")
        elements = [filt, self.__equalizer, tee, queue, appsink,
                    self.__volume, sink]
        map(bin_.add, elements)

        pad = elements[0].get_static_pad("sink")
        bin_.add_pad(gst.GhostPad("sink", pad))

        gst.element_link_many(filt, self.__equalizer, tee)
        gst.element_link_many(tee, self.__volume, sink)
        gst.element_link_many(tee, queue, appsink)

        self.__fake_sink = gst.element_factory_make("fakesink")
        self.__video_sink = gst.element_factory_make("xvimagesink")
        self.__video_sink.set_property("force_aspect_ratio", True)

        self.__bin = gst.element_factory_make("playbin2")
        self.__bin.set_property("audio_sink", bin_)
        self.__bin.set_property("buffer_duration", 500 * gst.MSECOND)
        self.__bin.set_property("video_sink", self.__fake_sink)
#        GST_PLAY_FLAG_VIDEO = 1 << 0
#        GST_PLAY_FLAG_TEXT = 1 << 2
#        flags = self.__bin.get_property("flags")
#        flags &= ~(GST_PLAY_FLAG_VIDEO | GST_PLAY_FLAG_TEXT)
#        self.__bin.set_property("flags", flags)

        self.__bin.connect("about_to_finish", self.__about_to_finish)
        self.__bin.set_state(gst.STATE_READY)

        bus = self.__bin.get_bus()
        bus.add_signal_watch()
        bus.enable_sync_message_emission()
        bus.connect("sync_message::element", lambda *x: self.emit("get_xid"))
        self.__busid = bus.connect("message", self.__message)

        if blacfg.getboolean("player", "muted"):
            volume = 0
        else:
            volume = blacfg.getfloat("player", "volume") * 100
        self.set_volume(volume)

        self.enable_equalizer(blacfg.getboolean("player", "use.equalizer"))

        return True

    @blautil.idle
    def __about_to_finish(self, player):
        # TODO: implement gapless playback

        # The signal we connect this callback to is emitted in a gst streaming
        # thread so we decorate it with `idle' to push it to the main thread as
        # we're likely to call gtk functions somewhere down the line from here.
        pass

    def __message(self, bus, message):
        if message.type == gst.MESSAGE_EOS:
            self.next(force_advance=False)
        elif message.type == gst.MESSAGE_TAG:
            self.__parse_tags(message.parse_tag())
        elif message.type == gst.MESSAGE_BUFFERING:
            # We can't import from blastatusbar on module level as it'd create
            # circular imports.
            global BlaStatusbar
            if BlaStatusbar is None:
                from blaplay.blagui.blastatusbar import BlaStatusbar
            percentage = message.parse_buffering()
            s = "Buffering: %d %%" % percentage
            BlaStatusbar.set_view_info(blaconst.VIEW_RADIO, s)
            if percentage == 0:
                print_d("Start buffering...")
            elif percentage == 100:
                self.__bin.set_state(gst.STATE_PLAYING)
                self.__state = blaconst.STATE_PLAYING
                self.emit("track_changed")
                self.emit("state_changed")
                gobject.timeout_add(
                    2000, BlaStatusbar.set_view_info, blaconst.VIEW_RADIO, "")
                print_d("Finished buffering")
        elif message.type == gst.MESSAGE_ERROR:
            self.stop()
            err, debug = message.parse_error()
            from blaplay.blagui import blaguiutils
            blaguiutils.error_dialog("Error", str(err))

    def __parse_tags(self, tags):
        # TODO: use these when playing a video as well

        MAPPING = {
            "location": "station",
            "organization": "organization",
            "title": TITLE
        }

        if not self.radio:
            return
        for key in tags.keys():
            value = tags[key]
            try:
                value = unicode(value.decode("utf-8", "replace"))
            except AttributeError:
                pass
            if key in ["organization", "location", "title"]:
                self.__station[MAPPING[key]] = value
        gobject.idle_add(self.emit, "state_changed")

    def set_xwindow_id(self, window_id):
        try:
            if window_id == 0:
                self.__bin.set_property("video_sink", self.__fake_sink)
            else:
                self.__bin.set_property("video_sink", self.__video_sink)
                self.__video_sink.set_xwindow_id(window_id)
        except AttributeError:
            pass

    def set_equalizer_value(self, band, value):
        if blacfg.getboolean("player", "use.equalizer"):
            try:
                self.__equalizer.set_property("band%d" % band, value)
            except AttributeError:
                pass

    def enable_equalizer(self, state):
        values = None
        if state:
            try:
                values = blacfg.getlistfloat(
                    "equalizer.profiles",
                    blacfg.getstring("player", "equalizer.profile"))
            except:
                pass

        if not values:
            values = [0.0] * blaconst.EQUALIZER_BANDS
        try:
            for band, value in enumerate(values):
                self.__equalizer.set_property("band%d" % band, value)
        except AttributeError:
            pass

    def set_volume(self, volume):
        volume /= 100.

        if blacfg.getboolean("player", "logarithmic.volume.scale"):
            volume_db = 50 * (volume - 1.0)
            if volume_db == -50:
                volume = 0
            else:
                volume = pow(10, volume_db / 20.0)

        if volume > 1.0:
            volume = 1.0
        elif volume < 0.0:
            volume = 0.0

        try:
            self.__volume.set_property("volume", volume)
        except AttributeError:
            pass

    def seek(self, pos):
        self.__bin.seek_simple(gst.FORMAT_TIME, gst.SEEK_FLAG_FLUSH, pos)
        self.emit("seek")

    def get_position(self):
        if self.radio:
            return 0
        try:
            return self.__bin.query_position(gst.FORMAT_TIME, None)[0]
        except gst.QueryError:
            return 0

    def get_track(self):
        try:
            return self.__station or blaplay.bla.library[self.__uri]
        except KeyError:
            pass
        return None

    def get_state(self):
        return self.__state

    def play_track(self, playlist, uri):
        if uri:
            self.__uri = uri
            self.play()
        else:
            self.stop()

    def play(self):
        if not self.__uri:
            if blacfg.getint("general", "view") == blaconst.VIEW_RADIO:
                args = ("get_station", blaconst.TRACK_PLAY)
            else:
                args = ("get_track", blaconst.TRACK_PLAY, True)
            return self.emit(*args)

        # Check if the resource is available. If it's not it's best to stop
        # trying and inform the user about the situation. If we'd just ask
        # for another track we'd potentially end up hitting the interpreter's
        # recursion limit in case lots of tracks turn out to be invalid.
        if not os.path.exists(self.__uri) or not os.path.isfile(self.__uri):
            from blaplay.blagui import blaguiutils
            uri = self.__uri
            self.stop()
            blaguiutils.error_dialog("Playback error",
                                     "Resource \"%s\" unavailable." % uri)
            return

        # If update returns None it means the track needed updating, but
        # failed to be parsed properly so request another song.
        if not blaplay.bla.library.update_track(self.__uri, return_track=True):
            self.emit("get_track", blaconst.TRACK_PLAY, True)

        if (self.__state == blaconst.STATE_STOPPED and
            not self.__init_pipeline()):
            return
        self.__bin.set_state(gst.STATE_NULL)
        self.__bin.set_property("uri", "file://%s" % self.__uri)
        self.__bin.set_state(gst.STATE_PLAYING)
        self.__station = None

        self.__state = blaconst.STATE_PLAYING
        self.emit("track_changed")
        self.emit("state_changed")

    def play_station(self, station):
        if not station:
            return self.stop()
        if (self.__state == blaconst.STATE_STOPPED and
            not self.__init_pipeline()):
            return
        self.__station = station
        self.__uri = None
        self.__bin.set_state(gst.STATE_NULL)
        self.__bin.set_property("uri", self.__station.location)
        self.__bin.set_state(gst.STATE_PAUSED)
        self.__state = blaconst.STATE_PAUSED
        self.emit("track_changed")
        self.emit("state_changed")

    @property
    def radio(self):
        return bool(self.__station)

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
        if self.__bin:
            self.__bin.set_state(gst.STATE_NULL)
        if self.radio:
            args = ("get_station", blaconst.TRACK_PREVIOUS)
        else:
            args = ("get_track", blaconst.TRACK_PREVIOUS, True)
        self.emit(*args)

    def next(self, force_advance=True):
        if self.__bin:
            self.__bin.set_state(gst.STATE_NULL)
        if self.radio:
            args = ("get_station", blaconst.TRACK_NEXT)
        else:
            args = ("get_track", blaconst.TRACK_NEXT, force_advance)
        self.emit(*args)

    def random(self):
        if self.__bin:
            self.__bin.set_state(gst.STATE_NULL)
        if self.radio:
            args = ("get_station", blaconst.TRACK_RANDOM)
        else:
            args = ("get_track", blaconst.TRACK_RANDOM, True)
        self.emit(*args)

    def play_pause(self):
        if self.__state == blaconst.STATE_STOPPED:
            self.play()
        else:
            self.pause()

