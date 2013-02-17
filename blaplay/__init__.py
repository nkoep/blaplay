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

import gobject
import gtk

from blaplay.blacore import blaconst

cli_queue = None


class Blaplay(object):
    # class instances which need to shut down gracefully and preferably before
    # the user interface has been destroyed can register themselves via the
    # "register_for_cleanup" method. classes that do so need to implement the
    # __call__ method as their cleanup routine

    __cleanup = []

    def __init__(self):
        self.library = self.player = self.window = None

    def main(self):
        gobject.idle_add(self.window.show)
        gtk.main()

    def register_for_cleanup(self, instance):
        self.__cleanup.append(instance)

    def shutdown(self):
        for instance in self.__cleanup:
            print_d("Calling shutdown routine for %s"
                    % instance.__class__.__name__)
            instance()

bla = Blaplay()


def finish_startup():
    from blaplay.blacore import blacfg, bladb
    from blaplay import blautil

    # initialize the config
    blacfg.init()

    # initialize the database
    bla.library = bladb.init()

    # create an instance of the playback device
    from blaplay.blacore import blaplayer
    bla.player = blaplayer.init()

    # initialize the GUI
    from blaplay import blagui
    bla.window = blagui.init()
    bla.window.connect("destroy", shutdown)

    # set up the D-Bus interface and last.fm services
    try: from blaplay.blautil import bladbus
    except ImportError:
        # if the dbus module isn't available we just define a class which acts
        # on behalf of the module, issuing warnings whenever it's used
        class bladbus:
            @classmethod
            def __warning(cls, exit):
                print_w("Failed to import dbus module. Install dbus-python.")
                if exit: raise SystemExit
            @classmethod
            def setup_bus(cls, *args): cls.__warning(False)
            @classmethod
            def query_bus(cls, *args): cls.__warning(True)
    bladbus.setup_bus()

    # initialize the scrobbler
    from blaplay.blautil import blafm
    blafm.init()

    # initialize metadata module
    from blaplay.blautil import blametadata
    blametadata.init()

    # set process name for programs like top or gnome-system-monitor
    import ctypes
    import ctypes.util

    gobject.set_prgname(blaconst.APPNAME)
    try:
        soname = ctypes.util.find_library("c")
        # 15 == PR_SET_NAME
        ctypes.CDLL(soname).prctl(15, blaconst.APPNAME, 0, 0, 0)
    except AttributeError: pass

    # update the config on disk from time to time
    gobject.timeout_add(blaconst.CFG_TIMEOUT * 60 * 1000, blacfg.save, False)

    # start the main loop
    bla.main()

def shutdown(window):
    print_d("Shutting down...")

    bla.player.stop()

    from blaplay import blautil
    blautil.BlaThread.kill_threads()

    bla.shutdown()

    from blaplay.blacore import blacfg
    blacfg.save()

    print_d("Stopping event loop")
    gtk.main_quit()

