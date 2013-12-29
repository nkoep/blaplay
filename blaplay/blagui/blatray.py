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

import gtk

import blaplay
from blaplay.blacore import blaconst, blacfg, blaplayer
from blaplay import blautil
from blaplay.blautil import blafm
import blaguiutils


class BlaTray(gtk.StatusIcon):
    __metaclass__ = blautil.BlaSingletonMeta

    def __init__(self):
        # TODO: add support for scroll-events

        super(BlaTray, self).__init__()
        self.set_from_icon_name(blaconst.APPNAME)
        self.set_visible(
            blacfg.getboolean("general", "always.show.tray"))
        self.set_tooltip_text("Stopped")
        self.set_has_tooltip(
            blacfg.getboolean("general", "tray.show.tooltip"))

        def config_changed(cfg, section, key):
            if section == "general":
                if key == "always.show.tray":
                    self.set_visible(blacfg.getboolean(section, key))
                elif key == "tray.show.tooltip":
                    self.set_has_tooltip(blacfg.getboolean(section, key))
        blacfg.connect("changed", config_changed)

        def activate(status_icon):
            blaplay.bla.window.toggle_hide()
        self.connect("activate", activate)
        self.connect("popup_menu", self.__tray_menu)

    def __tray_menu(self, icon, button, activation_time):
        import blaplay

        menu = blaguiutils.create_control_popup_menu()
        menu.append(gtk.SeparatorMenuItem())

        # Add last.fm submenu.
        submenu = blafm.create_popup_menu()
        if submenu:
            m = gtk.MenuItem("last.fm")
            m.set_submenu(submenu)
            menu.append(m)
            menu.append(gtk.SeparatorMenuItem())

        # Add quit option.
        m = gtk.MenuItem("Quit")
        m.connect("activate", lambda *x: blaplay.shutdown())
        menu.append(m)

        menu.show_all()
        menu.popup(None, None, None, button, activation_time)

