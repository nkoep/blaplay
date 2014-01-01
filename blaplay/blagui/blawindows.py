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

import gtk

from blaplay.blacore import blacfg
from blaplay import blautil


class BlaBaseWindow(gtk.Window):
    """
    The bare base for all of our windows. This tracks position, state and size,
    and possibly saves the various values to the config if enable_tracking is
    called with `is_main_window=True'.
    """

    __main_window = None

    def __init__(self, *args, **kwargs):
        super(BlaBaseWindow, self).__init__(*args, **kwargs)
        self.__position = (-1, -1)
        self.__size = (-1, -1)
        self.__maximized = self.__was_maximized = False
        self.__is_main_window = False

    def present(self):
        # Set the proper window state before presenting the window to the user.
        # This is necessary to avoid that the window appears in its default
        # state for a brief moment first.
        self.__restore_window_state()
        super(BlaBaseWindow, self).present()

    def enable_tracking(self, is_main_window=False):
        if self.__main_window is not None and is_main_window:
            raise ValueError("There can only be one main window")
        self.__is_main_window = is_main_window
        if self.__is_main_window:
            type(self).__main_window = self
        self.connect("configure_event", self.__configure_event)
        self.connect("window_state_event", self.__window_state_event)
        self.connect("map", self.__map)
        self.__restore_window_state()

    def __configure_event(self, window, event):
        if self.__maximized:
            return
        self.__size = (event.width, event.height)
        if self.__is_main_window:
            blacfg.set("general", "size", "%d, %d" % self.__size)

        if self.get_property("visible"):
            self.__position = self.get_position()
            if self.__is_main_window:
                blacfg.set("general", "position", "%d, %d" % self.__position)

    def __window_state_event(self, window, event):
        self.__maximized = bool(
            event.new_window_state & gtk.gdk.WINDOW_STATE_MAXIMIZED)
        if event.new_window_state & gtk.gdk.WINDOW_STATE_WITHDRAWN:
            return
        if self.__is_main_window:
            blacfg.setboolean("general", "maximized",
                              self.__maximized and self.__was_maximized)

    def __map(self, *args):
        self.__restore_window_state()

    def __restore_window_state(self):
        self.__restore_size()
        self.__restore_state()
        self.__restore_position()

    def __restore_size(self):
        if self.__is_main_window:
            size = blacfg.getlistint("general", "size")
            if size is not None:
                self.__size = size
        w, h = self.__size
        screen = self.get_screen()
        w = min(w, screen.get_width())
        h = min(h, screen.get_height())
        if w >= 0 and h >= 0:
            self.resize(w, h)

    def __restore_state(self):
        if self.__is_main_window:
            self.__maximized = self.__was_maximized = blacfg.getboolean(
                "general", "maximized")
        if self.__maximized:
            self.maximize()
        else:
            self.unmaximize()

    def __restore_position(self):
        if self.__is_main_window:
            position = blacfg.getlistint("general", "position")
            if position is not None:
                self.__position = position
        x, y = self.__position
        if x >= 0 and y >= 0:
            self.move(x, y)

    def set_maximized(self, yes):
        if yes:
            self.__was_maximized = self.__maximized
            self.maximize()
        elif not self.__was_maximized:
            # If the window was not already maximized before we maximized it
            # restore the old state here, i.e. unmaximize the w/indow again.
            self.unmaximize()

class BlaWindow(BlaBaseWindow):
    __gsignals__ = {
        "close_accel": blautil.signal(0)
    }

    instances = []

    def __init__(self, *args, **kwargs):
        dialog = kwargs.pop("dialog", True)
        with_buttonbox = kwargs.pop("with_buttonbox", True)
        with_closebutton = kwargs.pop("with_closebutton", True)
        with_cancelbutton = kwargs.pop("with_cancelbutton", False)
        close_on_escape = kwargs.pop("close_on_escape", True)

        super(BlaWindow, self).__init__(*args, **kwargs)
        self.instances.append(self)
        if dialog:
            self.set_type_hint(gtk.gdk.WINDOW_TYPE_HINT_DIALOG)
        self.set_destroy_with_parent(True)
        self.set_position(gtk.WIN_POS_CENTER_ON_PARENT)

        accels = gtk.AccelGroup()
        self.add_accel_group(accels)
        self.add_accelerator("close_accel", accels, ord("w"),
                             gtk.gdk.CONTROL_MASK, 0)
        if close_on_escape:
            esckey, mod = gtk.accelerator_parse("Escape")
            self.add_accelerator("close_accel", accels, esckey, mod, 0)

        self.vbox = gtk.VBox()
        self.add(self.vbox)

        if with_buttonbox or with_closebutton or with_cancelbutton:
            self.buttonbox = gtk.HButtonBox()
            self.buttonbox.set_spacing(10)
            self.buttonbox.set_border_width(5)
            self.buttonbox.set_layout(gtk.BUTTONBOX_END)

            if with_closebutton:
                button = gtk.Button(stock=gtk.STOCK_CLOSE)
            elif with_cancelbutton:
                button = gtk.Button(stock=gtk.STOCK_CANCEL)

            try:
                button.connect("clicked", self.__clicked)
            except NameError:
                pass
            else:
                self.buttonbox.pack_start(button)

            self.vbox.set_border_width(10)
            self.vbox.pack_end(self.buttonbox, expand=False, fill=False)

        self.connect_object("destroy", self.__destroy, self)
        self.enable_tracking()

    def __clicked(self, *args):
        if not self.emit("delete_event", gtk.gdk.Event(gtk.gdk.DELETE)):
            self.destroy()

    def __destroy(self, *args):
        try:
            self.instances.remove(self)
        except ValueError:
            return

    def do_close_accel(self):
        self.__clicked()

class BlaUniqueWindow(BlaWindow):
    __metaclass__ = blautil.BlaSingletonMeta

class BlaScrolledWindow(gtk.ScrolledWindow):
    def __init__(self):
        super(BlaScrolledWindow, self).__init__()
        self.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)

