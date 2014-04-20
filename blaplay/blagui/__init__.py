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
import gtk

from blaplay.blacore import blaconst

# DND constants
DND_LIBRARY, DND_PLAYLIST, DND_URIS = range(3)
DND_TARGETS = {
    DND_LIBRARY: ("tracks/library", gtk.TARGET_SAME_APP, DND_LIBRARY),
    DND_PLAYLIST: ("tracks/playlist", gtk.TARGET_SAME_APP, DND_PLAYLIST),
    DND_URIS: ("text/uri-list", 0, DND_URIS)
}


def _gtk_init():
    import pygtk
    pygtk.require("2.0")
    gtk.icon_theme_get_default().append_search_path(blaconst.ICONS_PATH)
    gtk.window_set_default_icon_name(blaconst.APPNAME)

def init(config, library, player):
    _gtk_init()

    # Create and populate the main window.
    from . import blamainwindow
    window = blamainwindow.create_window(config, library, player)

    return window

# TODO: Move these two functions to blaguiutil.
def get_accelerator_group(widget):
    toplevel = widget.get_toplevel()
    accel_groups = gtk.accel_groups_from_object(toplevel)
    if len(accel_groups) > 1:
        raise ValueError("Ambiguous accelerator group found for widget '%s'" %
                         widget)
    return accel_groups[-1]

def is_accel(event, accel):
    # Convenience function from Quod Libet to check for accelerator matches.
    if event.type != gtk.gdk.KEY_PRESS:
        return False

    # ctrl+shift+x gives us ctrl+shift+X and accelerator_parse returns
    # lowercase values for matching, so lowercase it if possible.
    keyval = event.keyval
    if not keyval & ~0xFF:
        keyval = ord(chr(keyval).lower())

    default_mod = gtk.accelerator_get_default_mod_mask()
    accel_keyval, accel_mod = gtk.accelerator_parse(accel)

    # If the accel contains non default modifiers matching will never work and
    # since no one should use them, complain.
    non_default = accel_mod & ~default_mod
    if non_default:
        print_w("Accelerator `%s' contains a non default modifier "
                "`%s'." % (accel, gtk.accelerator_name(0, non_default) or ""))

    # Remove everything except default modifiers and compare.
    return (accel_keyval, accel_mod) == (keyval, event.state & default_mod)

