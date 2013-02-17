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

N_IDENTIFIERS = 21

(ARTIST, TITLE, ALBUM, DATE, GENRE, COMPOSER, PERFORMER, ALBUM_ARTIST, TRACK,
 DISC, URI, MONITORED_DIRECTORY, MTIME, FILESIZE, LENGTH, SAMPLING_RATE,
 CHANNELS, CHANNEL_MODE, BITRATE, FORMAT, ENCODING) = xrange(N_IDENTIFIERS)

IDENTIFIER_LABELS = [
    # tags
    "Artist name", "Track title", "Album title", "Year", "Genre", "Composer",
    "Performer", "Album artist", "Track", "Disc",

    # properties
    "Path", "Monitored directory", "Last modified", "Filesize", "Duration",
    "Sampling rate", "Channels", "Channel mode", "Bitrate", "Format",
    "Encoding"
]

IDENTIFIER_TAGS = xrange(10)
IDENTIFIER_PROPERTIES = xrange(10, N_IDENTIFIERS)

