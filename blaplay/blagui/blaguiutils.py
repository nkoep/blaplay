# -*- coding: utf-8 -*-
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
import gobject

import blaplay
from blaplay import blautil
from blaplay import blaconst, blacfg

PADDING_X, PADDING_Y, PADDING_WIDTH, PADDING_HEIGHT = -2, 0, 4, 0


def question_dialog(text, secondary_text="", with_cancel_button=False):
    kwargs = dict(flags=gtk.DIALOG_DESTROY_WITH_PARENT|gtk.DIALOG_MODAL,
            type=gtk.MESSAGE_QUESTION)
    if not with_cancel_button: kwargs["buttons"] = gtk.BUTTONS_YES_NO
    diag = gtk.MessageDialog(**kwargs)

    if with_cancel_button:
        diag.add_buttons(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_NO,
                gtk.RESPONSE_NO, gtk.STOCK_YES, gtk.RESPONSE_YES)

    diag.set_property("text", text)
    diag.set_property("secondary-text", secondary_text)
    response = diag.run()
    diag.destroy()

    if with_cancel_button: return response
    else: return True if response == gtk.RESPONSE_YES else False

def warning_dialog(text, secondary_text):
    diag = gtk.MessageDialog(
            flags=gtk.DIALOG_DESTROY_WITH_PARENT|gtk.DIALOG_MODAL,
            type=gtk.MESSAGE_WARNING, buttons=gtk.BUTTONS_OK
    )
    diag.set_property("text", text)
    diag.set_property("secondary-text", secondary_text)
    diag.run()
    diag.destroy()

def error_dialog(text, secondary_text=""):
    diag = gtk.MessageDialog(
            flags=gtk.DIALOG_DESTROY_WITH_PARENT|gtk.DIALOG_MODAL,
            type=gtk.MESSAGE_ERROR, buttons=gtk.BUTTONS_OK
    )
    diag.set_property("text", text)
    diag.set_property("secondary-text", secondary_text)
    diag.run()
    diag.destroy()

def set_visible(state):
    if state: f = BlaWindow.present
    else: f = gtk.Window.hide
    map(f, BlaWindow.instances)

class BlaScrolledWindow(gtk.ScrolledWindow):
    def __init__(self):
        super(BlaScrolledWindow, self).__init__()
        self.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)

class BlaCellRendererBase(gtk.GenericCellRenderer):
    def __init__(self):
        super(BlaCellRendererBase, self).__init__()
        self.update_colors()

    def update_colors(self):
        self._text_color = blacfg.getstring("colors", "text")
        self._active_text_color = blacfg.getstring(
                "colors", "active.text")
        self._selected_row_color = blacfg.getstring(
                "colors", "selected.rows")
        self._background_color = blacfg.getstring("colors", "background")

    def do_set_property(self, prop, value):
        setattr(self, prop.name, value)

    def do_get_property(self, prop):
        return getattr(self, prop.name)

class BlaBaseWindow(gtk.Window):
    """
    The bare base for all of our windows. This tracks position, state and size,
    and possibly saves the various values to the config if enable_tracking is
    called with `is_main_window=True'.
    """

    def __init__(self, *args, **kwargs):
        super(BlaBaseWindow, self).__init__(*args, **kwargs)
        self.__position = (-1, -1)
        self.__size = (-1, -1)
        self.__maximized = False

    def present(self, *args):
        # set the proper window state before presenting the window to the user.
        # this is necessary to avoid that the window appears in its default
        # state for a brief moment first
        self.__restore_window_state()
        super(BlaBaseWindow, self).present()

    def enable_tracking(self, is_main_window=False):
        self.__is_main_window = is_main_window
        self.connect("configure_event", self.__configure_event)
        self.connect("window_state_event", self.__window_state_event)
        self.connect("map", self.__map)
        self.__restore_window_state()

    def __configure_event(self, window, event):
        if self.__maximized: return
        self.__size = (event.width, event.height)
        if self.__is_main_window:
            blacfg.set("general", "size", "%d, %d" % self.__size)

        if self.get_property("visible"):
            self.__position = self.get_position()
            if self.__is_main_window:
                blacfg.set("general", "position", "%d, %d" % self.__position)

    def __window_state_event(self, window, event):
        self.__maximized = bool(event.new_window_state &
                                gtk.gdk.WINDOW_STATE_MAXIMIZED)
        if event.new_window_state & gtk.gdk.WINDOW_STATE_WITHDRAWN: return
        blacfg.setboolean("general", "maximized", self.__maximized)

    def __map(self, *args):
        self.__restore_window_state()

    def __restore_window_state(self):
        self.__restore_size()
        self.__restore_state()
        self.__restore_position()

    def __restore_size(self):
        if self.__is_main_window:
            size = blacfg.getlistint("general", "size")
            if size is not None: self.__size = size
        w, h = self.__size
        screen = self.get_screen()
        w = min(w, screen.get_width())
        h = min(h, screen.get_height())
        if w >= 0 and h >= 0: self.resize(w, h)

    def __restore_state(self):
        if self.__is_main_window:
            self.__maximized = blacfg.getboolean("general", "maximized")
        if self.__maximized: self.maximize()
        else: self.unmaximize()

    def __restore_position(self):
        if self.__is_main_window:
            position = blacfg.getlistint("general", "position")
            if position is not None: self.__position = position
        x, y = self.__position
        if x >= 0 and y >= 0: self.move(x, y)

