# blaplay, Copyright (C) 2012-2014  Niklas Koep

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

import re
import time

import gobject
import gtk

from blaplay import blautil
from blaplay.blacore import blaconst
from blaplay.formats._identifiers import *


# TODO: Make this a model factory, parametrized over blaconst.ORGANIZE_BY_*.
class BlaLibraryModel(gtk.TreeStore):
    _MODEL_LAYOUT = (
        gobject.TYPE_STRING,    # uri
        gobject.TYPE_STRING     # label
    )

    __gsignals__ = {
        "populated": blautil.signal(0)
    }

    def __init__(self, organize_by):
        super(BlaLibraryModel, self).__init__(*BlaLibraryModel._MODEL_LAYOUT)
        self._organize_by = organize_by

    def _make_query_function(self, library, filter_string):
        if not filter_string:
            return lambda *x: True

        filter_string = filter_string.decode("utf-8")
        flags = re.UNICODE | re.IGNORECASE
        search_functions = [re.compile(t, flags).search for t in
                            map(re.escape, filter_string.split())]
        filter_directory = self.organize_by == blaconst.ORGANIZE_BY_DIRECTORY

        def query(uri):
            track = library[uri]
            strings = [track[identifier] for identifier in
                       (ARTIST, TITLE, ALBUM)]
            # XXX: This could be simplified if we could index the basename as
            #      track[BASENAME].
            if filter_directory:
                strings.append(track.basename)

            for search_function in search_functions:
                for string in strings:
                    if search_function(string):
                        break
                else:
                    return False
            return True
        return query

    def _get_filter(self, config):
        # This returns a filter function which URIs have to pass in order
        # for them to be considered in the library browser.
        def get_regexp(string):
            tokens = [t.replace(".", "\.").replace("*", ".*")
                      for t in map(str.strip, string.split(","))]
            return re.compile(r"(%s)" % "|".join(tokens))

        restrict_re = get_regexp(
            config.getstring("library", "restrict.to.pattern").strip())
        exclude_string = config.getstring("library", "exclude.pattern").strip()
        if exclude_string:
            exclude_re = get_regexp(exclude_string)
            def filt(s):
                return restrict_re.match(s) and not exclude_re.match(s)
        else:
            filt = restrict_re.match
        return filt

    @staticmethod
    def _get_track_label(track):
        # ValueError is raised if the int() call fails. We hazard the
        # possible performance hit to avoid bogus TRACK properties.
        try:
            label = "%02d." % int(track[TRACK].split("/")[0])
        except ValueError:
            label = ""
        else:
            try:
                label = "%d.%s " % (int(track[DISC].split("/")[0]), label)
            except ValueError:
                label = "%s " % label
        artist = (track[ALBUM_ARTIST] or track[PERFORMER] or
                  track[ARTIST] or track[COMPOSER])
        if track[ARTIST] and artist != track[ARTIST]:
            label += "%s - " % track[ARTIST]
        return "%s%s" % (label, track[TITLE] or track.basename)

    @staticmethod
    def _organize_by_directory(uri, track):
        try:
            md = track[MONITORED_DIRECTORY]
        except KeyError:
            raise ValueError("Trying to include track in the library "
                             "browser that has no monitored directory")
        directory = track.uri[len(md)+1:]
        return tuple(["bla"] + directory.split("/"))

    @classmethod
    def _organize_by_artist(cls, uri, track):
        return (track[ARTIST] or "?", track[ALBUM] or "?",
                cls._get_track_label(track))

    @classmethod
    def _organize_by_artist_album(cls, uri, track):
        artist = (track[ALBUM_ARTIST] or track[PERFORMER] or
                  track[ARTIST] or "?")
        return ("%s - %s" % (artist, track[ALBUM] or "?"),
                cls._get_track_label(track))

    @classmethod
    def _organize_by_album(cls, uri, track):
        return (track[ALBUM] or "?", cls._get_track_label(track))

    @classmethod
    def _organize_by_genre(cls, uri, track):
        key = GENRE
        organizer = track[key].capitalize() or "?"
        label = "%s - %s" % (
            track[ALBUM_ARTIST] or track[ARTIST], track[ALBUM] or "?")
        return (organizer, label, cls._get_track_label(track))

    @classmethod
    def _organize_by_year(cls, uri, track):
        key = DATE
        organizer = track[key].capitalize() or "?"
        organizer = organizer.split("-")[0]
        label = "%s - %s" % (
            track[ALBUM_ARTIST] or track[ARTIST], track[ALBUM] or "?")
        return (organizer, label, cls._get_track_label(track))

    @property
    def organize_by(self):
        return self._organize_by

    def populate(self, config, library, filter_string):
        start_time = time.time()

        organize_by = self.organize_by
        if organize_by == blaconst.ORGANIZE_BY_DIRECTORY:
            cb = self._organize_by_directory
        elif organize_by == blaconst.ORGANIZE_BY_ARTIST:
            cb = self._organize_by_artist
        elif organize_by == blaconst.ORGANIZE_BY_ARTIST_ALBUM:
            cb = self._organize_by_artist_album
        elif organize_by == blaconst.ORGANIZE_BY_ALBUM:
            cb = self._organize_by_album
        elif organize_by == blaconst.ORGANIZE_BY_GENRE:
            cb = self._organize_by_genre
        elif organize_by == blaconst.ORGANIZE_BY_YEAR:
            cb = self._organize_by_year
        else:
            raise NotImplementedError

        count = 0
        batch_size = 25

        list_ = []
        append = list_.append
        library_filter = self._get_filter(config)
        query = self._make_query_function(library, filter_string)
        def filt(*args):
            return library_filter(*args) and query(*args)
        for uri in filter(filt, library):
            comps = tuple(map(unicode, cb(uri, library[uri])))
            append((comps, uri))
            count = count+1
            if count % batch_size == 0:
                yield True

        iterators = {}
        append = self.append
        def key(item):
            return map(unicode.lower, item[0])
        for comps, uri in sorted(list_, key=key):
            for idx in xrange(len(comps)-1):
                comps_init = comps[:idx+1]
                iterator = iterators.get(comps_init, None)
                if iterator is None:
                    parent = iterators.get(comps_init[:-1], None)
                    iterators[comps_init] = iterator = append(
                        parent, (None, comps_init[-1]))
            append(iterator, (uri, comps[-1]))
            count = count+1
            if count % batch_size == 0:
                yield True

        print_d("Populated library model in %.2f seconds" %
                (time.time() - start_time))
        self.emit("populated")
        yield False

