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

from blaplay import blautil

modules = {}


def init():
    def f(s): return not (s.endswith("pyc") or s.startswith("_"))
    _modules = filter(f, os.listdir(os.path.dirname(__file__)))
    for module in _modules:
        basename = blautil.toss_extension(module)
        vis = basename.capitalize()
        try:
            module = __import__(
                    "blaplay.visualizations.%s" % basename, {}, {}, vis)
        except Exception as e:
            print_i("Failed to import module \"%s\": %r" % (module, e))
            continue
        vis = getattr(module, vis)
        modules[vis.identifier] = vis

