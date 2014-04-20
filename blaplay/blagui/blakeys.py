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

import gobject
try:
    import keybinder
except ImportError:
    keybinder = None

import blaplay
player = blaplay.bla.player
from blaplay.blacore import blacfg


class BlaKeys(gobject.GObject):
    __ACTIONS = {
        "playpause": lambda *x: player.play_pause(),
        "pause": lambda *x: player.pause(),
        "stop": lambda *x: player.stop(),
        "previous": lambda *x: player.previous(),
        "next": lambda *x: player.next(),
        # TODO: Add a proper API for these to the BlaPlayer class.
        "volup": lambda *x: False,
        "voldown": lambda *x: False,
        "mute": lambda *x: False
    }

    def __init__(self):
        if not self.can_bind():
            return

        for action in self.__ACTIONS.iterkeys():
            accel = blacfg.getstring("keybindings", action)
            if accel:
                self.bind(action, accel)

    def can_bind(self):
        return keybinder is not None

    def bind(self, action, accel):
        self.unbind(accel)
        return keybinder.bind(accel, self.__ACTIONS[action], None)

    def unbind(self, accel):
        try:
            keybinder.unbind(accel)
        except KeyError:
            pass

