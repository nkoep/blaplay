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

import gobject
gobject.threads_init()
import pygtk
pygtk.require("2.0")
import gtk
gtk.gdk.threads_init()

import blaplay
from blaplay import blaconst, blacfg, blaplayer, blafm
from blaguiutils import BlaTreeViewBase

uimanager = None
accelgroup = None
bla = None
tray = None


def init():
    from blawindow import BlaWindow
    global bla, tray

    gtk.icon_theme_get_default().append_search_path(blaconst.IMAGES_PATH)

    bla = BlaWindow()
    tray = BlaTray()

def update_menu(view):
    from blaplaylist import BlaPlaylist, BlaQueue

    state = False
    if view == blaconst.VIEW_PLAYLISTS: state = True

    for entry in blaconst.MENU_PLAYLISTS:
        uimanager.get_widget(entry).set_visible(state)

    if view in [blaconst.VIEW_PLAYLISTS, blaconst.VIEW_QUEUE]:
        clipboard = (BlaPlaylist.clipboard if view == blaconst.VIEW_PLAYLISTS
                else BlaQueue.clipboard)
        uimanager.get_widget("/Menu/Edit/Paste").set_sensitive(bool(clipboard))
        state = True
    else: state = False

    for entry in blaconst.MENU_EDIT:
        uimanager.get_widget(entry).set_visible(state)

def update_colors():
    if blacfg.getboolean("colors", "overwrite"): name = blaconst.STYLE_NAME
    else: name = ""
    map(lambda treeview: treeview.set_name(name), BlaTreeViewBase.instances)

    # invert background color to get a clearly visible color for the drop
    # indicator of DND operations
    color = gtk.gdk.color_parse(blacfg.getstring("colors", "background"))
    color = [65535-c for c in [color.red, color.green, color.blue]]
    color = gtk.gdk.Color(*color).to_string()

    gtk.rc_parse_string(
        """
        style "blaplay-toolbar"
        {
            xthickness = 0
            ythickness = 0

            GtkButton::focus-padding = 2
        }

        widget "*.GtkHBox.ctrlbar.GtkButton" style : highest "blaplay-toolbar"

        style "%s"
        {
            text[NORMAL] = "%s"
            text[ACTIVE] = "%s"
            text[PRELIGHT] = "%s"
            text[SELECTED] = "%s"
            text[INSENSITIVE] = "%s"

            base[NORMAL] = "%s"
            base[ACTIVE] = "%s"
            base[PRELIGHT] = "%s"
            base[SELECTED] = "%s"
            base[INSENSITIVE] = "%s"

            GtkTreeView::even-row-color = "%s"
            GtkTreeView::odd-row-color = "%s"
        }

        widget "*.GtkVBox.*.%s" style : highest "%s"
        """ % (
            blaconst.STYLE_NAME,

            # text colors
            blacfg.getstring("colors", "text"),
            blacfg.getstring("colors", "active.text"),
            blacfg.getstring("colors", "text"),
            blacfg.getstring("colors", "active.text"),
            blacfg.getstring("colors", "text"),

            # base colors
            blacfg.getstring("colors", "background"),
            blacfg.getstring("colors", "selected.rows"),
            blacfg.getstring("colors", "background"),
            blacfg.getstring("colors", "selected.rows"),
            blacfg.getstring("colors", "background"),

            # even-odd-row colors
            blacfg.getstring("colors", "background"),
            blacfg.getstring("colors", "alternate.rows"),

            blaconst.STYLE_NAME, blaconst.STYLE_NAME
        )
    )

    from blabrowsers import BlaBrowsers
    from blavisualization import BlaVisualization
    from blaview import BlaView

    BlaBrowsers.update_colors()
    BlaVisualization.update_colors()
    BlaView.update_colors()

def is_accel(event, accel):
    # convenience function from quodlibet to check for accelerator matches
    if event.type != gtk.gdk.KEY_PRESS: return False

    # ctrl+shift+x gives us ctrl+shift+X and accelerator_parse returns
    # lowercase values for matching, so lowercase it if possible
    keyval = event.keyval
    if not keyval & ~0xFF:
        keyval = ord(chr(keyval).lower())

    default_mod = gtk.accelerator_get_default_mod_mask()
    accel_keyval, accel_mod = gtk.accelerator_parse(accel)

    # if the accel contains non default modifiers matching will never work and
    # since no one should use them, complain
    non_default = accel_mod & ~default_mod
    if non_default:
        blaplay.print_w("Accelerator `%s' contains a non default modifier "
                "`%s'." % (accel, gtk.accelerator_name(0, non_default) or ""))

    # remove everything except default modifiers and compare
    return (accel_keyval, accel_mod) == (keyval, event.state & default_mod)


class BlaTray(gtk.StatusIcon):
    def __init__(self):
        super(BlaTray, self).__init__()
        self.set_from_icon_name(blaconst.APPNAME)
        self.set_visible(
                blacfg.getboolean("general", "always.show.tray"))
        self.set_tooltip_text("Stopped")
        self.set_has_tooltip(
                blacfg.getboolean("general", "tray.tooltip"))
        self.connect("activate", bla.toggle_hide)
        self.connect("popup_menu", self.__tray_menu)

    def __tray_menu(self, icon, button, activation_time):
        menu = gtk.Menu()
        player = blaplayer.player

        items = [
            ("Play/Pause", player.play_pause), ("Stop", player.stop),
            ("Next", player.next), ("Previous", player.previous), (None, None),
            ("last.fm", None), ("Quit", bla.quit)
        ]

        for label, callback in items:
            if label and callback is None:
                submenu = blafm.get_popup_menu()
                if not submenu: continue
                m = gtk.MenuItem(label)
                m.set_submenu(submenu)
                menu.append(m)
                m = gtk.SeparatorMenuItem()
            elif not label: m = gtk.SeparatorMenuItem()
            else:
                m = gtk.MenuItem(label)
                m.connect("activate", lambda x, c=callback: c())
            menu.append(m)

        menu.show_all()
        menu.popup(None, None, None, button, activation_time)

