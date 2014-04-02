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

metadata = None


def init():
    global metadata
    metadata = BlaMetadata()


class BlaMetadata(object):
    def __init__(self):
        metadata = blautil.deserialize_from_file(blaconst.METADATA_PATH)
        self.__metadata = metadata or {"lyrics": {}}
        def pre_shutdown_hook():
            blautil.serialize_to_file(self.__metadata, blaconst.METADATA_PATH)
        blaplay.bla.add_pre_shutdown_hook(pre_shutdown_hook)

    def add(self, section, key, value):
        self.__metadata[section][key] = value

    def get(self, section, key):
        try:
            return self.__metadata[section][key]
        except KeyError:
            return None

class BlaFetcher(gobject.GObject):
    __gsignals__ = {
        "cover": blautil.signal(2),
        "lyrics": blautil.signal(2)
    }

    __tid = -1
    __thread_lyrics = __thread_cover = None

    class JSONParser(object):
        def feed(self, feed, **kwargs):
            s = json.loads(feed)
            pages = s["query"]["pages"]
            try:
                lyrics = pages.values()[0]["revisions"][0]["*"]
            except KeyError:
                return ""
            try:
                lyrics = re.search(r"(<lyrics>)(.*)(</lyrics>)",
                                   lyrics, re.UNICODE | re.DOTALL).group(2)
            except AttributeError:
                return ""
            return lyrics

    class HTMLParser(HTMLParser_):
        def feed(self, feed, tag, attr, ignore=""):
            self.__tag = tag
            self.__attr = attr

            self.__lyrics_tag_found = False
            self.__lyrics = ""

            try:
                HTMLParser_.feed(self, unicode(feed.encode("utf-8")))
            except UnicodeDecodeError:
                return ""
            return self.__lyrics[self.__lyrics.find(ignore) +
                                 len(ignore):].strip()

        def handle_starttag(self, tag, attrs):
            if tag == self.__tag and self.__attr in attrs:
                self.__lyrics_tag_found = True
            if self.__lyrics_tag_found and tag == "br":
                self.__lyrics += "\n"

        def handle_endtag(self, tag):
            if tag == self.__tag:
                self.__lyrics_tag_found = False

        def handle_data(self, data):
            if self.__lyrics_tag_found:
                self.__lyrics += data.strip()

        def handle_charref(self, name):
            if self.__lyrics_tag_found:
                if name.startswith("x"):
                    c = unichr(int(name[1:], 16))
                else:
                    c = unichr(int(name))
                self.__lyrics += c

    def __init__(self):
        super(BlaFetcher, self).__init__()
        self.__json_parser = BlaFetcher.JSONParser()
        self.__html_parser = BlaFetcher.HTMLParser()

    def __download_feed(self, baseurl, separator, erase, replace, safe, artist,
                        title):
        feed = None

        # TODO: this can probably be achieved more elegantly

        # Erase site-specific characters.
        re_ = re.compile(r"|".join(erase) or r"$^", flags=re.UNICODE)
        artist, title = [re_.sub("", s) for s in (artist, title)]

        # Replace site-specific characters by the separator.
        # FIXME: this check SHOULD be redundant
        re_ = re.compile(r"|".join(replace) or r"$^", flags=re.UNICODE)
        artist, title = [re_.sub(separator, s) for s in (artist, title)]

        # Remove consecutive spaces and capitalize words (wikia is
        # case-sensitive).
        re_ = re.compile(r" +", re.UNICODE)
        artist, title = [re_.sub(" ", s).strip() for s in (artist, title)]
        re_ = re.compile(r"([\s\(\[\{])(\S)", re.UNICODE)
        artist, title = [re_.sub(lambda m: m.group(1) + m.group(2).upper(), s)
                         for s in (artist, title)]

        # FIXME: should this really be done for all search engines?
