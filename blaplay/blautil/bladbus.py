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

import sys
import os

import dbus
import dbus.service
import dbus.mainloop.glib
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

# We use the same bus and interface name for now.
INTERFACE = "org.freedesktop.blaplay"
OBJECT_PATH = "/%s/BlaDBus" % INTERFACE.replace(".", "/")


def setup_bus():
    print_i("Setting up D-Bus")

    bus_name = dbus.service.BusName(INTERFACE, dbus.SessionBus())
    BlaDBus(object_path=OBJECT_PATH, bus_name=bus_name)

def query_bus(query, arg=None):
    # FIXME: do this properly once we comply to MPRIS 2.2
    from blaplay.formats._identifiers import ARTIST, TITLE, ALBUM, DATE, GENRE

    # Get a proxy to the bus object of the running blaplay instance.
    try:
        proxy = dbus.SessionBus().get_object(INTERFACE, OBJECT_PATH)
    except dbus.DBusException:
        sys.exit()

    # Get an interface to the proxy. This offers direct access to methods
    # exposed through the interface.
    interface = dbus.Interface(proxy, INTERFACE)

    if isinstance(query, list):
        args = query[0].split("%")
        for idx, arg in enumerate(args):
            if arg != "":
                continue
            if (idx == len(args)-1 or
                args[idx+1][0] not in ["a", "t", "b", "y", "g", "c"]):
                print_e("Invalid format string `%s'" % args)

        callbacks = {
            "%a": lambda: interface.get_tag(ARTIST),
            "%t": lambda: interface.get_tag(TITLE),
            "%b": lambda: interface.get_tag(ALBUM),
            "%y": lambda: interface.get_tag(DATE),
            "%g": lambda: interface.get_tag(GENRE),
            "%c": lambda: interface.get_cover()
        }

        format_ = query[0]
        for key in callbacks.iterkeys():
            if key in format_:
                format_ = format_.replace(key, callbacks[key]())
        sys.stdout.write("%s\n" % format_.encode("utf-8"))

    else:
        if query == "play_pause":
            interface.play_pause()
        elif query == "stop":
            interface.stop()
        elif query == "next":
            interface.next()
        elif query == "previous":
            interface.previous()
        elif query == "raise_window":
            interface.raise_window()
        elif query in ["append", "new", "replace"] and arg:
            interface.parse_uris(query, arg)

    sys.exit()


class BlaDBus(dbus.service.Object):
    def __init__(self, **kwargs):
        dbus.service.Object.__init__(self, dbus.SessionBus(), **kwargs)
        import blaplay
        self.__player = blaplay.bla.player

    @dbus.service.method(
        dbus_interface=INTERFACE, in_signature="i", out_signature="s")
    def get_tag(self, identifier):
        from blaplay.formats._identifiers import ARTIST, TITLE

        track = self.__player.get_track()
        ret = track[identifier]
        if not ret:
            if identifier == ARTIST:
                if self.__player.radio:
                    ret = track["organization"]
                else:
                    ret = "?"
            elif identifier == TITLE:
                ret = os.path.basename(track.uri)
            else:
                ret = ""
        return str(ret)

    @dbus.service.method(
        dbus_interface=INTERFACE, in_signature="", out_signature="s")
    def get_cover(self):
        track = self.__player.get_track()
        if track:
            cover = track.get_cover_basepath()
            if os.path.isfile("%s.jpg" % cover):
                return ("%s.jpg" % cover)
            elif os.path.isfile("%s.png" % cover):
                return ("%s.png" % cover)
        return ""

    @dbus.service.method(
        dbus_interface=INTERFACE, in_signature="", out_signature="")
    def play_pause(self):
        self.__player.play_pause()

    @dbus.service.method(
        dbus_interface=INTERFACE, in_signature="", out_signature="")
    def stop(self):
        self.__player.stop()

    @dbus.service.method(
        dbus_interface=INTERFACE, in_signature="", out_signature="")
    def next(self):
        self.__player.next()

    @dbus.service.method(
        dbus_interface=INTERFACE, in_signature="", out_signature="")
    def previous(self):
        self.__player.previous()

    @dbus.service.method(
        dbus_interface=INTERFACE, in_signature="", out_signature="")
    def raise_window(self):
        import blaplay
        blaplay.bla.window.raise_window()

    @dbus.service.method(
        dbus_interface=INTERFACE, in_signature="sas", out_signature="")
    def parse_uris(self, action, uris):
        # TODO: do this via pipe
        from blaplay.blagui.blaplaylist import BlaPlaylistManager
        if action == "append":
            BlaPlaylistManager.add_to_current_playlist(uris, resolve=True)
        elif action == "new":
            BlaPlaylistManager.send_to_new_playlist(uris, resolve=True)
        else:
            f = BlaPlaylistManager.send_to_current_playlist(uris, resolve=True)

