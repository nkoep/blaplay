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

import gobject
import gtk
import cairo
import pango

import blaplay
player = blaplay.bla.player
from blaplay.blacore import blaconst, blacfg
from blaplay import blautil, blagui
from blaplay.formats._identifiers import *
from blawindows import BlaScrolledWindow
from blatagedit import BlaTagEditor, BlaProperties
from blastatusbar import BlaStatusbar
from blaplay.blautil import blametadata
import blaguiutils


def set_view(view):
    BlaView().set_view(view)

def BlaViewMeta(view_name):
    class _BlaViewMeta(blautil.BlaSingletonMeta):
        def __new__(cls, name, bases, dct):
            # Make sure at least one baseclass inherits from gobject.GObject.
            if not any([issubclass(base, gobject.GObject) for base in bases]):
                raise TypeError("%s does not inherit from gobject.GObject" %
                                name)

            # Add the view_name property.
            if "view_name" in dct:
                raise ValueError("View class %s already defines an attribute "
                                 "'view_name'" % name)
            dct["view_name"] = property(lambda self: view_name)

            # Add the init-function stub.
            if "init" not in dct:
                dct["init"] = lambda self: None

            # Add default behavior for `update_statusbar()'.
            if "update_statusbar" not in dct:
                dct["update_statusbar"] = lambda s: BlaStatusbar.set_view_info(
                    blacfg.getint("general", "view"), "")

            return super(_BlaViewMeta, cls).__new__(cls, name, bases, dct)

    return _BlaViewMeta


class BlaView(gtk.Viewport):
    __metaclass__ = blautil.BlaSingletonMeta

    def __init__(self, views):
        super(BlaView, self).__init__()
        self.set_shadow_type(gtk.SHADOW_NONE)

        self._views = views
        for view in self._views:
            view.init()

        def startup_complete(*args):
            self.set_view(blacfg.getint("general", "view"))
        blaplay.bla.connect("startup_complete", startup_complete)

        self.show_all()

    def set_view(self, view):
        view_prev = blacfg.getint("general", "view")
        blacfg.set_("general", "view", view)

        child = self.get_child()
        if view == view_prev and child is not None:
            return
        if child is not None:
            self.remove(child)
        child = self._views[view]
        if child.get_parent() is not None:
            child.unparent()
        self.add(child)
        child.update_statusbar()

    @staticmethod
    def create_view_manager():
        from blaplaylist import playlist_manager
        from blaqueue import queue
        return BlaView([playlist_manager, queue])

