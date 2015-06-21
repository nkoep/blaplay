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
from collections import OrderedDict

import gtk

VERSION = "0.1.0"
APPNAME = "blaplay"
COMMENT = "A bla that plays"
WEB = "http://nkoep.github.com/blaplay"
AUTHOR = "Niklas Koep"
AUTHORS = sorted(
    [AUTHOR])
EMAIL = "niklas.koep@gmail.com"
COPYRIGHT = "Copyright © 2012-2013 %s\n<%s>" % (AUTHOR, EMAIL)
GST_REQUIRED_VERSION = "0.10"

# Directories
USERDIR = os.path.join(os.path.expanduser("~"), ".%s" % APPNAME)
CACHEDIR = os.path.join(USERDIR, "cache")
BASEDIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
IMAGES_PATH = os.path.join(BASEDIR, "images")
ICONS_PATH = os.path.join(IMAGES_PATH, "icons")
COVERS = os.path.join(CACHEDIR, "covers")
ARTISTS = os.path.join(CACHEDIR, "artists")

# Files
CONFIG_PATH = os.path.join(USERDIR, "config")
PIDFILE = os.path.join(USERDIR, "pid")
LIBRARY_PATH = os.path.join(USERDIR, "library")
OOL_PATH = os.path.join(USERDIR, "ool")
PLAYLISTS_PATH = os.path.join(USERDIR, "playlists")
METADATA_PATH = os.path.join(USERDIR, "metadata")
SCROBBLES_PATH = os.path.join(USERDIR, "scrobbles")
STATIONS_PATH = os.path.join(USERDIR, "stations")
WISDOM_PATH = os.path.join(USERDIR, "wisdom")
LOGO = os.path.join(IMAGES_PATH, "logo.svg")
COVER = os.path.join(IMAGES_PATH, "cover.svg")

# last.fm
LASTFM_APIKEY = "38fcb93ce36693485715ea4197de49de"
LASTFM_SECRET = "18503e42d49e15bcd709bbdecdcf8682"
LASTFM_BASEURL = ("http://ws.audioscrobbler.com/2.0/?api_key=%s&format=json" %
                  LASTFM_APIKEY)
LASTFM_LOGO = os.path.join(IMAGES_PATH, "lastfm.gif")

# Player constants
STATE_PLAYING, STATE_PAUSED, STATE_STOPPED = range(3)
TRACK_PLAY, TRACK_NEXT, TRACK_PREVIOUS, TRACK_RANDOM = range(4)
EQUALIZER_BANDS = 10

BORDER_PADDING = 3
WIDGET_SPACING = gtk.HPaned().style_get_property("handle_size")

# Library and browser constants
(ORGANIZE_BY_DIRECTORY, ORGANIZE_BY_ARTIST, ORGANIZE_BY_ARTIST_ALBUM,
 ORGANIZE_BY_ALBUM, ORGANIZE_BY_GENRE, ORGANIZE_BY_YEAR) = range(6)

BROWSER_LIBRARY, BROWSER_FILESYSTEM = range(2)
(ACTION_SEND_TO_CURRENT, ACTION_ADD_TO_CURRENT, ACTION_SEND_TO_NEW,
 ACTION_EXPAND_COLLAPSE) = range(4)

# View constants
VIEW_PLAYLIST = 0
(VIEW_PLAYLISTS, VIEW_QUEUE, VIEW_VIDEO, VIEW_TAG_EDITOR,
 VIEW_PREFERENCES) = range(5)
(SELECT_ALL, SELECT_COMPLEMENT, SELECT_BY_ARTISTS, SELECT_BY_ALBUMS,
 SELECT_BY_ALBUM_ARTISTS, SELECT_BY_GENRES) = range(6)

# Playlist constants
TAG_EDITOR_MAX_ITEMS = QUEUE_MAX_ITEMS = 128
ORDER_NORMAL, ORDER_REPEAT, ORDER_SHUFFLE = range(3)
ORDER_LITERALS = OrderedDict([
    ("Normal", ORDER_NORMAL), ("Repeat", ORDER_REPEAT),
    ("Shuffle", ORDER_SHUFFLE)
])
#ORDER = ["Normal", "Repeat", "Repeat album", "Shuffle", "Shuffle albums"]
(PLAYLIST_FROM_SELECTION, PLAYLIST_FROM_ARTISTS, PLAYLIST_FROM_ALBUMS,
 PLAYLIST_FROM_ALBUM_ARTISTS, PLAYLIST_FROM_GENRE) = range(5)

(METADATA_TAGS, METADATA_PROPERTIES, METADATA_LYRICS) = range(3)

