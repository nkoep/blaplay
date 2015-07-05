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


class BlaKeys(gobject.GObject):
    def __init__(self, config, player):
        if not self.can_bind():
            return

        self._config = config

        self._actions = {
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
        for action in self._actions.keys():
            accel = config.getstring("keybindings", action)
            if accel:
                self.bind(action, accel)

    def can_bind(self):
        return keybinder is not None

    def bind(self, action, accel):
        if self.can_bind():
            self.unbind(self._config.getstring("keybindings", action))
            return keybinder.bind(accel, self._actions[action], None)
        return False

    def unbind(self, accel):
        if self.can_bind():
            try:
                keybinder.unbind(accel)
            except KeyError:
                pass

