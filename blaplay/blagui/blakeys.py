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

try: import mmkeys
except ImportError: from blaplay import _mmkeys as mmkeys

from blaplay import blaplayer
player = blaplayer.player


class BlaKeys(object):
    def __init__(self):
        try: self.__keys = mmkeys.MmKeys()
        except NameError: return

        keys = [
            ("mm_playpause", lambda *x: player.play_pause()),
            ("mm_stop", lambda *x: player.stop()),
            ("mm_prev", lambda *x: player.previous()),
            ("mm_next", lambda *x: player.next())
        ]
        map(lambda k: self.__keys.connect(*k), keys)

