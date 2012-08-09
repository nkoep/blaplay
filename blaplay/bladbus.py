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
import sys

import dbus
import dbus.service
import dbus.mainloop.glib
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

import blaplay
from blaplay import blaconst
from blaplay.formats._identifiers import *

SERVICE = "blub.bla.blaplayService"
INTERFACE = "blub.bla.blaplayInterface"


def setup_bus():
    blaplay.print_i("Setting up D-Bus")

    bus = dbus.SessionBus()
    bus_name = dbus.service.BusName(SERVICE, bus)
    BlaDBus(object_path="/BlaDBus", bus_name=bus_name)

# TODO: abstract this in a better way
def query_bus(query):
    try:
        bus = dbus.SessionBus()
        try: proxy = bus.get_object(SERVICE, "/BlaDBus")
        except: sys.exit()
        interface = dbus.Interface(proxy, INTERFACE)

        if type(query) == list:
            args = query[0].split("%")
            for idx, arg in enumerate(args):
                if arg != "": continue
                if (idx == len(args)-1 or
                        args[idx+1][0] not in ["a", "t", "b", "c"]):
                    blaplay.print_e("Invalid format string `%s'" % args)

            callbacks = {
                "%a": lambda: interface.get_standard_value(ARTIST),
                "%t": lambda: interface.get_standard_value(TITLE),
                "%b": lambda: interface.get_standard_value(ALBUM),
                "%c": lambda: interface.get_cover()
            }

            format = query[0]
            for key in callbacks.keys():
                if key in format:
                    format = format.replace(key, callbacks[key]())
            print format.encode("utf-8")

        else:
            if query == "play_pause": interface.play_pause()
            elif query == "stop": interface.stop()
            elif query == "next": interface.next()
            elif query == "previous": interface.previous()
            elif query == "raise_window": interface.raise_window()
    except: pass
    sys.exit()


class BlaDBus(dbus.service.Object):
    def __init__(self, **kwargs):
        dbus.service.Object.__init__(self, dbus.SessionBus(), **kwargs)
        from blaplay import blaplayer
        self.__player = blaplayer.player

    @dbus.service.method(dbus_interface=INTERFACE, in_signature="i",
            out_signature="s")
    def get_standard_value(self, value):
        track = self.__player.get_track()
        ret = ""
        if not track[value]:
            if value == ARTIST: ret = "?"
            elif value == TITLE: ret = os.path.basename(track.path)
            else: ret = ""
        else: ret = track[value]
        return ret

    @dbus.service.method(dbus_interface=INTERFACE, in_signature="",
            out_signature="s")
    def get_cover(self):
        track = self.__player.get_track()
        if track:
            cover = track.get_cover_basepath()
            if os.path.isfile("%s.jpg" % cover): return ("%s.jpg" % cover)
            elif os.path.isfile("%s.png" % cover): return ("%s.png" % cover)
        return ""

    @dbus.service.method(dbus_interface=INTERFACE, in_signature="",
            out_signature="")
    def play_pause(self):
        self.__player.play_pause()

    @dbus.service.method(dbus_interface=INTERFACE, in_signature="",
            out_signature="")
    def stop(self):
        self.__player.stop()

    @dbus.service.method(dbus_interface=INTERFACE, in_signature="",
            out_signature="")
    def next(self):
        self.__player.next()

    @dbus.service.method(dbus_interface=INTERFACE, in_signature="",
            out_signature="")
    def previous(self):
        self.__player.previous()

    @dbus.service.method(dbus_interface=INTERFACE, in_signature="",
            out_signature="")
    def raise_window(self):
        from blaplay import blagui
        blagui.bla.raise_window()

    @dbus.service.method(dbus_interface=INTERFACE, in_signature="as",
            out_signature="")
    def add_to_current_playlist(self, filenames):
        from blaplay.blagui.blaplaylist import BlaPlaylist
        BlaPlaylist.add_to_current_playlist("", filenames, resolve=True)

    @dbus.service.method(dbus_interface=INTERFACE, in_signature="as",
            out_signature="")
    def send_to_new_playlist(self, filenames):
        from blaplay.blagui.blaplaylist import BlaPlaylist
        BlaPlaylist.send_to_new_playlist("", filenames, resolve=True)
