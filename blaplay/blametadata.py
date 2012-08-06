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
import shutil
import sys
import urllib

import gobject
import libxml2

import blaplay
from blaplay import blaconst, blautils, blafm
from blaplay.formats._identifiers import *

FORMAT_XML, FORMAT_HTML = xrange(2)


class BlaFetcher(gobject.GObject):
    __gsignals__ = {
        "cover": blaplay.signal(2),
        "lyrics": blaplay.signal(1),
        "biography": blaplay.signal(2)
    }

    __track = None
    __tid = -1

    def __init__(self):
        super(BlaFetcher, self).__init__()

    def __parse_buffer(self, buf, locator, format):
        lyrics = ""

        # parse lyrics
        if format == FORMAT_XML:
            f = libxml2.readMemory
            flags = libxml2.XML_PARSE_NOERROR | libxml2.XML_PARSE_NOWARNING
        elif format == FORMAT_HTML:
            f = libxml2.htmlReadMemory
            flags = libxml2.HTML_PARSE_NOERROR | libxml2.HTML_PARSE_NOWARNING
        else: return lyrics

        # FIXME: this is recently raised by wikia replies :EE
        try: doc = f(buf, len(buf), None, "utf-8", flags)
        except (libxml2.treeError, TypeError): return lyrics

        ctx = doc.xpathNewContext()
        if not ctx: return lyrics

        obj = ctx.xpathEval(locator)
        if not obj: return lyrics

        lyrics = obj[0].getContent().strip()

        ctx.xpathFreeContext()
        doc.freeDoc()

        return lyrics

    def __download_lyrics(self, url, artist, title, separator):
        buf = None
        new_url = url % (artist.replace(" ", separator).replace("&", "and"),
                title.replace(" ", separator).replace("&", "and"))

        safestring = ":/?=+&%s" % separator
        new_url = urllib.quote(new_url.encode("utf-8"), safe=safestring)

        blaplay.print_d(new_url)

        try: f = urllib.urlopen(new_url)
        except IOError: return buf
        buf = f.read()
        f.close()
        return buf

    @blautils.thread
    def __fetch_lyrics(self):
        track = self.__track
        lyrics = None

        if not track or not track.get_lyrics_key():
            print track.get_lyrics_key()
            self.emit("lyrics", lyrics)
            return lyrics

        artist = track[ARTIST]
        title = track[TITLE]
        lyrics_key = track.get_lyrics_key()

        # try locally stored lyrics first
        lyrics = blaplay.get_metadata("lyrics", lyrics_key)
        if lyrics:
            self.emit("lyrics", lyrics)
            return

        # try to download lyrics
        resources = [
            ("http://lyrics.wikia.com/api.php?action=query&prop=revisions&"
             "rvprop=content&format=xml&titles=%s:%s", artist, title, "_",
             "//rev", FORMAT_XML),
            ("http://www.lyricsmania.com/%s_lyrics_%s.html", title,
             artist, "_", "//*[@id=\"songlyrics_h\"]", FORMAT_HTML),
            ("http://www.lyricstime.com/%s-%s-lyrics.html", artist,
             title, "-", "//*[@id=\"songlyrics\"]", FORMAT_HTML),
            ("http://megalyrics.ru/lyric/%s/%s.htm", artist, title, "_",
             "//pre[@class=\"lyric\"]", FORMAT_HTML)
        ]

        # FIXME: line feeds in results from megalyrics are somehow removed

        for url, artist, title, separator, locator, format in resources:
            # TODO: add safestrings for the different lyrics sources (namely
            #       the separators)
            if url.find("wikia") != -1:
                artist = artist.replace("'", " ").replace(".", separator)
                title = title.replace("'", " ").replace(".", separator)
            else:
                artist = artist.replace(".", separator)
                title = title.replace(".", separator)

            # TODO: remove leading, trailing and consecutive separators (strip)
            """
            from string import letters
            s = "The quick brown fox jumps over the lazy dog"
            "".join([c for idx, c in enumerate(s) if c in letters or
                    not c in s[:idx]])
            """

            # FIXME: replace all non-ascii characters with a separator
            #        character or define safestrings as suggested above
            #        "".join([x if ord(x) < 128 else "?" for x in s])

            buf = self.__download_lyrics(url, artist, title, separator)
            if not buf: continue
            lyrics = self.__parse_buffer(buf, locator, format)

            if (lyrics and lyrics[0] == "#" and lyrics.lower().find("redirect")
                    != -1):
                artist, title = lyrics.split("[")[-1].split("]")[0].split(":")
                buf = self.__download_lyrics(url, artist, title, separator)
                lyrics = self.__parse_buffer(buf, locator, format)

            # results from wikia need to be parsed again
            if lyrics and url.find("wikia") != -1:
                lyrics = self.__parse_buffer(lyrics, "//lyrics", FORMAT_HTML)

            if lyrics: break

        # if lyrics were found, store them locally
        if lyrics:
            lyrics = blautils.remove_html_tags(lyrics).strip()
            try: lyrics = lyrics.decode("utf-8", "replace")
            except (AttributeError, UnicodeDecodeError): pass
            blaplay.add_metadata("lyrics", lyrics_key, lyrics)

        self.emit("lyrics", lyrics)

    @blautils.thread
    def __fetch_cover(self, force_download=False):
        gobject.source_remove(self.__tid)
        track = self.__track
        cover = None

        image_base = track.get_cover_basepath()
        if not force_download:
            if os.path.isfile("%s.jpg" % image_base):
                cover = "%s.jpg" % image_base
            elif os.path.isfile("%s.png" % image_base):
                cover = "%s.png" % image_base

        if cover: self.emit("cover", cover, force_download)
        else:
            self.__tid = gobject.timeout_add(2000, lambda *x: self.emit(
                    "cover", blaconst.COVER, force_download))
            cover = blafm.get_cover(track, image_base)
            if cover != blaconst.COVER:
                gobject.source_remove(self.__tid)
                self.emit("cover", cover, force_download)

    @blautils.thread
    def __fetch_biography(self):
        track = self.__track
        image, biography = None, None
        if track[ARTIST]:
            # look for cached artist image
            image_base = os.path.join(blaconst.ARTISTS,
                    track[ARTIST].replace(" ", "_").replace("/", "_"))
            if os.path.isfile("%s.jpg" % image_base):
                image = "%s.jpg" % image_base
            elif os.path.isfile("%s.png" % image_base):
                image = "%s.png" % image_base

            # check if biography exists
            biography = blaplay.get_metadata("bio", track[ARTIST])

            if not biography or not image:
                image, biography = blafm.get_biography(track, image_base)
                if biography:
                    blaplay.add_metadata("bio", track[ARTIST], biography)

        self.emit("biography", image, biography)

    def start(self, track, cover_only=False):
        self.__track = track

        if cover_only:
            try:
                if not self.__thread_cover.is_alive():
                    self.__thread_cover = self.__fetch_cover(
                            force_download=True)
            except AttributeError: pass
        else:
            try:
                map(blautils.BlaThread.kill, [self.__thread_lyrics,
                        self.__thread_cover, self.__thread_biography])
            except AttributeError: pass

            self.__thread_lyrics = self.__fetch_lyrics()
            self.__thread_cover = self.__fetch_cover()
            self.__thread_biography = self.__fetch_biography()

    def set_cover(self, path=""):
        track = self.__track

        # stop any thread which might be busy with getting a cover
        self.__thread_cover.kill()

        # remove any old images (user-set or downloaded)
        if path != blaconst.COVER:
            image_base = track.get_cover_basepath()
            name = os.path.basename(image_base)
            images = [os.path.join(blaconst.COVERS, f) for f in
                    os.listdir(blaconst.COVERS) if f.startswith(name)]
            map(os.unlink, images)

        if path:
            cover = "%s.%s" % (image_base, blautils.get_extension(path))
            shutil.copy(path, cover)
        else: cover = blaconst.COVER

        self.emit("cover", cover, False)

