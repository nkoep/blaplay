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

import wave as _wave

from blaplay.formats import TagParseError
from _blatrack import BlaTrack
from _identifiers import *


class Wav(BlaTrack):
    __slots__ = ("extensions")
    extensions = ["wav"]

    def _read_tags(self):
        # the wave module uses fixed sampling rates. custom sampling rates are
        # therefore mapped to commonly used ones. additionally, it doesn't
        # detect compression modes like ADPCM. therefore we just specify
        # `lossless' as encoding type; it's not like these are common
        # use-cases anyway

        try: audio = _wave.open(self.path, "r")
        except _wave.Error: raise TagParseError

        self[SAMPLING_RATE] = audio.getframerate()
        self[CHANNELS] = audio.getnchannels()
        self[CHANNEL_MODE] = "Mono" if self[CHANNELS] == 1 else "Stereo"
        self[BITRATE] = (audio.getframerate() * 8 * audio.getsampwidth() *
                self[CHANNELS])
        self[LENGTH] = audio.getnframes() / audio.getframerate()
        self[FORMAT] = "WAVE"
        self[ENCODING] = "lossless"

        audio.close()

    def _save(self):
        # since WAVE files don't support tags we just return True here without
        # actually modifying the file. we also don't complain if a user tries
        # to store metadata for a WAVE file since we can just keep that as
        # metadata in our library. obviously this data is transient and lost if
        # a file is reparsed
        return True
