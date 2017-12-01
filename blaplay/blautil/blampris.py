# blaplay, Copyright (C) 2013  Niklas Koep

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

import sys
import os

import dbus
import dbus.service
from dbus.exceptions import DBusException

import blaplay
from blaplay.blacore import blaconst
from blaplay import blautil
from blaplay.formats import _identifiers as tids

BUS_NAME = "org.mpris.MediaPlayer2.%s" % blaconst.APPNAME
OBJECT_PATH = "/org/mpris/MediaPlayer2"
INTERFACE_INTROSPECT = "org.freedesktop.DBus.Introspectable"
INTERFACE_BASE  = "org.mpris.MediaPlayer2"
INTERFACE_PLAYER = "%s.Player" % INTERFACE_BASE
# TODO: double-check the EmitsChangedSignal annotations
INTROSPECTION_DATA = """
<node name="/org/mpris/MediaPlayer2">
  <interface name="org.freedesktop.DBus.Introspectable">
    <method name="Introspect">
      <arg direction="out" name="xml_data" type="s"/>
    </method>
  </interface>
  <interface name="org.freedesktop.DBus.Properties">
    <method name="Get">
      <arg direction="in" name="interface_name" type="s"/>
      <arg direction="in" name="property_name" type="s"/>
      <arg direction="out" name="value" type="v"/>
    </method>
    <method name="GetAll">
      <arg direction="in" name="interface_name" type="s"/>
      <arg direction="out" name="properties" type="a{sv}"/>
    </method>
    <method name="Set">
      <arg direction="in" name="interface_name" type="s"/>
      <arg direction="in" name="property_name" type="s"/>
      <arg direction="in" name="value" type="v"/>
    </method>
    <signal name="PropertiesChanged">
      <arg name="interface_name" type="s"/>
      <arg name="changed_properties" type="a{sv}"/>
      <arg name="invalidated_properties" type="as"/>
    </signal>
  </interface>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/>
    <method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="Fullscreen" type="b" access="readwrite"/>
    <property name="CanSetFullscreen" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="DesktopEntry" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/>
    <method name="Previous"/>
    <method name="Pause"/>
    <method name="PlayPause"/>
    <method name="Stop"/>
    <method name="Play"/>
    <method name="Seek">
      <arg direction="in" name="Offset" type="x"/>
    </method>
    <method name="SetPosition">
      <arg direction="in" name="TrackId" type="o"/>
      <arg direction="in" name="Position" type="x"/>
    </method>
    <method name="OpenUri">
      <arg direction="in" name="Uri" type="s"/>
    </method>
    <signal name="Seeked">
      <arg name="Position" type="x"/>
    </signal>
    <property name="PlaybackStatus" type="s" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="LoopStatus" type="s" access="readwrite">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="Rate" type="d" access="readwrite">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="Shuffle" type="b" access="readwrite">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="Metadata" type="a{sv}" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="Volume" type="d" access="readwrite">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="false"/>
    </property>
    <property name="Position" type="x" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="false"/>
    </property>
    <property name="MinimumRate" type="d" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="MaximumRate" type="d" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="CanGoNext" type="b" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="CanGoPrevious" type="b" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="CanPlay" type="b" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="CanPause" type="b" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="CanSeek" type="b" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="CanControl" type="b" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="false"/>
    </property>
  </interface>
</node>""".strip()

def init(app):
    print_i("Initializing MPRIS2 interfaces")

    bus_name = dbus.service.BusName(name=BUS_NAME, bus=dbus.SessionBus())
    BlaMpris(app, object_path=OBJECT_PATH, bus_name=bus_name)

