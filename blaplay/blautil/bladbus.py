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

# XXX: Remove this and add appropriate wrapper functions to supply the previous
#      functionality on top of blampris.

import sys
import os

import dbus.service
import dbus.mainloop.glib
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

# FIXME: Since we started using the gst module in the formats package importing
#        this here also imports gst which slows down startup if we only want to
#        query the state of a running blaplay instance.
from blaplay.formats import _identifiers as tids

# We use the same bus and interface name for now.
INTERFACE = "org.freedesktop.blaplay"
OBJECT_PATH = "/%s/BlaDBus" % INTERFACE.replace(".", "/")


def init(app):
    print_i("Setting up D-Bus")
    bus_name = dbus.service.BusName(INTERFACE, dbus.SessionBus())
    BlaDBus(app, object_path=OBJECT_PATH, bus_name=bus_name)

def query_bus(query, arg=None):
    # Get a proxy to the bus object of the running blaplay instance.
    try:
        proxy = dbus.SessionBus().get_object(INTERFACE, OBJECT_PATH)
    except dbus.DBusException:
        raise SystemExit

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
            "%a": lambda: interface.get_tag(tids.ARTIST),
            "%t": lambda: interface.get_tag(tids.TITLE),
            "%b": lambda: interface.get_tag(tids.ALBUM),
            "%y": lambda: interface.get_tag(tids.DATE),
            "%g": lambda: interface.get_tag(tids.GENRE),
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

    raise SystemExit


class BlaDBus(dbus.service.Object):
    def __init__(self, app, **kwargs):
        dbus.service.Object.__init__(self, dbus.SessionBus(), **kwargs)
        self._app = app

    @dbus.service.method(
        dbus_interface=INTERFACE, in_signature="i", out_signature="s")
    def get_tag(self, identifier):
        # FIXME: check if track is None
        track = self._app.player.get_track()
        ret = track[identifier]
        if not ret:
            if identifier == tids.ARTIST:
                ret = "?"
            elif identifier == tids.TITLE:
                ret = os.path.basename(track.uri)
            else:
                ret = ""
        return str(ret)

    @dbus.service.method(
        dbus_interface=INTERFACE, in_signature="", out_signature="s")
    def get_cover(self):
        track = self._app.player.get_track()
        if track:
            cover = track.get_cover_path()
            if cover is not None:
                return cover
        return ""

    @dbus.service.method(
        dbus_interface=INTERFACE, in_signature="", out_signature="")
    def play_pause(self):
        self._app.player.play_pause()

    @dbus.service.method(
        dbus_interface=INTERFACE, in_signature="", out_signature="")
    def stop(self):
        self._app.player.stop()

    @dbus.service.method(
        dbus_interface=INTERFACE, in_signature="", out_signature="")
    def next(self):
        self._app.player.next()

    @dbus.service.method(
        dbus_interface=INTERFACE, in_signature="", out_signature="")
    def previous(self):
        self._app.player.previous()

    @dbus.service.method(
        dbus_interface=INTERFACE, in_signature="", out_signature="")
    def raise_window(self):
        self._bla.window.raise_window()

    @dbus.service.method(
        dbus_interface=INTERFACE, in_signature="sas", out_signature="")
    def parse_uris(self, action, uris):
        print_w("TODO")

