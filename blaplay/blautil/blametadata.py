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
import urllib2
import socket
import unicodedata
import re
import json
from HTMLParser import HTMLParser as HTMLParser_

import gobject

import blaplay
from blaplay import blaconst
from blaplay import blautil
from blaplay.blautil import blafm
from blaplay.formats._identifiers import *

TIMEOUT = 10


class BlaMetadata(object):
    pass

class BlaFetcher(gobject.GObject):
    __gsignals__ = {
        "cover": blautil.signal(2),
        "lyrics": blautil.signal(1),
        "biography": blautil.signal(2)
    }

    __track = None
    __tid = -1

    class JSONParser(object):
        def feed(self, feed, **kwargs):
            s = json.loads(feed)
            pages = s["query"]["pages"]
            try: lyrics = pages.values()[0]["revisions"][0]["*"]
            except KeyError: return ""
            try:
                lyrics = re.search(r"(<lyrics>)(.*)(</lyrics>)",
                        lyrics, re.UNICODE | re.DOTALL).group(2)
            except AttributeError: return ""
            return lyrics

    class HTMLParser(HTMLParser_):
        def feed(self, feed, tag, attr, ignore=""):
            self.__tag = tag
            self.__attr = attr

            self.__lyrics_tag_found = False
            self.__lyrics = ""

            try: HTMLParser_.feed(self, unicode(feed.encode("utf-8")))
            except UnicodeDecodeError: return ""
            return self.__lyrics[self.__lyrics.find(ignore) +
                    len(ignore):].strip()

        def handle_starttag(self, tag, attrs):
            if tag == self.__tag and self.__attr in attrs:
                self.__lyrics_tag_found = True
            if self.__lyrics_tag_found and tag == "br": self.__lyrics += "\n"

        def handle_endtag(self, tag):
            if tag == self.__tag: self.__lyrics_tag_found = False

        def handle_data(self, data):
            if self.__lyrics_tag_found: self.__lyrics += data.strip()

        def handle_charref(self, name):
            if self.__lyrics_tag_found:
                if name.startswith("x"): c = unichr(int(name[1:], 16))
                else: c = unichr(int(name))
                self.__lyrics += c

    def __init__(self):
        super(BlaFetcher, self).__init__()
        self.__json_parser = BlaFetcher.JSONParser()
        self.__html_parser = BlaFetcher.HTMLParser()

    def __download_feed(self, baseurl, separator, erase, replace, safe, artist,
            title):
        feed = None

        # erase site-specific characters
        re_ = re.compile(r"|".join(erase) or r"$^", flags=re.UNICODE)
        artist, title = [re_.sub("", s) for s in (artist, title)]

        # replace site-specific characters by the separator
        # FIXME: this check SHOULD be redundant
        re_ = re.compile(r"|".join(replace) or r"$^", flags=re.UNICODE)
        artist, title = [re_.sub(separator, s) for s in (artist, title)]

        # remove consecutive spaces and capitalize words (wikia is
        # case-sensitive)
        re_ = re.compile(r" +", re.UNICODE)
        artist, title = [re_.sub(" ", s).strip() for s in (artist, title)]
        re_ = re.compile(r"([\s\(\[\{])(\S)", re.UNICODE)
        artist, title = [re_.sub(lambda m: m.group(1) + m.group(2).upper(), s)
                for s in (artist, title)]

        # FIXME: should this really be done for all search engines
