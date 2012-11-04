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

from mutagen.oggvorbis import OggVorbis
from mutagen.oggflac import OggFLAC
from mutagen.flac import FLAC

from blaplay import blautils
from _blatrack import BlaTrack
from _identifiers import *


class Xiph(BlaTrack):
    __slots__ = (
        "__ext_to_format", "extensions", "__tag_to_literal",
        "__literal_to_tag", "__split_keys"
    )
    __ext_to_format = {
        "ogg": (OggVorbis, "OGG Vorbis", "lossy"),
        "oga": (OggVorbis, "OGG Vorbis", "lossy"),
        "ogx": (OggVorbis, "OGG Vorbis", "lossy"),
        "flac": (FLAC, "FLAC", "lossless"),
        "oggflac": (OggFLAC, "Ogg FLAC", "lossless")
    }
    extensions = __ext_to_format.keys()
    __tag_to_literal = {
        "artist": ARTIST,
        "title": TITLE,
        "album": ALBUM,
        "genre": GENRE,
        "performer": PERFORMER,
        "albumartist": ALBUM_ARTIST,
        "date": DATE,
        "isrc": "isrc",
        "version": "version",
        "copyright": "copyright"
    }
    __literal_to_tag = dict(
            zip(__tag_to_literal.values(), __tag_to_literal.keys()))
    __split_keys = {
        TRACK: ("tracknumber", "totaltracks"),
        DISC: ("discnumber", "totaldiscs")
    }

    def _read_tags(self):
        uri = self.uri
        baseclass, format, encoding = self.__ext_to_format[
                blautils.get_extension(uri)]
        audio = baseclass(uri)

        for key, values in (audio.tags or {}).iteritems():
            try: identifier = self.__tag_to_literal[key]
            except KeyError: identifier = key
            self[identifier] = map(unicode, values)

        # in vorbis comments tracknumber and number of total tracks are stored
        # in different keys. the same goes for discs. we construct the form we
        # normally work with here
        for identifier, (num, total) in self.__split_keys.iteritems():
            if num in self.keys_tags():
                self[identifier] = self.pop(num)
            if self[identifier] and total in self.keys_tags():
                self[identifier] += "/" + self.pop(total)

        self._parse_info(audio.info)
        self[FORMAT] = format
        self[ENCODING] = encoding

    def _save(self):
        uri = self.uri
        baseclass, format, encoding = self.__ext_to_format[
                blautils.get_extension(uri)]
        try: audio = baseclass(uri)
        except IOError: return False
        tags = audio.tags
        if tags is None:
            audio.add_tags()
            tags = audio.tags

        try:
            for tag in self._deleted_tags:
                try: del tags[tag]
                except KeyError: pass
            self._deleted_tags.clear()
        except AttributeError: pass

        for identifier in self.keys_tags():
            try:
                values = self.get(identifier)
                if not values: raise KeyError
            except KeyError: continue

            try: tag = self.__literal_to_tag[identifier]
            except KeyError: tag = identifier

            if identifier in self.__split_keys:
                num, total = self.__split_keys[identifier]
                values = values.split("/", 1)
                tags[num] = values[0]
                if (len(values) > 1 and
                        total not in self.keys_tags()):
                    tags[total] = values[1]
            else: tags[tag] = values

        audio.save()
        return True