class BlaWindow(BlaBaseWindow):
    """ A window that binds the ^W accelerator to close. """

    __gsignals__ = {
        "close_accel": (gobject.SIGNAL_RUN_LAST | gobject.SIGNAL_ACTION,
                gobject.TYPE_NONE, ())
    }

    instances = []

    def __init__(self, *args, **kwargs):
        dialog = kwargs.pop("dialog", True)
        with_buttonbox = kwargs.pop("with_buttonbox", True)
        with_closebutton = kwargs.pop("with_closebutton", True)
        with_cancelbutton = kwargs.pop("with_cancelbutton", False)
        close_on_escape = kwargs.pop("close_on_escape", True)

        super(BlaWindow, self).__init__(*args, **kwargs)
        type(self).instances.append(self)
        if dialog: self.set_type_hint(gtk.gdk.WINDOW_TYPE_HINT_DIALOG)
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

            if with_closebutton: button = gtk.Button(stock=gtk.STOCK_CLOSE)
            elif with_cancelbutton: button = gtk.Button(stock=gtk.STOCK_CANCEL)

            try: button.connect("clicked", self.__clicked)
            except NameError: pass
            else: self.buttonbox.pack_start(button)

            self.vbox.set_border_width(10)
            self.vbox.pack_end(self.buttonbox, expand=False, fill=False)

        self.connect_object("destroy", self.__destroy, self)
        self.enable_tracking()

    def __clicked(self, *args):
        if not self.emit("delete_event", gtk.gdk.Event(gtk.gdk.DELETE)):
            self.destroy()

    def __destroy(self, *args):
        try: type(self).instances.remove(self)
        except ValueError: return

    def do_close_accel(self):
        self.__clicked()

class BlaUniqueWindow(BlaWindow):
    __window = None

    def __new__(cls, *args):
        window = cls.__window
        if window is None:
            return super(BlaUniqueWindow, cls).__new__(cls, *args)
        window.present()
        return window

    @classmethod
    def is_not_unique(cls):
        if cls.__window: return True

    def __init__(self, *args, **kwargs):
        if type(self).__window: return
        else: type(self).__window = self
        super(BlaUniqueWindow, self).__init__(*args, **kwargs)
        self.connect_object("destroy", self.__destroy, self)

    def __destroy(self, *args):
        type(self).__window = None

