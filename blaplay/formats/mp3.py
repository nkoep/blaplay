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
import struct
StructError = struct.error

from mutagen.mp3 import MP3 as _MP3, HeaderNotFoundError
from mutagen import id3

from _blatrack import BlaTrack
from blaplay.formats import TagParseError
from _identifiers import *

# This is a mapping between the Mutagen encoding constants and their string
# representations in Python.
ENC = {0: "iso-8859-1", 1: "utf-16", 2: "utf-16be", 3: "utf-8"}


def isascii(string):
    return ((len(string) == 0) or (ord(max(string)) < 128))


class Mp3(BlaTrack):
    __slots__ = (
        "extensions", "__idv3v1", "__tag_to_literal", "__literal_to_tag"
    )
    extensions = ["mp2", "mp3"]
    # Those are tags that we could get from id3v1 and id3v2. In case they're
    # not present in the id3v2 tags we check in id3v1.
    __id3v1 = [
        "TPE1", "TIT2", "TALB", "TDRC", "TCON", "TCOM", "TPE2", "TRCK", "TPOS"
    ]
    __tag_to_literal = {
        # default tags
        "TPE1": ARTIST,
        "TIT2": TITLE,
        "TALB": ALBUM,
        "TDRC": DATE,
        "TCON": GENRE,
        "TCOM": COMPOSER,
        "TPE2": PERFORMER,
        "TRCK": TRACK,
        "TPOS": DISC,

        # Additional tags as defined in ID3v2.4 which might be of interest.
        # Everything else is simply ignored, except for TXXX user tags.
        "TENC": "encoder",
        "TSSE": "encoder settings",
        "TDEN": "encoding time",
        "TDOR": "original release time",
        "TDRL": "release time",
        "TPUB": "publisher",
        "TSRC": "isrc",
        "WXXX": "url",
    }
    __literal_to_tag = dict(
        zip(__tag_to_literal.values(), __tag_to_literal.keys()))
    __literal_to_tag["ALBUM ARTIST"] = ALBUM_ARTIST

    def __parse_id3v1(self, string):
        frames = id3.ID3()
        try:
            tag, title, artist, album, year, comment, track, genre = \
                struct.unpack("3s30s30s30s4s29sBB", string)
        except StructError:
            return frames

        if tag != "TAG":
            return frames

        def fix_encoding(s):
            return s.split("\x00")[0].strip().decode("latin1")

        title, artist, album, year, comment = map(
            fix_encoding, [title, artist, album, year, comment])

        if title:
            frames["TIT2"] = id3.TIT2(encoding=3, text=title)
        if artist:
            frames["TPE1"] = id3.TPE1(encoding=3, text=[artist])
        if album:
            frames["TALB"] = id3.TALB(encoding=3, text=album)
        if year:
            frames["TDRC"] = id3.TDRC(encoding=3, text=year)
        if comment:
            frames["COMM"] = id3.COMM(
                encoding=3, lang="eng", desc="ID3v1 Comment", text=comment)

        if track and (track != 32 or string[-3] == "\x00"):
            frames["TRCK"] = id3.TRCK(encoding=3, text=str(track))

        if genre != 255:
            frames["TCON"] = id3.TCON(encoding=3, text=str(genre))
            frames["TCON"].text = frames["TCON"].genres

        return frames

    def _read_tags(self):
        def fix_encoding(args):
            text, enc = args
            if enc == 0:
                text = unicode(text).strip().encode("latin1")
                for enc in ["utf-8", "latin1"]:
                    try:
                        text = text.decode(enc)
                    except UnicodeError:
                        pass
                    else:
                        break
                else:
                    return None
            else:
                text = str(text).strip().decode("utf-8")
            return text

        try:
            audio = _MP3(self.uri)
        except HeaderNotFoundError:
            raise TagParseError
        tags = audio.tags or id3.ID3()
        tags_id3v1 = None

        # Get the tags to read. These are made up of the id3v1 tags and the
        # intersection of tags we might care about and tags that are actually
        # present in the id3v2 tags.
        ttr = set(self.__id3v1)
        other_tags = [k.split(":")[0] for k in tags.iterkeys()
                      if not k.startswith("TXXX")]
        ttr.update(set(self.__tag_to_literal.keys()).intersection(other_tags))

        for tag in ttr:
            identifier = self.__tag_to_literal[tag]
            try:
                frame = tags.getall(tag)[0]
                value = frame.url if tag == "WXXX" else frame.text
            except IndexError:
                if tag not in self.__id3v1:
                    continue
                elif tags_id3v1 is None:
                    with open(self.uri, "rb") as f:
                        f.seek(-128, os.SEEK_END)
                        tags_id3v1 = self.__parse_id3v1(f.read(128))
                try:
                    frame = tags_id3v1.getall(tag)[0]
                    value = frame.text
                except IndexError:
                    continue

            enc = frame.encoding
            self[identifier] = map(
                fix_encoding, zip(value, [enc] * len(value)))

        # Get all custom tags.
        for tag in tags.getall("TXXX"):
            # ALBUM ARTIST user tags (as written by older fb2k versions)
            # receive special treatment.
            if tag.desc == "ALBUM ARTIST":
                tag.desc = ALBUM_ARTIST
            enc = frame.encoding
            self[tag.desc] = map(
                fix_encoding, zip(tag.text, [enc] * len(value)))

        self._parse_info(audio.info)
        self[FORMAT] = "MP3"
        self[ENCODING] = "lossy"

    def _save(self):
        try:
            audio = _MP3(self.uri)
            tags = audio.tags
            if tags is None:
                audio.add_tags()
                tags = audio.tags
        except IOError:
            tags = id3.ID3()

        delall = tags.delall
        try:
            for identifier in self._deleted_tags:
                try:
                    tag = self.__literal_to_tag[identifier]
                except KeyError:
                    tag = "TXXX:%s" % identifier
                delall(tag)
            self._deleted_tags.clear()
        except AttributeError:
            pass

        for identifier in self.keys_tags():
            text = self.get(identifier)
            if not text:
                continue

            # UTF-8 is ASCII-compatible
            if isascii("\n".join(text)):
                encoding = 3
            else:
                encoding = 1
            kwargs = dict(encoding=encoding, text=text)

            try:
                tag = self.__literal_to_tag[identifier]
                delall(tag)
            except KeyError:
                tag = "TXXX"
                if identifier == ALBUM_ARTIST:
                    identifier = "ALBUM ARTIST"
                else:
                    identifier = identifier.upper()
                kwargs["desc"] = identifier
                delall("%s:%s" % (tag, identifier))

            tags.add(id3.Frames[tag](**kwargs))

        try:
            audio.save()
        except NameError:
            tags.save(self.uri)
            return False
        return True

