# blaplay, Copyright (C) 2013  Niklas Koep

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

import blaconst

# FIXME: this module will get imported even if we won't finish the startup,
#        e.g. blaplay is already running.

try:
    import pygst
    try:
        pygst.require(blaconst.GST_REQUIRED_VERSION)
    except pygst.RequiredVersionError:
        raise ImportError
    from gst import *
    import gst.pbutils as pbutils
except ImportError:
    class gst(object):
        class ElementNotFoundError(Exception):
            pass

        @classmethod
        def element_factory_find(cls, element):
            return None

        @classmethod
        def element_factory_make(cls, element):
            raise gst.ElementNotFoundError

