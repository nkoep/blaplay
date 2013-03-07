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

import os

VERSION = "0.1"
APPNAME = "blaplay"
COMMENT = "A bla that plays"
WEB = "http://nkoep.github.com/blaplay"
AUTHOR = "Niklas Koep"
AUTHORS = sorted(
    [AUTHOR])
EMAIL = "niklas.koep@gmail.com"
COPYRIGHT = "Copyright © 2012-2013 %s\n<%s>" % (AUTHOR, EMAIL)
CFG_TIMEOUT = 30

# Directories
USERDIR = os.path.join(os.path.expanduser("~"), ".%s" % APPNAME)
CACHEDIR = os.path.join(USERDIR, "cache")
BASEDIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
IMAGES_PATH = os.path.join(BASEDIR, "images")
ICONS_PATH = os.path.join(IMAGES_PATH, "icons")
COVERS = os.path.join(CACHEDIR, "covers")
ARTISTS = os.path.join(CACHEDIR, "artists")
RELEASES = os.path.join(CACHEDIR, "releases")
EVENTS = os.path.join(CACHEDIR, "events")

# Files
CFG_PATH = os.path.join(USERDIR, "config")
PIDFILE = os.path.join(USERDIR, "pid")
LIBRARY_PATH = os.path.join(USERDIR, "library")
OOL_PATH = os.path.join(USERDIR, "ool")
PLAYLISTS_PATH = os.path.join(USERDIR, "playlists")
METADATA_PATH = os.path.join(USERDIR, "metadata")
SCROBBLES_PATH = os.path.join(USERDIR, "scrobbles")
STATIONS_PATH = os.path.join(USERDIR, "stations")
RELEASES_PATH = os.path.join(USERDIR, "releases")
EVENTS_PATH = os.path.join(USERDIR, "events")
WISDOM_PATH = os.path.join(USERDIR, "wisdom")
LOGO = os.path.join(IMAGES_PATH, "logo.svg")
COVER = os.path.join(IMAGES_PATH, "cover.svg")

# last.fm
LASTFM_APIKEY = "38fcb93ce36693485715ea4197de49de"
LASTFM_SECRET = "18503e42d49e15bcd709bbdecdcf8682"
LASTFM_BASEURL = ("http://ws.audioscrobbler.com/2.0/?api_key=%s&format=json"
        % LASTFM_APIKEY)
LASTFM_LOGO = os.path.join(IMAGES_PATH, "lastfm.gif")

# Player constants
STATE_PLAYING, STATE_PAUSED, STATE_STOPPED = xrange(3)
TRACK_PLAY, TRACK_NEXT, TRACK_PREVIOUS, TRACK_RANDOM = xrange(4)
EQUALIZER_BANDS = 10

# Main menu
MENU = """
<ui>
    <menubar name="Menu">
        <menu action="File">
            <menuitem action="OpenPlaylist"/>
            <menuitem action="AddFiles"/>
            <menuitem action="AddDirectories"/>
            <menuitem action="SavePlaylist"/>
            <separator/>
            <menuitem action="Quit"/>
        </menu>
        <menu action="Edit">
            <menuitem action="AddNewPlaylist"/>
            <menuitem action="RemovePlaylist"/>
            <menuitem action="Clear"/>
            <menuitem action="LockUnlockPlaylist"/>
            <menu action="Select">
                <menuitem action="SelectAll"/>
                <menuitem action="SelectComplement"/>
                <menuitem action="SelectByArtist"/>
                <menuitem action="SelectByAlbum"/>
                <menuitem action="SelectByAlbumArtist"/>
                <menuitem action="SelectByGenre"/>
            </menu>
            <menu action="Selection">
                <menuitem action="Cut"/>
                <menuitem action="Copy"/>
                <menuitem action="Remove"/>
            </menu>
            <menuitem action="Paste"/>
            <menu action="NewPlaylistFrom">
                <menuitem action="PlaylistFromSelection"/>
                <menuitem action="PlaylistFromArtists"/>
                <menuitem action="PlaylistFromAlbums"/>
                <menuitem action="PlaylistFromAlbumArtists"/>
                <menuitem action="PlaylistFromGenre"/>
            </menu>
            <separator/>
            <menuitem action="RemoveDuplicates"/>
            <menuitem action="RemoveInvalidTracks"/>
            <menuitem action="Search"/>
            <separator/>
            <menuitem action="Preferences"/>
        </menu>
        <menu action="PlayOrder">
            <menuitem action="OrderNormal"/>
            <menuitem action="OrderRepeat"/>
            <menuitem action="OrderShuffle"/>
        </menu>
        <menu action="View">
            <menuitem action="Playlists"/>
            <menuitem action="Queue"/>
            <menuitem action="Radio"/>
            <menuitem action="RecommendedEvents"/>
            <menuitem action="NewReleases"/>
            <separator/>
            <menuitem action="Browsers"/>
            <menuitem action="PlaylistTabs"/>
            <menuitem action="SidePane"/>
            <menuitem action="Statusbar"/>
            <menuitem action="Visualization"/>
            <separator/>
            <menuitem action="JumpToPlayingTrack"/>
        </menu>
        <menu action="Help">
            <menuitem action="About"/>
        </menu>
    </menubar>
</ui>
"""
def _builder(base, items):
    return [base % item for item in items]
