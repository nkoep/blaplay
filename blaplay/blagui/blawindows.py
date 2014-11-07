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

from blaplay import blautil


class BlaBaseWindow(gtk.Window):
    """
    The bare base for all of our windows. This tracks position, state, and
    size. The `state_manager', if given, has to be an object that implements a
    `size', `position', and `maximized' method. Called without arguments, these
    methods should return the desired size, position, and maximized state of
    the window. Otherwise, the methods are called with their respective values
    to allow the state manager to keep track of modifications.
    """

    class StateManager(object):
        def size(self, *args):
            pass
        def position(self, *args):
            pass
        def maximized(self, *args):
            return False

    def __init__(self, state_manager=None, *args, **kwargs):
        super(BlaBaseWindow, self).__init__(*args, **kwargs)
        self._position = (-1, -1)
        self._size = (-1, -1)
        self._maximized = self._was_maximized = False
        if state_manager is None:
            state_manager = self.StateManager()
        elif not isinstance(state_manager, self.StateManager):
            raise TypeError()
        self._state_manager = state_manager
        self.connect("configure_event", self._configure_event)
        self.connect("window_state_event", self._window_state_event)
        self.connect("map", self._map)
        self._restore_window_state()

    def present(self):
        # Set the proper window state before presenting the window to the user.
        # This is necessary to avoid that the window appears in its default
        # state for a brief moment first.
        self._restore_window_state()
        super(BlaBaseWindow, self).present()

    def _configure_event(self, window, event):
        if self._maximized:
            return
        self._size = (event.width, event.height)
        self._state_manager.size(self._size)

        if self.get_property("visible"):
            self._position = self.get_position()
            self._state_manager.position(self._position)

    def _window_state_event(self, window, event):
        self._maximized = bool(
            event.new_window_state & gtk.gdk.WINDOW_STATE_MAXIMIZED)
        if event.new_window_state & gtk.gdk.WINDOW_STATE_WITHDRAWN:
            return
        self._state_manager.maximized(self._maximized and self._was_maximized)

    def _map(self, *args):
        self._restore_window_state()

    def _restore_window_state(self):
        self._restore_size()
        self._restore_state()
        self._restore_position()

    def _restore_size(self):
        size = self._state_manager.size()
        if size is not None:
            self._size = size
        w, h = self._size
        screen = self.get_screen()
        w = min(w, screen.get_width())
        h = min(h, screen.get_height())
        if w >= 0 and h >= 0:
            self.resize(w, h)

    def _restore_state(self):
        self._maximized = self._was_maximized = self._state_manager.maximized()
        if self._maximized:
            self.maximize()
        else:
            self.unmaximize()

    def _restore_position(self):
        position = self._state_manager.position()
        if position is not None:
            self._position = position
        x, y = self._position
        if x >= 0 and y >= 0:
            self.move(x, y)

    def set_maximized(self, yes):
        if yes:
            self._was_maximized = self._maximized
            self.maximize()
        elif not self._was_maximized:
            # If the window was not already maximized before we maximized it
            # restore the old state here, i.e. unmaximize the window again.
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

class BlaScrolledWindow(gtk.ScrolledWindow):
    def __init__(self):
        super(BlaScrolledWindow, self).__init__()
        self.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)

