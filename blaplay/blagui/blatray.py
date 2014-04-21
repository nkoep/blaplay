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

import gtk

import blaplay
from blaplay.blacore import blaconst, blacfg, blaplayer
from blaplay.blautil import blafm
import blaguiutil


class BlaTray(gtk.StatusIcon):
    def __init__(self):
        # TODO: Add support for scroll-events.

        super(BlaTray, self).__init__()
        self.set_from_icon_name(blaconst.APPNAME)
        self.set_visible(
            blacfg.getboolean("general", "always.show.tray"))
        self.set_tooltip_text("Stopped")
        def config_changed(cfg, section, key):
            if section == "general" and key == "always.show.tray":
                self.set_visible(blacfg.getboolean(section, key))
        blacfg.connect("changed", config_changed)

        def activate(status_icon):
            blaplay.bla.window.toggle_hide()
        self.connect("activate", activate)
        self.connect("popup_menu", self.__tray_menu)

    def __tray_menu(self, icon, button, activation_time):
        menu = blaguiutil.create_control_popup_menu()
        menu.append_separator()

        # Add last.fm submenu.
        submenu = blafm.create_popup_menu()
        if submenu:
            menu.append_submenu("last.fm", submenu)
            menu.append_separator()

        # Add quit option.
        menu.append_item("Quit", blaplay.shutdown)

        menu.run(button, activation_time)

