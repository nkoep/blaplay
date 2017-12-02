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
except ImportError:
    die("Python 2 PyGST module is missing")
try:
    pygst.require("0.10")
except pygst.RequiredVersionError:
    die("GStreamer 0.10 is missing")
import gst

import blaplay
from blaplay.blacore import blaconst, blacfg
from blaplay import blautil

gstreamer_is_working = None


def init(library):
    def test_gstreamer():
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
    gstreamer_is_working = test_gstreamer()

    # Make sure mad is used for decoding mp3s if both the mad and fluendo
    # decoder are available on the system as mad should be faster.
    fluendo, mad = map(gst.element_factory_find, ["flump3dec", "mad"])
    if fluendo and mad:
        fluendo.set_rank(min(fluendo.get_rank(), max(mad.get_rank() - 1, 0)))

    return BlaPlayer(library)


class BlaPlayer(gobject.GObject):
    __gsignals__ = {
        "get-track": blautil.signal(2),
        "state-changed": blautil.signal(0),
        "track-changed": blautil.signal(0),
        "track-stopped": blautil.signal(0),
        "new-buffer": blautil.signal(1),
        "seeked": blautil.signal(1)
    }

    _playbin = None
    _volume = None
    _equalizer = None
    _uri = None
    _state = blaconst.STATE_STOPPED

    def __init__(self, library):
        super(BlaPlayer, self).__init__()
        self._library = library

    def _init_pipeline(self):
        if not gstreamer_is_working:
            self.stop()
            from blaplay.blagui import blaguiutil
            blaguiutil.error_dialog(
                "Error", "Failed to construct GStreamer pipeline. Make sure "
                "GStreamer 0.10, its Python bindings, and gst-plugins-base "
                "and gst-plugins-good are installed.")
            return False

        audio_sink = gst.Bin()
        self._equalizer = gst.element_factory_make("equalizer-10bands")
        tee = gst.element_factory_make("tee")
        queue = gst.element_factory_make("queue")
        queue.set_property("silent", True)

        def on_new_buffer(sink):
            # Careful, the `sink.emit` is synchronous and actually returns the
            # buffer.
            self.emit("new-buffer", sink.emit("pull-buffer"))
        appsink = gst.element_factory_make("appsink")
        appsink.set_property(
            "caps", gst.caps_from_string("audio/x-raw-float,"
                                         "rate=(int)44100,"
                                         "channels=(int)2,"
                                         "width=(int)32,"
                                         "depth=(int)32,"
                                         "endianness=(int)1234"))
        appsink.set_property("drop", True)
        appsink.set_property("sync", True)
        appsink.set_property("emit_signals", True)
        appsink.connect("new-buffer", on_new_buffer)

        sink = gst.element_factory_make("autoaudiosink")

        self._volume = gst.element_factory_make("volume")
        audio_sink.add_many(
            self._equalizer, tee, self._volume, sink, queue, appsink)

        # Hook up the first element's sink pad to the bin's sink pad.
        pad = self._equalizer.get_static_pad("sink")
        audio_sink.add_pad(gst.GhostPad("sink", pad))

        # Link elements
        gst.element_link_many(self._equalizer, tee)
        gst.element_link_many(tee, self._volume, sink)
        gst.element_link_many(tee, queue, appsink)

        self._playbin = gst.element_factory_make("playbin2")
        self._playbin.set_property("audio-sink", audio_sink)
        self._playbin.set_property("buffer-duration", 500 * gst.MSECOND)

        self._playbin.set_state(gst.STATE_READY)

        bus = self._playbin.get_bus()
        bus.add_signal_watch()
        bus.enable_sync_message_emission()
        self._message_id = bus.connect("message", self._on_message)

        if blacfg.getboolean("player", "muted"):
            volume = 0
        else:
            volume = blacfg.getfloat("player", "volume") * 100
        self.set_volume(volume)

        self.enable_equalizer(blacfg.getboolean("player", "use.equalizer"))

        return True

    def _on_message(self, bus, message):
        if message.type == gst.MESSAGE_EOS:
            self.next(force_advance=False)
        elif message.type == gst.MESSAGE_ERROR:
            self.stop()
            err, debug = message.parse_error()
            from blaplay.blagui import blaguiutil
            blaguiutil.error_dialog("Error", str(err))

    def set_equalizer_value(self, band, value):
        if blacfg.getboolean("player", "use.equalizer"):
            try:
                self._equalizer.set_property("band%d" % band, value)
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
                self._equalizer.set_property("band%d" % band, value)
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
            self._volume.set_property("volume", volume)
        except AttributeError:
            pass

    def seek(self, pos):
        self._playbin.seek_simple(gst.FORMAT_TIME, gst.SEEK_FLAG_FLUSH, pos)
        self.emit("seeked", pos)

    def get_position(self):
        try:
            return self._playbin.query_position(gst.FORMAT_TIME, None)[0]
        except (AttributeError, gst.QueryError):
            pass
        return 0

    def get_track(self):
        try:
            return self._library[self._uri]
        except KeyError:
            pass
        return None

    def get_state(self):
        return self._state

    def get_state_string(self):
        if self._state == blaconst.STATE_PLAYING:
            return "Playing"
        elif self._state == blaconst.STATE_PAUSED:
            return "Paused"
        return "Stopped"

    def play_track(self, uri):
        # FIXME: It's weird to set the uri here and play the track afterwards.
        #        Maybe we should compose these two methods differently.
        if uri:
            self._uri = uri
            self.play()
        else:
            self.stop()

    def play(self):
        if not self._uri:
            args = ("get-track", blaconst.TRACK_PLAY, True)
            return self.emit(*args)

        # Check if the resource is available. If it's not it's best to stop
        # trying and inform the user about the situation. If we'd just ask
        # for another track we'd potentially end up hitting the interpreter's
        # recursion limit in case lots of tracks turn out to be invalid.
        if not os.path.exists(self._uri) or not os.path.isfile(self._uri):
            from blaplay.blagui import blaguiutil
            uri = self._uri
            self.stop()
            blaguiutil.error_dialog(
                "Playback error", "Resource \"%s\" unavailable." % uri)
            return

        # XXX: Is it sensible to update the track from here? Seems like the
        #      library (monitor) should be in charge of that.
        # If `update_track' returns None it means the track needed updating,
        # but failed to be parsed properly so request another song.
        if self._library.update_track(self._uri) is None:
            self.emit("get-track", blaconst.TRACK_PLAY, True)

        if (self._state == blaconst.STATE_STOPPED and
            not self._init_pipeline()):
            return
        self._playbin.set_state(gst.STATE_NULL)
        self._playbin.set_property("uri", "file://%s" % self._uri)
        self._playbin.set_state(gst.STATE_PLAYING)

        self._state = blaconst.STATE_PLAYING
        self.emit("track-changed")
        self.emit("state-changed")

    def pause(self):
        if self._state == blaconst.STATE_PAUSED:
            self._playbin.set_state(gst.STATE_PLAYING)
            self._state = blaconst.STATE_PLAYING
        elif self._state == blaconst.STATE_PLAYING:
            self._playbin.set_state(gst.STATE_PAUSED)
            self._state = blaconst.STATE_PAUSED
        self.emit("state-changed")

    def play_pause(self):
        if self._state == blaconst.STATE_STOPPED:
            self.play()
        else:
            self.pause()

    def stop(self):
        if self._playbin:
            self._playbin.set_state(gst.STATE_NULL)
            bus = self._playbin.get_bus()
            bus.disconnect(self._message_id)
            bus.remove_signal_watch()

        self._playbin = None
        self._equalizer = None
        self._uri = None

        self._state = blaconst.STATE_STOPPED
        self.emit("state-changed")
        self.emit("track-stopped")

    def previous(self):
        if self._playbin:
            self._playbin.set_state(gst.STATE_NULL)
        self.emit("get-track", blaconst.TRACK_PREVIOUS, True)

    def next(self, force_advance=True):
        if self._playbin:
            self._playbin.set_state(gst.STATE_NULL)
        self.emit("get-track", blaconst.TRACK_NEXT, force_advance)

    def random(self):
        if self._playbin:
            self._playbin.set_state(gst.STATE_NULL)
        self.emit("get-track", blaconst.TRACK_RANDOM, True)
