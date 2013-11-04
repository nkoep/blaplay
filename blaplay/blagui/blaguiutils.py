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
    from blawindows import BlaWindow
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

