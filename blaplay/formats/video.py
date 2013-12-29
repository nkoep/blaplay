# blaplay, Copyright (C) 2013  Niklas Koep

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

from blaplay.blacore import blagst as gst
from _blatrack import BlaTrack
from blaplay.formats import TagParseError
from _identifiers import *


class Video(BlaTrack):
    __slots__ = ("extensions", "__tag_to_literal", "__literal_to_tag",
                 "__split_keys", "__discoverer")
    extensions = ["avi", "flv", "mkv", "wmv", "mp4", "webm", "divx", "m2v",
                  "mov", "mpg"]
    __tag_to_literal = {
        gst.TAG_ARTIST: ARTIST,
        gst.TAG_TITLE: TITLE,
        gst.TAG_ALBUM: ALBUM,
        gst.TAG_GENRE: GENRE,
        gst.TAG_COMPOSER: COMPOSER,
        gst.TAG_ALBUM_ARTIST: ALBUM_ARTIST,
        gst.TAG_DATE: DATE,

        # Additional information that might be of interest.
        gst.TAG_ISRC: "isrc",
        gst.TAG_ENCODER: "encoder",
        gst.TAG_HOMEPAGE: "website"
    }
    __split_keys = {
        TRACK: (gst.TAG_TRACK_NUMBER, gst.TAG_TRACK_COUNT),
        DISC: (gst.TAG_ALBUM_VOLUME_NUMBER, gst.TAG_ALBUM_VOLUME_COUNT)
    }
    __literal_to_tag = dict(
        zip(__tag_to_literal.values(), __tag_to_literal.keys()))
    __discoverer = gst.pbutils.Discoverer(gst.SECOND)

    def _parse_info(self, info):
        tags = info.get_tags()
        self[FORMAT] = tags["container-format"]
        self[LENGTH] = int(info.get_duration() / gst.SECOND)

    def _read_tags(self):
        # FIXME: this method can quite often block the main loop or at least
        #        slow it down a lot to create jerky animations in the
        #        visualizations. maybe we should look into the async methods

        try:
            info = self.__discoverer.discover_uri("file://%s" % self.uri)
        except gst.GError:
            raise TagParseError
        tags = info.get_tags()

        for key in tags.keys():
            try:
                value = unicode(tags[key])
                self[self.__tag_to_literal[key]] = value
            except UnicodeDecodeError:
                pass
            except KeyError:
                self[key] = value

        self._parse_info(info)

    def _save(self):
        print_d("TODO")
        return True