#        artist = artist.replace(".", separator)
#        title = title.replace(".", separator)

        url = baseurl.format(artist.replace(" ", separator).replace("&",
                "and"), title.replace(" ", separator).replace("&", "and"))

        # substitue composite letters and transliterate accents
        DICT = {
            u"æ": "ae", u"ð": "d", u"ø": "o", u"þ": "th", u"œ": "oe", u"ƒ": "f"
        }
        regexp = re.compile(
                "|".join(["(%s)" % key for key in DICT]), re.UNICODE)
        lookup = dict((idx+1, value)
                for idx, value in enumerate(DICT.itervalues()))
        url = regexp.sub(lambda mo: mo.expand(lookup[mo.lastindex]),
                unicode(url.encode("utf-8")))
        url = unicodedata.normalize(
                "NFKD", unicode(url)).encode("ascii", "ignore")

        # remove consecutive separators and quote url
        url = re.sub("%s+" % separator, separator, url, flags=re.UNICODE)
        url = urllib.quote(url, safe=":/?=+&%s%s" % (separator, safe))

        print_d(url)

        try: conn = urllib2.urlopen(url, timeout=TIMEOUT)
        except (IOError, socket.timeout): return feed
        else:
            encoding = conn.headers.getparam("charset")
            try: feed = conn.read()
            except socket.timeout: return feed
        try: feed = feed.decode(encoding).encode("utf-8")
        except (TypeError, UnicodeDecodeError): pass
        conn.close()
        return feed

    @blautil.thread
    def __fetch_lyrics(self):
        track = self.__track
        lyrics = None

        if not track or not track.get_lyrics_key():
            gobject.idle_add(self.emit, "lyrics", lyrics)
            return

        artist = track[ARTIST]
        title = track[TITLE]
        lyrics_key = track.get_lyrics_key()

        # try locally stored lyrics first
        lyrics = blaplay.get_metadata("lyrics", lyrics_key)
        if lyrics and False:
            gobject.idle_add(self.emit, "lyrics", lyrics)
            return

        # try to download lyrics
        resources = [
            # TODO: - add option for passing dict of replacements to the __download_feed method
            #       - don't escape ß for wikia
            ("http://lyrics.wikia.com/api.php?action=query&prop=revisions&"
                "rvprop=content&format=json&titles={0}:{1}", "_", "", "",
                "()!", self.__json_parser, "", "", ""
            ),
#            ("http://www.lyricsmania.com/{1}_lyrics_{0}.html", "_", ".", "",
#                    self.__html_parser, "div", ("id", "songlyrics_h"), ""),
#            ("http://www.lyricstime.com/{0}-{1}-lyrics.html", "-", ".", "",
#                    self.__html_parser, "div", ("id", "songlyrics"), ""),
#            ("http://megalyrics.ru/lyric/{0}/{1}.htm", "_", ".", "",
#                    self.__html_parser, "pre", ("class", "lyric"),
#                    "Текст песни".decode("utf-8")
#            ),
#            ("http://www.lyricscollege.com/{0}_{1}_lyrics", "-", ".", "",
#                    self.__html_parser, "div", ("class", "lyrics"), ""),
#            ("http://www.songtextemania.com/{1}_songtext_{0}.html", "_", "'.",
#                    "", self.__html_parser, "div", ("id", "songlyrics_h"),
#                    "Songtext:"
#            )
        ]

        for (url, separator, erase, replace, safe, parser, tag, attr,
                ignore) in resources:
            # TODO: songtextemania removes apostrophes

            feed = self.__download_feed(
                    url, separator, erase, replace, safe, artist, title)
            if not feed: continue
            lyrics = parser.feed(feed=feed, tag=tag, attr=attr, ignore=ignore)

            # TODO: test redirect feature of wikia
#            if (lyrics and lyrics[0] == "#" and lyrics.lower().find("redirect")
#                    != -1):
#                artist, title = lyrics.split("[")[-1].split("]")[0].split(":")
#                buf = self.__download_lyrics(url, artist, title, separator)
#                lyrics = self.__parse_buffer(buf, locator, format_)

            if lyrics: break

        # if lyrics were found, store them locally
        if lyrics:
            lyrics = blautil.remove_html_tags(lyrics).strip()
            try: lyrics = lyrics.decode("utf-8", "replace")
            except (AttributeError, UnicodeDecodeError):
                print_d("Failed to store lyrics")
            blaplay.add_metadata("lyrics", lyrics_key, lyrics)

        gobject.idle_add(self.emit, "lyrics", lyrics)

    @blautil.thread
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

        if cover: gobject.idle_add(self.emit, "cover", cover, force_download)
        else:
            def f():
                gobject.idle_add(
                        self.emit, "cover", blaconst.COVER, force_download)
                return False
            self.__tid = gobject.timeout_add(2000, f)
            cover = blafm.get_cover(track, image_base)
            if not cover and not force_download:
                base = os.path.dirname(track.uri)
                images = [f for f in os.listdir(base)
                        if blautil.get_extension(f) in ["jpg", "png"]]
                for image in images:
                    name = image.lower()
                    if ("front" in name or "cover" in name or
                            name.startswith("folder") or
                            (name.startswith("albumart") and
                            name.endswith("large"))):
                        path = os.path.join(base, image)
                        name = os.path.basename(image_base)
                        images = [f for f in os.listdir(blaconst.COVERS)
                                if f.startswith(name)]
                        images = [os.path.join(blaconst.COVERS, f)
                                for f in images]
                        map(os.unlink, images)
                        cover = "%s.%s" % (
                                image_base, blautil.get_extension(path))
                        shutil.copy(path, cover)
                        break

            if cover:
                gobject.source_remove(self.__tid)
                gobject.idle_add(self.emit, "cover", cover, force_download)

    @blautil.thread
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

        gobject.idle_add(self.emit, "biography", image, biography)

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
                map(blautil.BlaThread.kill, [self.__thread_lyrics,
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
            cover = "%s.%s" % (image_base, blautil.get_extension(path))
            shutil.copy(path, cover)
        else: cover = blaconst.COVER

        # this is called directly from the main thread so we can emit the
        # signal without gobject.idle_add
        self.emit("cover", cover, False)

