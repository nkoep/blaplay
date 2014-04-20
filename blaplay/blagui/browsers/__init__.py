# blaplay, Copyright (C) 2012-2014  Niklas Koep

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

from .blalibrarybrowser import BlaLibraryBrowser
from .blalibrarybrowsercontroller import BlaLibraryBrowserController
from .blafilesystembrowser import BlaFilesystemBrowser


def create_view(config, library, playlist_manager):
    # Create the library browser and its controller.
    library_browser = BlaLibraryBrowser()
    BlaLibraryBrowserController(
        config, library, library_browser, playlist_manager)

    # # Create the filesystem browser and its controller.
    # filesystem_browser = BlaFilesystemBrowser()
    # BlaFilesystemBrowserController(
    #     config, filesystem_browser, playlist_manager)

    return BlaBrowserView(config, [library_browser])#, filesystem_browser])


class BlaBrowserView(gtk.Notebook):
    def __init__(self, config, browsers):
        super(BlaBrowserView, self).__init__()

        self._config = config

        for browser in browsers:
            label = gtk.Label(browser.name)
            self.append_page(browser, label)

        browser_id = config.getint("general", "browser.view")
        for browser in self:
            if browser.ID == browser_id:
                self.set_current_page(self.page_num(browser))
                break
        self.connect("switch-page", self._on_switch_page, config)

        self.show_all()

    def _on_switch_page(self, notebook, page, page_num, config):
        browser = self.get_nth_page(page_num)
        config.set_("general", "browser.view", browser.ID)

