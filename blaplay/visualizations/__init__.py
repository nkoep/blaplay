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

from blaplay import blautil

modules = {}


def _is_py_file(s):
    return not (s.endswith("pyc") or s.startswith("_"))

def _check_module_integrity(module, name):
    try:
        vis = getattr(module, name)
        identifier = vis.identifier
        for method in ["set_width", "new_buffer", "consume_buffer",
                       "flush_buffers", "draw"]:
            method = getattr(vis, method)
            if not callable(method):
                raise AttributeError
        if not hasattr(vis, "height"):
            raise AttributeError
    except AttributeError as exc:
        print_d("Failed to initialize \"%s\" visualization: %s" %
                (identifier, exc))
        return None
    return vis

for module in filter(_is_py_file, os.listdir(os.path.dirname(__file__))):
    basename = blautil.toss_extension(module)
    name = basename.capitalize()
    try:
        module = __import__(
            "blaplay.visualizations.%s" % basename, {}, {}, name)
    except Exception as exc:
        print_d("Failed to import module \"%s\": %r" % (module, exc))
    else:
        vis = _check_module_integrity(module, name)
        if vis:
            modules[vis.identifier] = vis

del _is_py_file
del _check_module_integrity

