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
    __slots__ = "_pre_shutdown_hooks config library player window".split()

    def __init__(self):
        super(Blaplay, self).__init__()
        self._pre_shutdown_hooks = []
        self.config = self.library = self.player = self.window = None

    def __setattr__(self, attr, value):
        # The attributes for this class are frozen. That is, we only allow the
        # assignment to attributes named in __slots__. However, we additionally
        # make sure no one reassigns to one of the allowed fields here.
        if hasattr(self, attr) and getattr(self, attr) is not None:
            raise ValueError("Attribute '%s' already has a value" % attr)
        return super(Blaplay, self).__setattr__(attr, value)

    def run(self):
        gobject.idle_add(self.window.show)
        print_d("Starting the main loop")
        gtk.main()

    # TODO: Replace the hook system by simply emitting a `shutdown` signal by
    #       this object, and letting the default signal handler do what's
    #       currently done in `Blaplay.shutdown`.
    def _hook_repr(self, hook):
        return "{:s}.{:s}".format(hook.__module__, hook.__name__)

    def add_pre_shutdown_hook(self, hook):
        # TODO: Implement a `Hook` class for this.
        if callable(hook):
            self._pre_shutdown_hooks.append(hook)
        else:
            print_w("Shutdown hook '{:s}' ignored as it isn't callable".format(
                self._hook_repr(hook)))

    def shutdown(self):
        print_d("Shutting down %s..." % blaconst.APPNAME)

        # Stop playback. It is important to do this before destroying the main
        # window as we otherwise might end up with an invalid xid we told
        # gstreamer to use for video rendering.
        try:
            self.player.stop()
        except AttributeError:
            pass

        # FIXME: This is our gateway routine for shutting down blaplay, i.e.
        #        shutdown always starts here. Just calling the kill_threads
        #        classmethod isn't enough to actually stop the threads. We also
        #        need to join them. Otherwise, an interpreter shutdown might be
        #        initiated after leaving this function with threads still
        #        running. Occasionally, these wake up to find their containing
        #        module's globals() dict wiped clean and start spitting out
        #        exceptions or even segfaults.
        blautil.BlaThread.kill_threads()

        for hook in self._pre_shutdown_hooks:
            print_d("Calling pre-shutdown hook '{:s}'".format(
                self._hook_repr(hook)))
            hook()

        from blaplay.blagui import blaguiutil
        # TODO: destroy all additional windows instead of just hiding them.
        #       windows from which dialogs were run (which have their own event
        #       loops) will cause segfaults otherwise. would it be enough to
        #       parent every other window to self.window?
        blaguiutil.set_visible(False)

        from blaplay.blacore import blacfg
        blacfg.save()

        print_d("Stopping the main loop")
        gtk.main_quit()

# TODO: Remove this global instance once it's accessed from nowhere else
#       anymore.
app = Blaplay()
# XXX: This is only here for compatibility for now.
bla = app


def finish_startup():
    from blaplay.blacore import blacfg, bladb

    # Initialize the config.
    # config = app_state.config = blacfg.init(blaconst.CONFIG_PATH)
    config = app.config = blacfg

    # Initialize the library.
    library = app.library = bladb.init(config, blaconst.LIBRARY_PATH)

    # Create an instance of the playback device.
    from blaplay.blacore import blaplayer
    player = app.player = blaplayer.init(library)

    # Initialize the GUI.
    from blaplay import blagui
    app.window = blagui.init(config, library, player)

    from blaplay.blagui import blakeys
    blakeys.BlaKeys()

    # TODO: Make python2-dbus a hard dependency so we can drop this mock
    #       module.
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
    else:
        bladbus.init(app)

    # Initialize MPRIS2 module.
    try:
        from blaplay.blautil import blampris
    except ImportError:
        pass
    else:
        blampris.init(app)

    # Initialize last.fm services.
    from blaplay.blautil import blafm
    blafm.init(library, player)

    # Initialize the metadata module.
    from blaplay.blautil import blametadata
    blametadata.init()

    # Set the process name for programs like top or gnome-system-monitor.
    gobject.set_prgname(blaconst.APPNAME)
    # From linux/prctl.h: 15 == PR_SET_NAME
    blautil.cdll("c").prctl(15, blaconst.APPNAME, 0, 0, 0)

    # Finally, start the main loop.
    app.run()

def shutdown():
    app.shutdown()

