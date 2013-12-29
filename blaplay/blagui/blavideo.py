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
from blaplay.blacore import blaconst, blacfg
from blaplay import blautil, blagui
from blaview import BlaViewMeta


class BlaVideoCanvas(gtk.DrawingArea):
    __gsignals__ = {
        "toggle_fullscreen": blautil.signal(0)
    }

    def __init__(self):
        super(BlaVideoCanvas, self).__init__()
        self.set_app_paintable(True)
        self.add_events(gtk.gdk.BUTTON_PRESS_MASK | gtk.gdk.SCROLL_MASK |
                        gtk.gdk.KEY_PRESS_MASK | gtk.gdk.POINTER_MOTION_MASK)
        self.connect_object_after("expose_event",
                                  BlaVideoCanvas.__expose_event, self)
        # The cover art display uses this class as well but must be able to
        # override the the default button_press event handler. Thus we need to
        # register the default handler via connect_*_after().
        self.connect_object_after("button_press_event",
                                  BlaVideoCanvas.__button_press_event, self)
        self.connect_object("scroll_event",
                            BlaVideoCanvas.__scroll_event, self)
        self.connect_object("motion_notify_event",
                            BlaVideoCanvas.__motion_notify_event, self)
        self.connect_object("toggle_fullscreen",
                            BlaVideoCanvas.__toggle_fullscreen, self)
        # The video view always gets realized/unrealized when the view changes.
        # We can't update the xid right after changing the view because
        # realizing the drawingarea is done asynchronously in the X server so
        # the xid might not be valid yet. Note that the signal is not emitted
        # when the side pane gets unhidden because the video canvas element
        # never gets unrealized in the first place.
        def realize(da):
            self.__parent = self.get_parent()
            # If the xid is updated even though no video is playing we get
            # killed off by the X server due to a BadWindow error.
            if player.video:
                player.set_xwindow_id(self.window.xid)
            self.modify_bg(gtk.STATE_NORMAL, gtk.gdk.Color(0, 0, 0))
        self.connect("realize", realize)

        # Request a redraw on track_changed and track_stopped events to reset
        # the drawing area.
        for signal in ["track_changed", "track_stopped"]:
            player.connect(signal, lambda *x: self.queue_draw())

        self.__parent = None

    def __toggle_fullscreen(self):
        blaplay.bla.window.set_fullscreen(
            self, self.__parent if self.__parent.child is None else None)

    def __expose_event(self, event):
        # TODO: - if not player.video: display title + anim
        pass

    def __button_press_event(self, event):
        if event.button == 1 and event.type == gtk.gdk._2BUTTON_PRESS:
            self.emit("toggle_fullscreen")
        elif event.button == 3 and event.type not in [gtk.gdk._2BUTTON_PRESS,
                                                      gtk.gdk._3BUTTON_PRESS]:
            if not player.video:
                return False

            menu = blaguiutils.create_control_popup_menu()
            menu.append(gtk.SeparatorMenuItem())

            # Add fullscreen entry.
            action = ("Enter" if not blaplay.bla.window.is_fullscreen else
                      "Leave")
            m = gtk.ImageMenuItem(gtk.STOCK_FULLSCREEN)
            m.set_label("%s fullscreen" % action)
            m.connect("activate",
                      lambda *x: self.emit("toggle_fullscreen"))
            menu.append(m)

            menu.show_all()
            menu.popup(None, None, None, event.button, event.time)
            return True
        else:
            return False
        self.__schedule_hide_cursor()

    def __scroll_event(self, event):
        # TODO: add either volume up/down or seek-on-scroll behaviour
        print_d("TODO: scroll event")

    def __motion_notify_event(self, event):
        # TODO: toggle cursor and controls overlay visibility
        self.__schedule_hide_cursor()

    def __schedule_hide_cursor(self):
        try:
            gobject.source_remove(self.__tid)
        except AttributeError:
            pass
        self.window.set_cursor(None)
        def hide_cursor():
            if blaplay.bla.window.is_fullscreen:
                self.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.BLANK_CURSOR))
        self.__tid = gobject.timeout_add(1500, hide_cursor)

class BlaVideo(gtk.Viewport):
    __metaclass__ = BlaViewMeta("Video")

    def __init__(self):
        super(BlaVideo, self).__init__()

        self.__drawing_area = BlaVideoCanvas()
        viewport = gtk.Viewport()
        viewport.set_shadow_type(gtk.SHADOW_NONE)

        vbox = gtk.VBox(spacing=10)
        viewport.add(self.__drawing_area)
        vbox.pack_start(viewport, expand=True, fill=True)

        self.__hbox = gtk.HBox(spacing=3)

        categories = [
            ("General", ["Title", "Artist", "Duration", "Filesize"]),
            ("Video", ["Codec", "Resolution", "Frame rate", "Bitrate"]),
            ("Audio", ["Stream", "Codec", "Channels", "Sampling rate",
                       "Bitrate"])
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

        self.__shadow_type = self.get_shadow_type()

        self.add(vbox)
        self.show_all()

    def get_video_canvas(self):
        return self.__drawing_area