class BlaTreeViewBase(gtk.TreeView):
    __gsignals__ = {
        "popup": blautil.signal(1)
    }

    instances = []

    def __init__(self, *args, **kwargs):
        self.__multicol = kwargs.pop("multicol", False)
        self.__renderer = kwargs.pop("renderer", None)
        self.__text_column = kwargs.pop("text_column", None)
        self.__allow_no_selection = kwargs.pop("allow_no_selection", True)
        set_button_event_handlers = kwargs.pop(
                "set_button_event_handlers", True)

        super(BlaTreeViewBase, self).__init__(*args, **kwargs)
        if blacfg.getboolean("colors", "overwrite") and self.__multicol:
            name = blaconst.STYLE_NAME
        else: name = ""
        self.set_name(name)
        type(self).instances.append(self)
        self.set_enable_search(False)
        if set_button_event_handlers:
            self.connect_object("button_press_event",
                    BlaTreeViewBase.__button_press_event, self)
            self.connect_object("button_release_event",
                    BlaTreeViewBase.__button_release_event, self)
            self.connect_object(
                    "row_activated", BlaTreeViewBase.__row_activated, self)
        self.connect_after("drag_begin", self.__drag_begin)
        self.connect_object("drag_failed", BlaTreeViewBase.__drag_failed, self)
        self.get_selection().set_mode(gtk.SELECTION_MULTIPLE)
        self.__pending_event = None

    def __row_activated(self, *args):
        self.__pending_event = None
        self.get_selection().set_select_function(lambda *x: True)

    def __accept_button_event(self, column, path, event, check_expander):
        if (not blacfg.getboolean("library", "custom.browser") or
                self.__multicol or self.__renderer is None):
            return True

        renderer = column.get_cell_renderers()[self.__renderer]
        model = self.get_model()
        iterator = model.get_iter(path)

        layout = renderer.get_layout(
                self, model.get_value(iterator, self.__text_column))
        width = layout.get_pixel_size()[0]
        cell_area = self.get_cell_area(path, column)
        expander_size = self.style_get_property("expander_size")

        # check vertical position of click event
        if not (event.y >= cell_area.y+PADDING_Y and
                event.y <= cell_area.y+cell_area.height):
            return False

        # check for click on expander and if the row has children
        if (check_expander and
                event.x >= cell_area.x+PADDING_X-expander_size and
                event.x <= cell_area.x+PADDING_X and
                model.iter_has_child(iterator) and
                event.type not in [gtk.gdk._2BUTTON_PRESS,
                gtk.gdk._3BUTTON_PRESS]):
            return True

        # check for click in the highlighted area
        if (event.x >= cell_area.x+PADDING_X and
                event.x <= cell_area.x+width):
            return True
        return False

    def __button_press_event(self, event):
        self.grab_focus()

        def unselect_all(selection):
            selection.set_select_function(lambda *x: True)
            selection.unselect_all()

        selection = self.get_selection()
        x, y = map(int, [event.x, event.y])
        try: path, column, cellx, celly = self.get_path_at_pos(x, y)
        except TypeError:
            if self.__allow_no_selection:
                if event.button == 3: self.emit("popup", event)
                unselect_all(selection)
            return True

        if event.button == 1: check_expander = True
        else: check_expander = False
        if not self.__accept_button_event(column, path, event, check_expander):
            unselect_all(selection)
            return True

        self.grab_focus()
        if event.button in [1, 2]:
            if ((selection.path_is_selected(path) and
                    not (event.state &
                    (gtk.gdk.CONTROL_MASK | gtk.gdk.SHIFT_MASK)))):
                self.__pending_event = [x, y]
                selection.set_select_function(lambda *args: False)
            elif event.type == gtk.gdk.BUTTON_PRESS:
                if self.__allow_no_selection:
                    self.__pending_event = None
                    selection.set_select_function(lambda *args: True)
                elif (selection.path_is_selected(path) and
                        selection.count_selected_rows() == 1 and
                        event.state & gtk.gdk.CONTROL_MASK):
                    return True

        else: # event.button == 3
            if not selection.path_is_selected(path):
                self.set_cursor(path, column, 0)
            else: column.focus_cell(column.get_cell_renderers()[0])
            self.emit("popup", event)
            return True

    def __button_release_event(self, event):
        if self.__pending_event:
            selection = self.get_selection()
            oldevent = self.__pending_event
            self.__pending_event = None
            selection.set_select_function(lambda *x: True)
            safezone = 10
            if not (oldevent[0]-safezone <= event.x <= oldevent[0]+safezone and
                    oldevent[1]-safezone <= event.y <= oldevent[1]+safezone):
                return True
            x, y = map(int, [event.x, event.y])
            try: path, column, cellx, celly = self.get_path_at_pos(x, y)
            except TypeError: return True
            self.set_cursor(path, column, 0)

    def __drag_begin(self, treeview, context):
        context.set_icon_stock(gtk.STOCK_DND, 0, 0)

    def __drag_failed(self, context, result):
        # eat the event that triggers the animation of the dragged item when we
        # release a drag and it's rejected by the drop area
        return True

