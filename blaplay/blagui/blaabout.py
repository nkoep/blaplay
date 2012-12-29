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

import gtk

from blaplay.blacore import blaconst


class BlaAbout(gtk.AboutDialog):
    def __init__(self, *args):
        super(BlaAbout, self).__init__()
        self.set_logo(gtk.image_new_from_file(blaconst.LOGO).get_pixbuf())
        self.set_name(blaconst.APPNAME)
        self.set_version(blaconst.VERSION)
        self.set_comments(blaconst.COMMENT)
        self.set_website(blaconst.WEB)
        self.set_copyright(blaconst.COPYRIGHT)
        self.set_authors(blaconst.AUTHORS)
        self.show_all()
        self.run()
        self.destroy()

