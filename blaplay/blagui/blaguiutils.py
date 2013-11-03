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
from blaplay.blacore import blaconst, blacfg
from blaplay import blautil

# TODO: move these to blabrowsers.py once the required code was moved out of
#       BlaTreeViewBase
PADDING_X, PADDING_Y, PADDING_WIDTH, PADDING_HEIGHT = -2, 0, 4, 0


def _generic_dialog(text, secondary_text, **kwargs):
    diag = BlaMessageDialog(**kwargs)
    diag.set_property("text", text)
    diag.set_property("secondary-text", secondary_text)
    return diag

def question_dialog(text, secondary_text="", with_cancel_button=False,
                    parent=None):
    buttons = [gtk.STOCK_NO, gtk.RESPONSE_NO, gtk.STOCK_YES, gtk.RESPONSE_YES]
    if with_cancel_button:
        buttons = [gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL] + buttons
    diag = _generic_dialog(text, secondary_text, parent=parent,
                           type=gtk.MESSAGE_QUESTION)
    diag.add_buttons(*buttons)
    response = diag.run()
    diag.destroy()
    return response

def warning_dialog(text, secondary_text, parent=None):
    diag = _generic_dialog(text, secondary_text, parent=parent,
                           type=gtk.MESSAGE_WARNING, buttons=gtk.BUTTONS_OK)
    diag.run()
    diag.destroy()

def error_dialog(text, secondary_text="", parent=None):
    diag = _generic_dialog(text, secondary_text, parent=parent,
                           type=gtk.MESSAGE_ERROR, buttons=gtk.BUTTONS_OK)
    diag.run()
    diag.destroy()

def set_visible(state):
    if state:
        f = BlaWindow.present
    else:
        f = gtk.Window.hide
    map(f, BlaWindow.instances)


class BlaDialog(gtk.Dialog):
    def __init__(self, *args, **kwargs):
        kwargs["parent"] = kwargs.get("parent", None) or blaplay.bla.window
        kwargs["flags"] = gtk.DIALOG_DESTROY_WITH_PARENT | gtk.DIALOG_MODAL
        if "buttons" not in kwargs:
            kwargs["buttons"] = (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                 gtk.STOCK_OK, gtk.RESPONSE_OK)
        super(BlaDialog, self).__init__(*args, **kwargs)
        self.set_resizable(False)

class BlaMessageDialog(gtk.MessageDialog):
    def __init__(self, *args, **kwargs):
        kwargs["parent"] = kwargs.get("parent", None) or blaplay.bla.window
        kwargs["flags"] = gtk.DIALOG_DESTROY_WITH_PARENT | gtk.DIALOG_MODAL
        super(BlaMessageDialog, self).__init__(*args, **kwargs)
        self.set_resizable(False)

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

# TODO: move the window classes to their own file
class BlaScrolledWindow(gtk.ScrolledWindow):
    def __init__(self):
        super(BlaScrolledWindow, self).__init__()
        self.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)

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
        # set the proper window state before presenting the window to the user.
        # this is necessary to avoid that the window appears in its default
        # state for a brief moment first
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

# FIXME: use the BlaSingletonMeta metaclass from blautils instead
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
        if cls.__window:
            return True

    def __init__(self, *args, **kwargs):
        if type(self).__window:
            return
        else:
            type(self).__window = self
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
        # TODO: rename to __empty_selection_allowed
        self.__allow_no_selection = kwargs.pop("allow_no_selection", True)
        set_button_event_handlers = kwargs.pop(
            "set_button_event_handlers", True)

        super(BlaTreeViewBase, self).__init__(*args, **kwargs)
        self.instances.append(self)

        if blacfg.getboolean("colors", "overwrite") and self.__multicol:
            name = blaconst.STYLE_NAME
        else:
            name = ""
        self.set_name(name)
        self.set_enable_search(False)
        self.get_selection().set_mode(gtk.SELECTION_MULTIPLE)

        self.__pending = False
        if set_button_event_handlers:
            self.connect_object("button_press_event",
                                BlaTreeViewBase.__button_press_event, self)
            self.connect_object("button_release_event",
                                BlaTreeViewBase.__button_release_event, self)

        # Hook up signals for drag and drop.
        def drag_begin(treeview, context):
            context.set_icon_stock(gtk.STOCK_DND, 0, 0)
            self.__dragging = True
        self.connect_after("drag_begin", drag_begin)
        def drag_failed(treeview, context, result):
            self.__drag_aborted = True
            self.__allow_selection(True)
            # Eat the animation event in case a receiver rejects the drop.
            return True
        self.connect("drag_failed", drag_failed)
        def drag_end(treeview, context):
            self.__allow_selection(True)
            self.__dragging = False
        self.connect("drag_end", drag_end)
        self.__dragging = False
        self.__drag_aborted = False

    def __allow_selection(self, yes):
        self.get_selection().set_select_function(lambda *x: yes)

    def __accept_button_event(self, column, path, event, check_expander):
        # TODO: get rid of this method and implement it only where necessary
        #       (i.e. the library browser)
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
        # Never block on double or triple click events.
        if (event.type == gtk.gdk._2BUTTON_PRESS or
            event.type == gtk.gdk._3BUTTON_PRESS):
            self.__allow_selection(True)
            return False

        if event.button not in [1, 2, 3]:
            return True

        self.grab_focus()
        selection = self.get_selection()

        try:
            path, column = self.get_path_at_pos(
                *map(int, [event.x, event.y]))[:2]
        except TypeError:
            # If the click event didn't hit a row check if we allow deselecting
            # all rows in the view and do so if we do.
            if self.__allow_no_selection:
                self.__allow_selection(True)
                selection.unselect_all()
                if event.button == 3:
                    self.emit("popup", event)
            return True

        # TODO: remove me
        if not self.__accept_button_event(column, path, event,
                                          check_expander=(event.button== 1)):
            self.__allow_selection(True)
            selection.unselect_all()

        path_selected = selection.path_is_selected(path)
        mod_active = event.get_state() & (
            gtk.gdk.CONTROL_MASK | gtk.gdk.SHIFT_MASK)

        if event.button == 1:
            # The __pending variable is used to signal to the button release
            # event handler that a normal button press event (no modifier)
            # occured on an already selected path. This is the situation at the
            # beginning of a DND operation. In this case we have to disallow
            # that the default button press handler selects the clicked path,
            # hence the negation of __pending when calling __allow_selection().
            self.__pending = path_selected and not mod_active
            self.__allow_selection(not self.__pending)

        elif event.button == 3:
            self.__allow_selection(True)
            if not path_selected:
                self.set_cursor(path, column, 0)
            else:
                column.focus_cell(column.get_cell_renderers()[0])
            self.emit("popup", event)
            return True

        return False

    def __button_release_event(self, event):
        if event.button not in [1, 2, 3]:
            return True

        self.__allow_selection(True)

        if (not self.__pending or self.__dragging or
            self.is_rubber_banding_active()):
            return False

        # Ignore button release events after aborted DND operations.
        if self.__drag_aborted:
            self.__drag_aborted = False
            return False
        try:
            path, column = self.get_path_at_pos(
                *map(int, [event.x, event.y]))[:2]
            self.set_cursor(path, column, 0)
        except TypeError:
            pass

        self.__pending = False

        return False

