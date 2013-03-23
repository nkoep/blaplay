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

import gobject
import gtk

import blaplay
player = blaplay.bla.player
from blaplay import blautil


def view(name):
    def view(cls):
        cls.name = property(lambda self: name)
        return cls
    return view

@view("Video")
class BlaVideo(gtk.Viewport):
    __gsignals__ = {
        "count_changed": blautil.signal(2)
    }
    __is_fullscreen = False

    def __init__(self):
        super(BlaVideo, self).__init__()
        vbox = gtk.VBox(spacing=10)

        self.__da = gtk.DrawingArea()
        self.__da.modify_bg(gtk.STATE_NORMAL, gtk.gdk.Color(0, 0, 0))
        self.__da.set_app_paintable(True)
        self.__da.add_events(gtk.gdk.BUTTON_PRESS_MASK |
                             gtk.gdk.KEY_PRESS_MASK |
                             gtk.gdk.SCROLL_MASK |
                             gtk.gdk.POINTER_MOTION_MASK)
        self.__da.connect_object("button_press_event",
                                 BlaVideo.__button_press_event, self)
        self.__da.connect_object("key_press_event",
                                 BlaVideo.__key_press_event, self)
        self.__da.connect_object("scroll_event",
                                 BlaVideo.__scroll_event, self)
        self.__da.connect_object("motion_notify_event",
                                 BlaVideo.__motion_notify_event, self)
        def drawingarea_realized(drawingarea):
            gtk.gdk.display_get_default().sync()
            player.set_xwindow_id(drawingarea.window.xid)
            blaplay.bla.window.connect_object(
                "window_state_event", BlaVideo.__window_state_event, self)
        self.__da.connect("realize", drawingarea_realized)
        def drawingarea_unrealized(drawingarea):
            player.set_xwindow_id(0)
        self.__da.connect("unrealize", drawingarea_unrealized)
        def get_xid(player):
            if self.__da.window is not None:
                xid = self.__da.window.xid
            else:
                xid = 0
            player.set_xwindow_id(xid)
        player.connect("get_xid", get_xid)
        # Request a redraw on track_stopped events to reset the drawing area.
        player.connect("track_stopped", lambda *x: self.__da.queue_draw())

        vbox.pack_start(self.__da, expand=True, fill=True)

        self.__hbox = gtk.HBox(spacing=3)

        categories = [
            ("General", ["Title", "Artist", "Album", "Year"]),
            ("Video", ["Resolution", "Codec", "Frame rate", "Bitrate"]),
            ("Audio", ["Codec", "Channels", "Sampling rate", "Bitrate"])
        ]
        for title, fields in categories:
            table = gtk.Table(rows=len(fields)+1, columns=2, homogeneous=False)

            # Add the heading.
            label = gtk.Label()
            label.set_markup("<b>%s</b>" % title)
            alignment = gtk.Alignment(xalign=0.05)
            alignment.add(label)
            table.attach(alignment, 0, 2, 0, 1)

            for idx, field in enumerate(fields):
                label = gtk.Label()
                label.set_markup("<i>%s:</i>" % field)
                alignment = gtk.Alignment(xalign=0.1)
                alignment.add(label)
                table.attach(alignment, 0, 1, 2 * idx + 1, 2 * idx + 2)
            self.__hbox.pack_start(table)

        # TODO: fix the height to the same height as cover display
        self.__hbox.set_size_request(-1, 150)
        vbox.pack_start(self.__hbox, expand=False, fill=False)

        self.add(vbox)
        self.show_all()

        self.__shadow_type = self.get_shadow_type()

    def __toggle_cursor(self):
        try:
            gobject.source_remove(self.__tid)
        except AttributeError:
            pass
        self.__da.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.LEFT_PTR))
        if self.__is_fullscreen:
            self.__tid = gobject.timeout_add(
                2000, lambda: self.__da.window.set_cursor(
                gtk.gdk.Cursor(gtk.gdk.BLANK_CURSOR)))

    def __button_press_event(self, event):
        # TODO: handle right-click events

        self.__toggle_cursor()
        if event.button == 1 and event.type == gtk.gdk._2BUTTON_PRESS:
            state = self.__is_fullscreen
            if state:
                blaplay.bla.window.unfullscreen()
                self.set_shadow_type(self.__shadow_type)
            else:
                self.set_shadow_type(gtk.SHADOW_NONE)
                blaplay.bla.window.fullscreen()

            blaplay.bla.window.set_interface_visible(state)
            self.__hbox.set_visible(state)
        return False

    def __key_press_event(self, event):
        # TODO: handle ctrl+enter for fullscreen
        pass

    def __scroll_event(self, event):
        # TODO: add either volume up/down or seek-on-scroll behaviour
        pass

    def __motion_notify_event(self, event):
        # TODO: toggle cursor and controls overlay visibility
        self.__toggle_cursor()

    def __window_state_event(self, event):
        self.__is_fullscreen = bool(
            gtk.gdk.WINDOW_STATE_FULLSCREEN & event.new_window_state)

    def get_drawingarea(self):
        return self.__da

