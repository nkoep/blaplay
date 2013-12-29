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

formats = {}


class TagParseError(Exception):
    pass


def get_track(path):
    ext = blautil.get_extension(path).lower()
    try:
        track = formats[ext](path)
    except (KeyError, TagParseError):
        track = None
    return track

def _is_py_file(s):
    # TODO: move this to blautil since we also use it for visualizations
    return not (s.endswith("pyc") or s.startswith("_"))

def _check_module_integrity(module, name):
    try:
        format_ = getattr(module, name)
        extensions = format_.extensions
        # TODO: use the iter() built-in to check iterability
        if not hasattr(extensions, "__iter__"):
            raise AttributeError
        # TODO: check if these are callable
        for attr in ["_read_tags", "_save"]:
            if not hasattr(format_, attr):
                raise AttributeError
    except AttributeError as exc:
        print_d("Failed to initialize \"%s\" visualization: %s" %
                (identifier, exc))
        return None
    return format_

# Every module name in the formats package except those defining a format start
# with an underscore. We filter module sources by this. Everything that passes
# is treated like a format. Format classes have the same name as the module
# name, but with capitalized first letter.
# FIXME: some distributions might not install the py-files. to avoid being
#        overly specific when it comes to extensions just filter out every file
#        which starts with an underscore, put all passed names into a set() and
#        iterate over this instead
for module in filter(_is_py_file, os.listdir(os.path.dirname(__file__))):
    basename = blautil.toss_extension(module)
    name = basename.capitalize()

    try:
        module = __import__(
            "blaplay.formats.%s" % basename, {}, {}, name)
        format_ = getattr(module, name)
    except Exception as exc:
        print_d("Failed to import module \"%s\": %r" % (module, exc))
    else:
        format_ = _check_module_integrity(module, name)
        if format_:
            for ext in format_.extensions:
                # FIXME: with the addition of video support we overwrite
                #        certain extension handlers here, e.g. mp4
                formats[ext] = format_

del _is_py_file
del _check_module_integrity

