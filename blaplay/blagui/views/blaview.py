# blaplay, Copyright (C) 2014  Niklas Koep

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
from ..blawindows import BlaScrolledWindow


class _Header(gtk.HBox):
    def __init__(self, name):
        super(_Header, self).__init__(spacing=2)

        self._icon_image = gtk.Image()

        # Create a lock image and resize it so it fits the text size.
        self._label = gtk.Label(name)
        self._height = int(self._label.create_pango_layout(
            self._label.get_text()).get_pixel_size()[-1] * 3 / 4)

        pixbuf = self._create_pixbuf(gtk.STOCK_DIALOG_AUTHENTICATION)
        self._lock_image = gtk.image_new_from_pixbuf(pixbuf)

        for widget in (self._icon_image, self._label, self._lock_image):
            self.pack_start(widget)

        self._label.show()
        self.show()

    def _create_pixbuf(self, stock_id):
        pixbuf = self.render_icon(stock_id, gtk.ICON_SIZE_SMALL_TOOLBAR)
        return pixbuf.scale_simple(
            self._height, self._height, gtk.gdk.INTERP_HYPER)

    def hide_icon(self):
        self._icon_image.set_visible(False)

    def set_icon_from_stock(self, stock_id):
        if stock_id is None:
            self.hide_icon()
            return
        pixbuf = self._create_pixbuf(stock_id)
        self._icon_image.set_from_pixbuf(pixbuf)
        self._icon_image.set_visible(True)

    def set_name(self, name):
        self._label.set_text(name)

    def set_locked(self, locked):
        self._lock_image.set_visible(locked)

class BlaView(BlaScrolledWindow):
    def __new__(cls, *args, **kwargs):
        # XXX: Can we do this with a mixin for future re-use?
        if cls == BlaView:
            raise ValueError("Cannot instantiate abstract class '%s'" %
                             cls.__name__)
        return super(BlaView, cls).__new__(cls, *args, **kwargs)

    def __init__(self, name, manager):
        super(BlaView, self).__init__()
        self.set_shadow_type(gtk.SHADOW_NONE)

        self._name = name
        self._manager = manager

        self._lock = blautil.BlaLock(strict=False)
        self._header = _Header(name)

    def locked(self):
        return self._lock.locked()

    def lock(self):
        self._lock.acquire()
        self._header.set_locked(True)

    def unlock(self):
        self._lock.release()
        self._header.set_locked(False)

    def toggle_lock(self):
        if self.locked():
            self.unlock()
        else:
            self.lock()

    @property
    def name(self):
        return self._name

    @property
    def manager(self):
        return self._manager

    def set_name(self, name):
        self._name = name
        self._header.set_name(name)

    def get_header(self):
        return self._header

    def get_status_message(self):
        return ""

    def remove(self):
        self.manager.remove_view(self)

    def add_context_menu_options(self, menu):
        self.manager.populate_context_menu(menu, self)

