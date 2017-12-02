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

try:
    import dbus
except ImportError:
    die("Python 2 DBus module is missing")
import dbus.service
import dbus.mainloop.glib
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

# We use the same bus and interface name for now.
INTERFACE = "org.freedesktop.blaplay"
OBJECT_PATH = "/%s/BlaDBus" % INTERFACE.replace(".", "/")


def init(app):
    print_i("Setting up D-Bus")
    bus_name = dbus.service.BusName(INTERFACE, dbus.SessionBus())
    BlaDBus(app, object_path=OBJECT_PATH, bus_name=bus_name)


def get_interface():
    # Get a proxy to the bus object of the running blaplay instance.
    try:
        proxy = dbus.SessionBus().get_object(INTERFACE, OBJECT_PATH)
    except dbus.DBusException:
        return None
    # Get an interface to the proxy. This offers direct access to
    # methods exposed through the interface.
    return dbus.Interface(proxy, INTERFACE)


class BlaDBus(dbus.service.Object):
    def __init__(self, app, **kwargs):
        dbus.service.Object.__init__(self, dbus.SessionBus(), **kwargs)
        self._app = app

    @dbus.service.method(
        dbus_interface=INTERFACE, in_signature="", out_signature="")
    def raise_window(self):
        self._app.window.raise_window()

    @dbus.service.method(
        dbus_interface=INTERFACE, in_signature="sas", out_signature="")
    def handle_uris(self, action, uris):
        if action == "append":
            self._append_uris_to_current_playlist(uris)
        elif action == "new":
            self._send_uris_to_new_playlist(uris)
        elif action == "replace":
            self._send_uris_to_current_playlist(uris)
        else:
            assert False, "invalid operation"

    def _append_uris_to_current_playlist(self, uris):
        print_w("TODO")

    def _send_uris_to_new_playlist(self, uris):
        print_w("TODO")

    def _send_uris_to_current_playlist(self, uris):
        print_w("TODO")
