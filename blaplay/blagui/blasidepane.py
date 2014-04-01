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

from blaplay.blacore import blaconst
from blaplay.blautil.blametadata import BlaFetcher as BlaMetadataFetcher
from blalyricsviewer import BlaLyricsViewer
from blatrackinfo import BlaTrackInfo


class BlaSidePane(gtk.VBox):
    def __init__(self):
        super(BlaSidePane, self).__init__(spacing=blaconst.WIDGET_SPACING)
        metadata_fetcher = BlaMetadataFetcher()
        self.pack_start(BlaLyricsViewer(metadata_fetcher))
        self.pack_start(BlaTrackInfo(metadata_fetcher), expand=False)
        self.show_all()

