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

from blaplay.blacore import blaconst


class _BlaTracklistDelegateMixin(object):
    def current_tab_is_tracklist(self):
        tab = self._get_current_tab()
        return (tab.ID == blaconst.VIEW_PLAYLIST or
                tab.ID == blaconst.VIEW_QUEUE)

    def enter_search_mode(self):
        if self.current_tab_is_tracklist():
            tab = self._get_current_tab()
            tab.enable_search()

class _BlaPlaylistDelegateMixin(object):
    def _get_current_tab_as_playlist(self):
        if not self.current_tab_is_playlist():
            return None
        return self._get_current_tab()

    def current_tab_is_playlist(self):
        tab = self._get_current_tab()
        return tab.ID == blaconst.VIEW_PLAYLIST

    def add_new_playlist(self):
        self._view_managers[blaconst.VIEW_PLAYLIST].add_playlist(
            request_focus=True)

    def open_playlist(self):
        self._view_managers[blaconst.VIEW_PLAYLIST].open_playlist()

    def save_current_playlist(self):
        playlist = self._get_current_tab_as_playlist()
        if playlist is None:
            return
        self._view_managers[blaconst.VIEW_PLAYLIST].save_playlist(playlist)

    def add_files_to_current_playlist(self):
        playlist = self._get_current_tab_as_playlist()
        if playlist is None:
            return
        self._view_managers[blaconst.VIEW_PLAYLIST].add_files_to_playlist(
            playlist)

    def add_directories_to_current_playlist(self):
        playlist = self._get_current_tab_as_playlist()
        if playlist is None:
            return
        self._view_managers[
            blaconst.VIEW_PLAYLIST].add_directories_to_playlist(playlist)

    def jump_to_playing_track(self):
        self._view_managers[blaconst.VIEW_PLAYLIST].jump_to_playing_track()

    def send_uris_to_current_playlist(self, uris):
        playlist = self._get_current_tab_as_playlist()
        if playlist is None:
            return
        self._view_managers[blaconst.VIEW_PLAYLIST].send_uris_to_playlist(
            playlist, uris)

    def add_uris_to_current_playlist(self, uris):
        playlist = self._get_current_tab_as_playlist()
        if playlist is None:
            return
        self._view_managers[blaconst.VIEW_PLAYLIST].add_uris_to_playlist(
            playlist, uris)

    def send_uris_to_new_playlist(self, name, uris):
        self._view_managers[blaconst.VIEW_PLAYLIST].send_uris_to_new_playlist(
            name=name, uris=uris)

class _BlaPreferencesDelegateMixin(object):
    def show_preferences(self):
        self._view_managers[blaconst.VIEW_PREFERENCES].show_preferences()

class BlaViewDelegate(_BlaPlaylistDelegateMixin, _BlaTracklistDelegateMixin,
                      _BlaPreferencesDelegateMixin):
    """
    This class abstracts away the views system. Intended consumers are the UI
    manager which implements the global menu bar, as well as the browser
    classes which use the view delegate to send media resources to playlists,
    tag editors or the queue.
    """

    def __init__(self, tab_view, view_managers):
        self._tab_view = tab_view
        self._view_managers = view_managers

    def _get_current_tab(self):
        return self._tab_view.get_current_view()

    def current_tab_is_locked(self):
        view = self._get_current_tab()
        return view.locked()

    def current_tab_toggle_lock(self):
        view = self._get_current_tab()
        view.toggle_lock()

    def close_current_tab(self):
        view = self._get_current_tab()
        view.remove()

