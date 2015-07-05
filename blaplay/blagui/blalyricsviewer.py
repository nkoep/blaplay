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

import os

import gobject
import gtk
import pango

from blaplay import blautil
from blaplay.blacore import blaconst
from blaplay.formats._identifiers import *
from blawindows import BlaScrolledWindow


class BlaLyricsViewer(gtk.Notebook):
    def __init__(self, player, metadata_fetcher):
        super(BlaLyricsViewer, self).__init__()

        self._metadata_fetcher = metadata_fetcher
        self._track = None
        self._timestamp = 0
        self._timeout_id = 0

        sw = BlaScrolledWindow()
        sw.set_shadow_type(gtk.SHADOW_NONE)

        # Create the text view.
        text_view = gtk.TextView()
        text_view.set_editable(False)
        text_view.set_cursor_visible(False)
        text_view.set_wrap_mode(gtk.WRAP_WORD)
        text_view.set_justification(gtk.JUSTIFY_CENTER)
        sw.add(text_view)
        self.append_page(sw, gtk.Label("Lyrics"))

        # Create insert tags.
        self._tb = text_view.get_buffer()
        self._tb.create_tag("italic", style=pango.STYLE_ITALIC)

        self._add_action_widget()

        # Hook up signals.
        player.connect("state-changed", self._on_player_state_changed)
        metadata_fetcher.connect_object(
            "lyrics", BlaLyricsViewer._display_lyrics, self)

        self.show_all()

    def _add_action_widget(self):
        return # TODO
        button = gtk.Button()
        button.set_tooltip_text("Edit lyrics")
        button.set_relief(gtk.RELIEF_NONE)
        button.set_focus_on_click(False)
        button.add(
            gtk.image_new_from_stock(gtk.STOCK_EDIT, gtk.ICON_SIZE_MENU))
        style = gtk.RcStyle()
        style.xthickness = style.ythickness = 0
        button.modify_style(style)
        button.connect("clicked", lambda *x: False)
        button.show_all()
        self.set_action_widget(button, gtk.PACK_END)

    @blautil.idle
    def _display_lyrics(self, timestamp, lyrics):
        if timestamp != self._timestamp:
            return
        iterator = self._tb.get_iter_at_mark(self._tb.get_insert())
        if lyrics is None:
            self._tb.insert_with_tags_by_name(
                iterator, "\n\nNo lyrics found", "italic")
        else:
            self._tb.insert(iterator, "\n\n%s" % lyrics)

    @blautil.idle
    def _clear_text_buffer(self):
        self._tb.delete(self._tb.get_start_iter(), self._tb.get_end_iter())

    def _on_player_state_changed(self, player):
        def fetch_lyrics():
            self._metadata_fetcher.fetch_lyrics(track, self._timestamp)
            self._timeout_id = 0
            return False

        if self._timeout_id:
            gobject.source_remove(self._timeout_id)

        track = player.get_track()
        if track == self._track:
            return
        state = player.get_state()

        self._clear_text_buffer()
        self._timestamp = gobject.get_current_time()

        if state == blaconst.STATE_STOPPED:
            self._track = None
        else:
            self._track = track
            self._timeout_id = gobject.timeout_add(250, fetch_lyrics)

