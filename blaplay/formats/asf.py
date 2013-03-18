# blaplay, Copyright (C) 2012-2013  Niklas Koep

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

from mutagen.asf import ASF as _Asf, error as AsfError

from _blatrack import BlaTrack
from blaplay.formats import TagParseError
from _identifiers import *


class Asf(BlaTrack):
    __slots__ = ("extensions", "__tag_to_literal", "__literal_to_tag")
    extensions = ["wma"]
    __tag_to_literal = {
        "Author": ARTIST,
        "Title": TITLE,
        "WM/AlbumTitle": ALBUM,
        "WM/Genre": GENRE,
        "WM/Composer": COMPOSER,
        "WM/AlbumArtist": ALBUM_ARTIST,
        "WM/TrackNumber": TRACK,
        "WM/PartOfSet": DISC,
        "WM/Year": DATE,

        # additional information that might be of interest
        "WM/ISRC": "isrc",
        "WM/EncodedBy": "encoder",
        "WM/Publisher": "publisher",
        "WM/AuthorURL": "website"
    }
    __literal_to_tag = dict(
        zip(__tag_to_literal.values(), __tag_to_literal.keys()))

    def _read_tags(self):
        try:
            audio = _Asf(self.uri)
        except AsfError:
            raise TagParseError

        for key, values in (audio.tags or {}).iteritems():
            try:
                values = map(unicode, values)
                self[self.__tag_to_literal[key]] = values
            except UnicodeDecodeError:
                pass
            except KeyError:
                self[key] = values

        self._parse_info(audio.info)
        self[FORMAT] = "WMA"
        self[ENCODING] = "lossy"

    def _save(self):
        try:
            audio = _Asf(self.uri)
            tags = audio.tags
        except (IOError, AsfError):
            return False

        try:
            for tag in self._deleted_tags:
                try:
                    del audio[tag]
                except KeyError:
                    pass
            self._deleted_tags.clear()
        except AttributeError:
            pass

        for identifier in self.keys_tags():
            try:
                values = self.get(identifier)
                if not values:
                    raise KeyError
            except KeyError:
                continue

            try:
                tag = self.__literal_to_tag[identifier]
            except KeyError:
                tag = identifier
            tags[tag] = values

        audio.save()
        return True