MENU_PLAYLISTS = _builder(
    "/Menu/%s",
    ["File/AddFiles", "File/AddDirectories", "File/SavePlaylist",
     "Edit/AddNewPlaylist", "Edit/RemovePlaylist",
     "Edit/LockUnlockPlaylist", "Edit/NewPlaylistFrom", "Edit/Search",
     "View/PlaylistTabs", "View/JumpToPlayingTrack"])
MENU_EDIT = _builder(
    "/Menu/Edit/%s",
    ["Paste", "Clear", "Select", "Select/SelectAll",
     "Select/SelectComplement", "Selection/Cut", "Selection/Copy",
     "Selection/Remove", "RemoveDuplicates", "RemoveInvalidTracks"] +
    _builder("Select/Select%s", ["All", "ByArtist", "ByAlbum",
                                 "ByAlbumArtist", "ByGenre"]))
MENU_ORDER = _builder("/Menu/PlayOrder/%s",
                      ["OrderNormal", "OrderRepeat", "OrderShuffle"])
MENU_VIEWS = _builder("/Menu/View/%s", ["Playlists", "Queue", "Radio",
                                        "RecommendedEvents", "NewReleases"])
del _builder

# Library and browser constants
(ORGANIZE_BY_DIRECTORY, ORGANIZE_BY_ARTIST, ORGANIZE_BY_ARTIST_ALBUM,
 ORGANIZE_BY_ALBUM, ORGANIZE_BY_GENRE, ORGANIZE_BY_YEAR) = xrange(6)

BROWSER_LIBRARY, BROWSER_FILESYSTEM = xrange(2)
(ACTION_SEND_TO_CURRENT, ACTION_ADD_TO_CURRENT, ACTION_SEND_TO_NEW,
 ACTION_EXPAND_COLLAPSE) = xrange(4)

# View constants
VIEW_PLAYLISTS, VIEW_QUEUE, VIEW_RADIO, VIEW_EVENTS, VIEW_RELEASES = xrange(5)
(SELECT_ALL, SELECT_COMPLEMENT, SELECT_BY_ARTISTS, SELECT_BY_ALBUMS,
 SELECT_BY_ALBUM_ARTISTS, SELECT_BY_GENRES) = xrange(6)

# Playlist constants
QUEUE_MAX_ITEMS = 128
ORDER_NORMAL, ORDER_REPEAT, ORDER_SHUFFLE = xrange(3)
ORDER_LITERALS = ["Normal", "Repeat", "Shuffle"]
#ORDER = ["Normal", "Repeat", "Repeat album", "Shuffle", "Shuffle albums"]
(PLAYLIST_FROM_SELECTION, PLAYLIST_FROM_ARTISTS, PLAYLIST_FROM_ALBUMS,
 PLAYLIST_FROM_ALBUM_ARTISTS, PLAYLIST_FROM_GENRE) = xrange(5)

METADATA_LYRICS, METADATA_BIOGRAPHY = xrange(2)

# Events browser
EVENTS_RECOMMENDED, EVENTS_ALL = xrange(2)

# Releases browser
NEW_RELEASES_FROM_LIBRARY, NEW_RELEASES_RECOMMENDED = xrange(2)

