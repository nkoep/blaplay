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

import sys
import os

import gobject
import gtk

from blaplay.blacore import blaconst

blacfg = None
bladbus = None
metadata = {"bio": {}, "lyrics": {}}
cli_queue = None


class Blaplay(object):
    # class instances which need to shut down gracefully and preferable before
    # the user interface has been destroyed can register themselves via the
    # "register_for_cleanup" method. classes that do so need to implement
    # __call__ as their cleanup routine

    __cleanup = dict()

    def __init__(self):
        self.library = self.player = self.window = None

    def main(self):
        gobject.idle_add(self.window.show)
        gtk.main()

    def register_for_cleanup(self, instance):
        self.__cleanup[instance.__class__.__name__] = instance

    def shutdown(self):
        for class_name, instance in self.__cleanup.items():
            print_d("Calling shutdown routine for %s" % class_name)
            instance()

bla = Blaplay()


def finalize():
    gobject.threads_init()

    global blacfg

    from blaplay.blacore import blacfg, bladb

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
    global bladbus
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




    # TODO: move this to blametadata.py
    # get cached metadata
    from blaplay import blautil
    global metadata
    _metadata = blautil.deserialize_from_file(blaconst.METADATA_PATH)
    if _metadata: metadata = _metadata





    # set process name for programs like top or gnome-system-monitor
    import ctypes
    import ctypes.util

    gobject.set_prgname(blaconst.APPNAME)
    try:
        soname = ctypes.util.find_library("c")
        # 15 == PR_SET_NAME
        ctypes.CDLL(soname).prctl(15, blaconst.APPNAME, 0, 0, 0)
    except AttributeError: pass

    # write config to disk every 10 minutes
    gobject.timeout_add(10 * 60 * 1000, blacfg.save, False)

    # start the main loop
    bla.main()

def shutdown(window):
    print_d("Shutting down...")

    bla.player.stop()
    bla.shutdown()

    # TODO: do we have to call gtk.Window.destroy(window) here?

    from blaplay import blautil
    blautil.BlaThread.clean_up()
    save_metadata()
    blacfg.save()

    # process remaining events manually before calling gtk.main_quit
    while False and gtk.events_pending():
        if gtk.main_iteration(False): break
    else: gtk.main_quit()







def add_metadata(section, key, value):
    global metadata
    metadata[section][key] = value

def get_metadata(section, key):
    try: return metadata[section][key]
    except KeyError: return None

def save_metadata():
    blautil.serialize_to_file(metadata, blaconst.METADATA_PATH)

