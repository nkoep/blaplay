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

def create_control_popup_menu():
    import blaplay
    player = blaplay.bla.player

    menu = gtk.Menu()

    if player.get_state() in [blaconst.STATE_PAUSED, blaconst.STATE_STOPPED]:
        label = "Play"
        stock = gtk.STOCK_MEDIA_PLAY
    else:
        label = "Pause"
        stock = gtk.STOCK_MEDIA_PAUSE
    items = [
        (label, stock, player.play_pause),
        ("Stop", gtk.STOCK_MEDIA_STOP, player.stop),
        ("Previous", gtk.STOCK_MEDIA_PREVIOUS, player.previous),
        ("Next", gtk.STOCK_MEDIA_NEXT, player.next)
    ]
    for label, stock, callback in items:
        m = gtk.ImageMenuItem(stock)
        m.set_label(label)
        # Force early binding of `callback' by using default arguments.
        m.connect("activate", lambda x, c=callback: c())
        menu.append(m)

    return menu

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

    def do_set_property(self, prop, value):
        setattr(self, prop.name, value)

    def do_get_property(self, prop):
        return getattr(self, prop.name)

class BlaTreeViewBase(gtk.TreeView):
    __gsignals__ = {
        "popup": blautil.signal(1),
    }

    def __init__(self, *args, **kwargs):
        # TODO: rename to __empty_selection_allowed
        self.__allow_no_selection = kwargs.pop("allow_no_selection", True)
        set_button_event_handlers = kwargs.pop(
            "set_button_event_handlers", True)
        kwargs.pop("multicol", None) # TODO: Remove this.
        super(BlaTreeViewBase, self).__init__(*args, **kwargs)

        self.set_enable_search(False)
        self.set_property("rules_hint", True)
        self.set_rubber_banding(True)
        self.get_selection().set_mode(gtk.SELECTION_MULTIPLE)

        if set_button_event_handlers:
            self.connect("button_press_event", self._button_press_event)
            self.connect_object("button_release_event",
                                BlaTreeViewBase.__button_release_event, self)
            self.__pending_event = None

        def drag_begin(treeview, context):
            context.set_icon_stock(gtk.STOCK_DND, 0, 0)
        self.connect_after("drag_begin", drag_begin)
        def drag_failed(treeview, context, result):
            return True
        self.connect("drag_failed", drag_failed)

    def __allow_selection(self, yes):
        self.get_selection().set_select_function(lambda *x: yes)

    def _button_press_event(self, treeview, event):
        if event.button not in (1, 2, 3):
            return True

        selection = self.get_selection()
        x, y = map(int, [event.x, event.y])
        try:
            path, column = self.get_path_at_pos(x, y)[:2]
        except TypeError:
            if self.__allow_no_selection:
                self.__allow_selection(True)
                selection.unselect_all()
                if event.button == 3:
                    self.emit("popup", event)
            return True

        self.grab_focus()

        if event.button == 1:
            if (selection.path_is_selected(path) and
                not event.get_state() & (gtk.gdk.CONTROL_MASK |
                                         gtk.gdk.SHIFT_MASK)):
                self.__pending_event = (x, y)
                self.__allow_selection(False)
            elif event.type == gtk.gdk.BUTTON_PRESS:
                self.__pending_event = None
                self.__allow_selection(True)
        elif event.button == 3:
            if selection.path_is_selected(path):
                column.focus_cell(column.get_cells()[0])
            else:
                self.set_cursor(path, column)
            self.emit("popup", event)
            return True

        return False

    def __button_release_event(self, event):
        if event.button not in (1, 2, 3):
            return True

        if self.__pending_event is not None:
            self.__allow_selection(True)
            x_old, y_old = self.__pending_event
            self.__pending_event = None
            x, y = map(int, [event.x, event.y])
            threshold = gtk.settings_get_default().get_property(
                "gtk_dnd_drag_threshold")
            # This check is necessary because we use the generic
            # `drag_source_set' method family of gtk.Widget instead of the
            # gtk.TreeView-specific `enable_model_drag_source'. Without it,
            # double- and triple-click events may initiate DND operations even
            # though the user is not holding a mouse button.
            if abs(x_old-x) > threshold or abs(y_old-y) > threshold:
                return True
            try:
                path, column = self.get_path_at_pos(x, y)[:2]
            except TypeError:
                return True
            self.set_cursor(path, column, 0)

