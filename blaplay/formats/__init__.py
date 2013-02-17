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

formats = {}


def init():
    # every module name in the formats package except those defining formats
    # start with an underscore. we filter module sources by this. everything
    # that passes is a format. format classes have the same name as the module
    # name, only with capitalized first letter

    def f(s): return not (s.endswith("pyc") or s.startswith("_"))
    modules = filter(f, os.listdir(os.path.dirname(__file__)))
    for module in map(blautil.toss_extension, modules):
        format = module.capitalize()
        module = __import__("blaplay.formats.%s" % module, {}, {}, format)
        format = getattr(module, format)
        for ext in format.extensions: formats[ext] = format

def get_track(path):
    ext = blautil.get_extension(path).lower()
    try: track = formats[ext](path)
    except (KeyError, TagParseError): track = None
    return track


class TagParseError(Exception): pass