class BlaMpris(dbus.service.Object):
    def __init__(self, app, object_path, bus_name):
        dbus.service.Object.__init__(self, object_path=object_path,
                                     bus_name=bus_name)
        self._app = app

        # Define the properties for each interface. They are implemented with
        # callback functions to allow for easier handling of read-only and
        # read/write properties. In the latter case the callback function must
        # accept an optional argument which defaults to None. For simplicity,
        # the argument has to be called `value'.
        self.__properties = blautil.BlaFrozenDict({
            INTERFACE_BASE: blautil.BlaFrozenDict({
                "CanQuit": lambda: True,
                "CanRaise": lambda: True,
                "HasTrackList": lambda: False, # FIXME: not yet
                "Identity": lambda: blaconst.APPNAME,
                "DesktopEntry": self.__desktop_entry,
                # TODO: move this to blaconst?
                "SupportedUriSchemes": lambda: ["file", "http", "dvd"],
                "SupportedMimeTypes": self.__supported_mime_types
            }),
            INTERFACE_PLAYER: blautil.BlaFrozenDict({
                "PlaybackStatus": self._app.player.get_state_string,
                "LoopStatus": self.__loop_status,
                "Rate": lambda value=None: 1.0,
                "Shuffle": self.__shuffle,
                "Metadata": self.__metadata,
                "Volume": self.__volume,
                "Position": self.__position,
                "MinimumRate": lambda: 1.0,
                "MaximumRate": lambda: 1.0,
                "CanGoNext": lambda: True,
                "CanGoPrevious": lambda: True,
                "CanPlay": lambda: True,
                "CanPause": lambda: True,
                "CanSeek": lambda: True,
                "CanControl": lambda: True
            })
        })
        # Perform a very crude sanity check on the callback functions.
        import inspect
        def validate_callback(callback):
            argspec = inspect.getargspec(callback)
            # Check number of arguments. This will miss callbacks like
            # `def func(*args): ...' as the args property of argspec will be
            # an empty list.
            args = argspec.args
            if inspect.ismethod(callback):
                args = args[1:]
            n_args = len(args)
            if n_args > 1:
                raise ValueError("Property callback function must take 0 or 1 "
                                 "arguments at the most")
            if n_args == 1 and args[0] != "value":
                raise ValueError("Property callback function for a read/write "
                                 "property must accept an argument called "
                                 "`value'")
            # Check default arguments. If the callback supplies default
            # arguments it must only define one and the default value has to be
            # None.
            defaults = argspec.defaults
            if (defaults is not None and len(defaults) != 1 and
                len(defaults) != n_args and
                defaults[0] is not None):
                raise ValueError("Property callback functions for read/write "
                                 "properties must accept an optional argument "
                                 "that defaults to None")
        for interface_name, properties in self.__properties.items():
            map(validate_callback, properties.itervalues())

        # Propagate blaplay-specific events on the session bus which have an
        # appropriate analogon in the MPRIS2 specification.
        player = self._app.player
        def seeked(player, pos):
            self.Seeked(pos / 1000)
            return False
        player.connect("seeked", seeked)

        # TODO: Roll this into a generic callback.
        def emit_properties_changed_signal(player, property_name):
            value = self.Get(INTERFACE_PLAYER, property_name)
            self.PropertiesChanged(
                INTERFACE_PLAYER, {property_name: value}, [])
        player.connect("state-changed", emit_properties_changed_signal,
                       "PlaybackStatus")
        player.connect("track-changed", emit_properties_changed_signal,
                       "Metadata")

    def __get_interface_properties(self, interface_name):
        try:
            return self.__properties[interface_name]
        except KeyError:
            raise DBusException("Object %s does not implement interface %s" %
                                (OBJECT_PATH, interface_name))
        return {}

    # According to http://dbus.freedesktop.org/doc/dbus-specification.html the
    # following three methods are required for exporting properties on an
    # interface.
    @dbus.service.method(dbus_interface=dbus.PROPERTIES_IFACE,
                         in_signature="ss", out_signature="v")
    def Get(self, interface_name, property_name):
        interface_properties = self.__get_interface_properties(interface_name)
        try:
            value = interface_properties[property_name]()
        except KeyError:
            raise DBusException("Interface %s has no property %s" %
                                (interface_name, property_name))
        return value

    @dbus.service.method(dbus_interface=dbus.PROPERTIES_IFACE,
                         in_signature="ssv")
    def Set(self, interface_name, property_name, value):
        interface_properties = self.__get_interface_properties(interface_name)
        try:
            interface_properties[property_name](value=value)
        except KeyError:
            raise DBusException("Interface %s has no property %s" %
                                (interface_name, property_name))
        except TypeError:
            raise DBusException("Property %s of interface %s is read-only" %
                                (property_name, interface_name))
        # TODO: only emit this in case of success
        self.PropertiesChanged(interface_name, {property_name: value}, [])

    @dbus.service.method(dbus_interface=dbus.PROPERTIES_IFACE,
                         in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface_name):
        interface_properties = self.__get_interface_properties(interface_name)
        properties = {}
        for property_name, callback in interface_properties.items():
            properties[property_name] = callback()
        return properties

    # This is used to signal property changes. The method itself does not have
    # to implement anything.
    @dbus.service.signal(dbus_interface=dbus.PROPERTIES_IFACE,
                         signature="sa{sv}as")
    def PropertiesChanged(self, interface_name, changed_properties,
                          invalidated_properties):
        pass

    @dbus.service.method(dbus_interface=dbus.INTROSPECTABLE_IFACE)
    def Introspect(self):
        return INTROSPECTION_DATA

    # Implementation of the org.mpris.MediaPlayer2 interface
    # Methods
    @dbus.service.method(dbus_interface=INTERFACE_BASE)
    def Raise(self):
        self._app.window.raise_window()

    @dbus.service.method(dbus_interface=INTERFACE_BASE)
    def Quit(self):
        blaplay.shutdown()

    def __desktop_entry(self):
        import gio
        app_infos = gio.app_info_get_all()
        for app_info in app_infos:
            if app_info.get_name() == blaconst.APPNAME:
                return blautil.toss_extension(app_info.get_id())
        return ""

    def __supported_mime_types(self):
        # TODO: check the formats package for supported mimetypes
        return dbus.Array([], signature="s")

    # Implementation of the org.mpris.MediaPlayer2.Player interface
    # Methods
    @dbus.service.method(dbus_interface=INTERFACE_PLAYER)
    def Next(self):
        self._app.player.next()

    @dbus.service.method(dbus_interface=INTERFACE_PLAYER)
    def Previous(self):
        self._app.player.previous()

    @dbus.service.method(dbus_interface=INTERFACE_PLAYER)
    def Pause(self):
        self._app.player.pause()

    @dbus.service.method(dbus_interface=INTERFACE_PLAYER)
    def PlayPause(self):
        self._app.player.play_pause()

    @dbus.service.method(dbus_interface=INTERFACE_PLAYER)
    def Stop(self):
        self._app.player.stop()

    @dbus.service.method(dbus_interface=INTERFACE_PLAYER)
    def Play(self):
        self._app.player.play()

    @dbus.service.method(dbus_interface=INTERFACE_PLAYER,
                         in_signature="x")
    def Seek(self, offset):
        # BlaPlayer's seek() method expects an offset in nanoseconds while
        # the MPRIS2 specification defines offets in terms of microseconds.
        self._app.player.seek(
            self._app.player.get_position() + offset * 1000)

    @dbus.service.method(dbus_interface=INTERFACE_PLAYER, in_signature="ox")
    def SetPosition(self, track_id, offset):
        # TODO:
        # path = "/org/freedesktop/blaplay"
        # if track_id != dbus.ObjectPath(path + "/" + str()): pass
        if offset < 0 or track_id != "TODO: check if track_ids match":
            return
        self._app.player.seek(offset * 1000)

    @dbus.service.method(dbus_interface=INTERFACE_PLAYER, in_signature="s")
    def OpenUri(self, uri):
        # TODO:
        pass

    # Signals
    @dbus.service.signal(dbus_interface=INTERFACE_PLAYER, signature="x")
    def Seeked(self, position):
        pass

    # Properties
    def __loop_status(self, value=None):
        # Read value
        if value is None:
            order = self._app.config.getint("general", "play.order")
            if order == blaconst.ORDER_REPEAT:
                return "Track"
            elif order == blaconst.ORDER_SHUFFLE:
                return "Playlist"
            return "None"
        else:
            # TODO: export a method somewhere which changes the play order.
            #       better yet, let widgets listen for changes of the config
            #       and check if play.order changed.
            pass

    def __shuffle(self, value=None):
        # Read value
        if value is None:
            return (self._app.config.getint("general", "play.order") ==
                    blaconst.ORDER_SHUFFLE)
        else:
            # TODO: see __loop_status
            pass

    def __metadata(self):
        def Dictionary(d):
            return dbus.Dictionary(d, signature="sv")

        # TODO: determine the trackid from the unique identifier we use in the
        #       playlist. it isn't exported yet though
        player = self._app.player
        track = player.get_track()
        id_ = str(id(track)) if track is not None else "NoTrack"
        metadata = {
            "mpris:trackid": dbus.ObjectPath(
                "/org/freedesktop/blaplay/%s" % id_)
        }
        if track is None:
            return Dictionary(metadata)

        # Track length
        metadata["mpris:length"] = dbus.Int64(track[tids.LENGTH] * 1000 ** 2)

        # Cover art
        cover = track.get_cover_path()
        if cover is not None:
            metadata["mpris:artUrl"] = dbus.UTF8String("file://%s" % cover)

        # Single values
        for id_, key in [(tids.ALBUM, "album"), (tids.TITLE, "title")]:
            value = track[id_]
            if not value:
                continue
            metadata["xesam:%s" % key] = dbus.UTF8String(value)

        # Values which get marshaled as `as'
        pairs = [
            (tids.ALBUM_ARTIST, "albumArtist"), (tids.ARTIST, "artist"),
            (tids.COMPOSER, "composer"), (tids.GENRE, "genre")
        ]
        for id_, key in pairs:
            value = track[id_]
            if not value:
                continue
            metadata["xesam:%s" % key] = dbus.Array([dbus.UTF8String(value)],
                                                    signature="s")

        # TODO: asText (lyrics)
        # Disc and track number
        for id_, key in [(tids.DISC, "disc"), (tids.TRACK, "trackNumber")]:
            try:
                value = int(track[id_].split("/")[0])
            except ValueError:
                continue
            metadata["xesam:%s" % key] = dbus.Int32(value)

        # URL
        uri = track[tids.URI]
        metadata["xseam:url"] = dbus.UTF8String("file://%s" % uri)

        # Year
        year = track[tids.DATE].split("-")[0]
        if year:
            import time
            metadata["xesam:contentCreated"] = dbus.UTF8String(
                time.strftime("%Y-%m-%dT%H:%M:%S", time.strptime(year, "%Y")))

        return Dictionary(metadata)

    def __volume(self, value=None):
        player = self._app.player

        # Read value
        if value is None:
            return self._app.config.getfloat("player", "volume")
        else:
            player.set_volume(value)

    def __position(self):
        return self._app.player.get_position() / 1000
