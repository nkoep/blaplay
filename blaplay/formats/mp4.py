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

from mutagen.mp4 import MP4 as _Mp4, error as Mp4Error

from _blatrack import BlaTrack
from blaplay.formats import TagParseError
from _identifiers import *


class Mp4(BlaTrack):
    __slots__ = ("extensions", "__tag_to_literal", "__literal_to_tag")
    extensions = ["aac", "m4a", "mp4"]
    # Freeform keys begin with "----" (four dashes).
    __tag_to_literal = {
        "\xa9ART": ARTIST,
        "\xa9nam": TITLE,
        "\xa9alb": ALBUM,
        "\xa9gen": GENRE,
        "\xa9wrt": COMPOSER,
        "aART": ALBUM_ARTIST,
        "\xa9day": DATE,
        "trkn": TRACK,
        "disk": DISC,

        # additional information that might be of interest
        "\xa9too": "encoder",
        "cprt": "copyright"
    }
    __literal_to_tag = dict(
        zip(__tag_to_literal.values(), __tag_to_literal.keys()))

    def _read_tags(self):
        try:
            audio = _Mp4(self.uri)
        except Mp4Error:
            raise TagParseError

        for key, values in (audio.tags or {}).iteritems():
            if key in ["disk", "trkn"]:
                value = ["%d/%d" % values[0]]
            elif key.startswith("----:"):
                key = key[5:]
                value = values
            elif self.__tag_to_literal.has_key(key):
                value = map(unicode, values)
            else:
                continue
            try:
                self[self.__tag_to_literal[key]] = value
            except KeyError:
                self[key] = value

        self._parse_info(audio.info)
        self[FORMAT] = "MPEG-4 AAC"
        self[ENCODING] = "lossy" if self[BITRATE] else "lossless"

    def _save(self):
        try:
            audio = _Mp4(self.uri)
        except IOError:
            return False

        try:
            for tag in self._deleted_tags:
                try:
                    del audio[tag]
                except KeyError:
                    try:
                        del audio["----:%s" % tag]
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

            # If a key is not from our specifically defined mapping dict it's a
            # freeform key so treat it accordingly.
            try:
                tag = self.__literal_to_tag[identifier]
            except KeyError:
                tag = "----:%s" % identifier
                values = [v.encode("utf-8") for v in values]

            # Track and disc numbers are stored as a list of tuples so handle
            # them separately.
            if identifier in [TRACK, DISC]:
                values = values.split("/")
                try:
                    v1 = int(values[0])
                except (IndexError, ValueError):
                    continue
                try:
                    v2 = int(values[1])
                except (IndexError, ValueError):
                    v2 = 0
                audio[tag] = [(v1, v2)]
            else:
                audio[tag] = values

        audio.save()
        return True

