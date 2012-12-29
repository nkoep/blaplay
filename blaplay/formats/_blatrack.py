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

from blaplay.blacore import blacfg, blaconst, bladb
from blaplay import blautil
ignore = bladb.BlaLibraryMonitor.ignore
from blaplay.formats import TagParseError
from _identifiers import *


class BlaTrack(dict):
    __slots__ = ("_deleted_tags")

    def __init__(self, path):
        self[MTIME] = os.path.getmtime(path)
        self[FILESIZE] = os.path.getsize(path)
        self[URI] = path

        self._read_tags()

    def __getstate__(self):
        return self.items()

    def __setstate__(self, state):
        for item, value in state: self[item] = value

    def __delitem__(self, key):
        # tags that are specifically removed in the tag editor are removed and
        # then added to a special set that we check when writing tags to file.
        # by default, if we have a key in our dict with an empty value we just
        # ignore the tag instead of deleting it
        try: dict.__delitem__(self, key)
        except KeyError: pass
        if not hasattr(self, "_deleted_tags"): self._deleted_tags = set()
        self._deleted_tags.add(key)

    def __getitem__(self, key):
        # we overwrite the default getter to only return the first entry from
        # a tag which might have been constructed from multiple values. for
        # actually writing tags back to a file the `get()' method should be
        # used
        try: item = dict.__getitem__(self, key)
        except KeyError: return ""
        try:
            if not isinstance(item, list): raise IndexError
            return item[0]
        except IndexError: return item

    def _parse_info(self, info):
        self[SAMPLING_RATE] = info.sample_rate

        # info classes of lossless formats (usually/probably) don't define
        # bitrate attributes
        try:
            self[BITRATE] = info.bitrate
        except AttributeError: self[BITRATE] = 0

        try: mode = info.mode
        except AttributeError:
            channels = info.channels
            if channels == 0: mode = channels = ""
            else: mode = "Mono" if channels == 1 else "Stereo"
        else:
            # MPEGInfo has a mode attribute to specify the number of channels
            channels = 2 if 0 <= mode <= 2 else 1
            if mode == 0: mode = "Stereo"
            elif mode == 1: mode = "Joint-stereo"
            elif mode == 2: mode = "Dual channel"
            else: mode = "Mono" # mode == 3

        self[CHANNELS] = channels
        self[CHANNEL_MODE] = mode
        self[LENGTH] = int(info.length)

    def save(self):
        # this makes sure the next EVENT_CHANGED event for this file is ignored
        # by the library monitor as otherwise we'd update everything twice
        ignore.add(self[URI])
        status = self._save()
        self[MTIME] = os.path.getmtime(self[URI])
        return status

    def keys_tags(self):
        # this returns every key that corresponds to a tag as opposed to an
        # attribute like filesize, etc.
        return list(set(self.keys()).difference(IDENTIFIER_PROPERTIES))

    def keys_additional_tags(self):
        # this returns every key that corresponds to a tag that does not have
        # a numeric identifier as defined in formats._identifiers
        return list(set(self.keys()).difference(xrange(N_IDENTIFIERS)))

    def get_cover_basepath(self):
        if "" in [self[ARTIST], self[ALBUM]]: return ""
        base = "%s-%s" % (self[ARTIST].replace(" ", "_"),
                self[ALBUM].replace(" ", "_"))
        base = base.replace("/", "_")
        return os.path.join(blaconst.COVERS, base)

    def get_lyrics_key(self):
        if "" in [self[ARTIST], self[TITLE]]: return ""
        lyrics_key = "%s-%s" % (
                self[ARTIST].replace(" ", "_").replace("/", "_"),
                self[TITLE].replace(" ", "_").replace("/", "_")
        )
        return lyrics_key

    def get_filesize(self, short=False):
        filesize = "%.2f MB" % float(self[FILESIZE] / (1024. ** 2))
        if not short: filesize += " (%d bytes)" % self[FILESIZE]
        return filesize

    @property
    def duration(self):
        m, s = divmod(self[LENGTH], 60)
        h, x = divmod(m, 60)
        return "%d:%02d:%02d" % (h, m, s) if h else "%d:%02d" % (m, s)

    uri = property(lambda self: self[URI])
    basename = property(lambda self: os.path.basename(
            blautil.toss_extension(self.uri)))
    bitrate = property(lambda self: "%d kbps" % (self[BITRATE] / 1000)
            if self[BITRATE] else "")
    sampling_rate = property(lambda self: "%d Hz" % self[SAMPLING_RATE]
            if self[SAMPLING_RATE] else "")

