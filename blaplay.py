#!/usr/bin/env python2
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

import blaplay


blaplay.init(__file__)

if __name__ == "__main__":
    from blaplay import blacfg, bladb, blaplayer, blagui

    # initialize the config
    blacfg.init()

    # initialize the database
    bladb.init()

    # create an instance of the playback device
    blaplayer.init()

    # initialize the GUI
    blagui.init()

    # finalize blaplay start-up and start the event loop
    blaplay.finalize()

