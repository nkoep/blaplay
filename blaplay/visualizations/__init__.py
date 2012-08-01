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

import os

from blaplay import blautils

modules = {}


def init():
    # pretty much the same deal as with audio formats except constants in
    # blaconst are used to look up visualization elements

    def f(s): return not (s.endswith("pyc") or s.startswith("_"))
    _modules = filter(f, os.listdir(os.path.dirname(__file__)))
    for module in map(blautils.toss_extension, _modules):
        vis = module.capitalize()
        module = __import__("blaplay.visualizations.%s" % module, {}, {}, vis)
        vis = getattr(module, vis)
        modules[vis.identifier] = vis