#        artist = artist.replace(".", separator)
#        title = title.replace(".", separator)

        url = baseurl.format(
            artist.replace(" ", separator).replace("&", "and"),
            title.replace(" ", separator).replace("&", "and"))

        # Substitute composite letters and transliterate accents.
        DICT = {
            u"æ": "ae", u"ð": "d", u"ø": "o", u"þ": "th", u"œ": "oe", u"ƒ": "f"
        }
        regexp = re.compile(
            "|".join(["(%s)" % key for key in DICT]), re.UNICODE)
        lookup = dict(
            (idx+1, value) for idx, value in enumerate(DICT.itervalues()))
        url = regexp.sub(lambda mo: mo.expand(lookup[mo.lastindex]),
                         unicode(url.encode("utf-8")))
        url = unicodedata.normalize(
            "NFKD", unicode(url)).encode("ascii", "ignore")

        # Remove consecutive separators and quote the URL.
        url = re.sub("%s+" % separator, separator, url, flags=re.UNICODE)
        url = urllib.quote(url, safe=":/?=+&%s%s" % (separator, safe))

        print_d(url)

        try:
            conn = urllib2.urlopen(url, timeout=TIMEOUT)
        except (IOError, socket.timeout):
            return feed
        else:
            encoding = conn.headers.getparam("charset")
            try:
                feed = conn.read()
            except socket.timeout:
                return feed
        try:
            feed = feed.decode(encoding).encode("utf-8")
        except (TypeError, UnicodeDecodeError):
            pass
        conn.close()
        return feed

    @blautil.thread
    def __fetch_lyrics(self, track, timestamp):
        def emit(lyrics):
            if not lyrics:
                lyrics = None
            gobject.idle_add(self.emit, "lyrics", timestamp, lyrics)

        lyrics = None

        if not track or not track.get_lyrics_key():
            emit(lyrics)
            return

        lyrics_key = track.get_lyrics_key()

        # Try locally stored lyrics first.
        lyrics = metadata.get("lyrics", lyrics_key)
        if lyrics and False: # FIXME: remove this after testing
            emit(lyrics)
            return

        # TODO: wrap lyrics providers in their own class
        #       http://www.plyrics.com/lyrics/balanceandcomposure/reflection.html
        #       http://www.songlyrics.com/born-of-osiris/exhilarate-lyrics/
        resources = [
            # TODO: - add option for passing dict of replacements to the __download_feed method
            #       - don't escape ß for wikia
            ("http://lyrics.wikia.com/api.php?action=query&prop=revisions&"
             "rvprop=content&format=json&titles={0}:{1}", "_", "", "",
             "()!", self.__json_parser, "", "", ""),
#            ("http://www.lyricsmania.com/{1}_lyrics_{0}.html", "_", ".", "",
#             self.__html_parser, "div", ("id", "songlyrics_h"), ""),
#            ("http://www.lyricstime.com/{0}-{1}-lyrics.html", "-", ".", "",
#             self.__html_parser, "div", ("id", "songlyrics"), ""),
#            ("http://megalyrics.ru/lyric/{0}/{1}.htm", "_", ".", "",
#             self.__html_parser, "pre", ("class", "lyric"),
#             "Текст песни".decode("utf-8")),
#            ("http://www.lyricscollege.com/{0}_{1}_lyrics", "-", ".", "",
#             self.__html_parser, "div", ("class", "lyrics"), ""),
#            ("http://www.songtextemania.com/{1}_songtext_{0}.html", "_", "'.",
#             "", self.__html_parser, "div", ("id", "songlyrics_h"),
#             "Songtext:")
        ]

        artist = track[ARTIST]
        title = track[TITLE]
        for (url, separator, erase, replace, safe, parser, tag, attr,
             ignore) in resources:
            # TODO: songtextemania removes apostrophes

            feed = self.__download_feed(
                url, separator, erase, replace, safe, artist, title)
            if not feed:
                continue
            lyrics = parser.feed(feed=feed, tag=tag, attr=attr, ignore=ignore)

            # TODO: test redirect feature of wikia
#            if (lyrics and lyrics[0] == "#" and lyrics.lower().find("redirect")
#                    != -1):
#                artist, title = lyrics.split("[")[-1].split("]")[0].split(":")
#                buf = self.__download_lyrics(url, artist, title, separator)
#                lyrics = self.__parse_buffer(buf, locator, format_)

            if lyrics:
                break

        if lyrics:
            lyrics = blautil.remove_html_tags(lyrics).strip()
            try:
                lyrics = lyrics.decode("utf-8", "replace")
            except (AttributeError, UnicodeDecodeError):
                print_d("Failed to store lyrics")
            metadata.add("lyrics", lyrics_key, lyrics)

        emit(lyrics)

    @blautil.thread
    def __fetch_cover(self, track, timestamp):
        def emit(cover):
            gobject.source_remove(self.__tid)
            gobject.idle_add(self.emit, "cover", timestamp, cover)
            return False

        gobject.source_remove(self.__tid)
        cover = None

        image_base = track.get_cover_basepath()
        if image_base is None:
            return

        if os.path.isfile("%s.jpg" % image_base):
            cover = "%s.jpg" % image_base
        elif os.path.isfile("%s.png" % image_base):
            cover = "%s.png" % image_base

        if cover is not None:
            return emit(cover)

        self.__tid = gobject.timeout_add(2000, emit, blaconst.COVER)
        cover = blafm.get_cover(track, image_base)
        if cover is None:
            base = os.path.dirname(track.uri)
            images = [f for f in os.listdir(base)
                      if blautil.get_extension(f).lower() in ["jpg", "png"]]
            r = re.compile(
                r"front|cover|^folder|^albumart.*large", re.UNICODE)
            for image in images:
                name = image.lower()
                if r.search(name):
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
        if cover is not None:
            emit(cover)

    def fetch_cover(self, track, timestamp):
        # This convenience method makes sure we keep a reference to the thread
        # that retrieves the cover so we're able to kill it once the method is
        # called again. Covers ought to be able to be fetched independently of
        # the lyrics so we wrap the thread creation here.
        try:
            self.__thread_cover.kill()
        except AttributeError:
            pass
        self.__thread_cover = self.__fetch_cover(track, timestamp)

    def fetch_lyrics(self, track, timestamp):
        for thread in [self.__thread_lyrics, self.__thread_cover]:
            try:
                thread.kill()
            except AttributeError:
                pass

        self.__thread_lyrics = self.__fetch_lyrics(track, timestamp)

