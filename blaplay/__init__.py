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
from blaplay import blautil


class Blaplay(gobject.GObject):
    __metaclass__ = blautil.BlaSingletonMeta
    __slots__ = ("_pre_shutdown_hooks", "library", "player", "window")

    __gsignals__ = {
        "startup_complete": blautil.signal(0)
    }

    def __init__(self):
        super(Blaplay, self).__init__()
        self.library = self.player = self.window = None
        self._pre_shutdown_hooks = []

    def __setattr__(self, attr, value):
        # The attributes for this class are frozen. That is, we only allow the
        # assignment to attributes named in __slots__. However, we additionally
        # make sure no one reassigns to one of the allowed fields here.
        if hasattr(self, attr) and getattr(self, attr) is not None:
            raise ValueError("Attribute '%s' already has a value" % attr)
        return super(Blaplay, self).__setattr__(attr, value)

    def main(self):
        def map_event(window, event):
            self.emit("startup_complete")
            self.window.disconnect(cid)
        cid = self.window.connect("map_event", map_event)
        gobject.idle_add(self.window.show)
        print_d("Entering the main loop")
        gtk.main()

    def add_pre_shutdown_hook(self, hook):
        self._pre_shutdown_hooks.append(hook)

    def shutdown(self):
        print_d("Shutting down %s..." % blaconst.APPNAME)

        # Stop playback. It is important to do this before destroying the main
        # window as we otherwise might end up with an invalid xid we told
        # gstreamer to use for video rendering.
        try:
            self.player.stop()
        except AttributeError:
            pass

        # FIXME: this is our gateway routine for shutting down blaplay, i.e.
        #        shutdown always starts here. just calling the kill_threads
        #        classmethod isn't enough to actually stop the threads. we also
        #        need to join them. otherwise interpreter shutdown might be
        #        initiated after leaving this function with threads still running.
        #        occasionally, these wake up to find their containing module's
        #        globals() dict wiped clean and start spitting out exceptions +
        #        segfaults.
        from blaplay import blautil
        blautil.BlaThread.kill_threads()

        for hook in self._pre_shutdown_hooks:
            print_d("Calling pre-shutdown hook '%s.%s'" %
                    (hook.__module__, hook.__name__))
            hook()

        from blaplay.blagui import blaguiutils
        # TODO: destroy all additional windows instead of just hiding them.
        #       windows from which dialogs were run (which have their own event
        #       loops) will cause segfaults otherwise. would it be enough to
        #       parent every other window to self.window?
        blaguiutils.set_visible(False)

        # Get rid of the main window.
        try:
            self.window.destroy_()
        except AttributeError:
            pass

        from blaplay.blacore import blacfg
        blacfg.save()

        print_d("Stopping the main loop")
        gtk.main_quit()

bla = Blaplay()


def finish_startup():
    from blaplay.blacore import blacfg, bladb

    # Initialize the config.
    blacfg.init()

    # Initialize the library.
    library = bla.library = bladb.init(blaconst.LIBRARY_PATH, blacfg)

    # Create an instance of the playback device.
    from blaplay.blacore import blaplayer
    bla.player = blaplayer.init(library)

    # Initialize the GUI.
    from blaplay import blagui
    bla.window = blagui.init(library)

    from blaplay.blagui import blakeys
    blakeys.BlaKeys()

    # Set up the D-Bus interface.
    try:
        from blaplay.blautil import bladbus
    except ImportError:
        # If the DBUS module isn't available we just define a class which acts
        # on behalf of the module, issuing warnings whenever it's used.
        class bladbus:
            @classmethod
            def __warning(cls, exit):
                print_w("Failed to import dbus module. Install dbus-python.")
                if exit:
                    raise SystemExit

            @classmethod
            def setup_bus(cls, *args):
                cls.__warning(False)

            @classmethod
            def query_bus(cls, *args):
                cls.__warning(True)

    bladbus.setup_bus()

    # Initialize MPRIS2 module.
    try:
        from blaplay.blautil import blampris
    except ImportError:
        pass
    else:
        blampris.init()

    # Initialize last.fm services.
    from blaplay.blautil import blafm
    blafm.init(library)

    # Initialize metadata module.
    from blaplay.blautil import blametadata
    blametadata.init()

    # Set process name for programs like top or gnome-system-monitor.
    gobject.set_prgname(blaconst.APPNAME)
    # 15 == PR_SET_NAME
    blautil.cdll("c").prctl(15, blaconst.APPNAME, 0, 0, 0)

    # Finally, start the main loop.
    bla.main()

def shutdown():
    bla.shutdown()

