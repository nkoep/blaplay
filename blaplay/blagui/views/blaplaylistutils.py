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

import os
import urllib
import urlparse
import xml.etree.cElementTree as ETree
from xml.sax.saxutils import escape as xml_escape

from blaplay.formats._identifiers import *
from .. import blaguiutil


# XXX: These routines should be more efficient if playlists wrote to memory
#      first (see cStringIO).

def m3u_write(path, name, tracks, store_relative_paths):
    with open(path, "w") as f:
        f.write("#EXTM3U\n")
        for track in tracks:
            uri = track.uri
            length = track[LENGTH]
            artist = track[ARTIST]
            title = track[TITLE]
            if artist:
                header = "%s - %s" % (artist, title)
            else:
                header = title
            if store_relative_paths:
                uri = os.path.basename(uri)
            f.write("#EXTINF:%d, %s\n%s\n" % (length, header, uri))

def m3u_parse(path):
    directory = os.path.dirname(path)
    uris = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("#"):
                if not os.path.isabs(line):
                    line = os.path.join(directory, line)
                uris.append(line)
    return uris

def pls_write(path, name, tracks, store_relative_paths):
    with open(path, "w") as f:
        f.write("[playlist]\n")
        for idx, track in enumerate(tracks):
            uri = track.uri
            if store_relative_paths:
                uri = os.path.basename(uri)
            text = "File%d=%s\nTitle%d=%s\nLength%d=%s\n" % (
                idx, uri, idx, track[TITLE], idx, track[LENGTH])
            f.write(text)
        f.write("NumberOfEntries=%d\nVersion=2\n" % len(tracks))

def pls_parse(path):
    directory = os.path.dirname(path)
    uris = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line.lower().startswith("file"):
                try:
                    line = line[line.index("=")+1:].strip()
                except ValueError:
                    pass
                else:
                    if not os.path.isabs(line):
                        line = os.path.join(directory, line)
                    uris.append(line)
    return uris

def xspf_write(path, name, tracks, store_relative_paths):
    tags = {
        "title": TITLE,
        "creator": ARTIST,
        "album": ALBUM,
        "trackNum": TRACK
    }
    with open(path, "w") as f:
        f.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
                "<playlist version=\"1\" "
                "xmlns=\"http://xspf.org/ns/0/\">\n")
        f.write("  <title>%s</title>\n" % name)
        f.write("  <trackList>\n")
        for track in tracks:
            uri = track.uri
            f.write("    <track>\n")
            for element, identifier in tags.iteritems():
                value = xml_escape(track[identifier])
                if not value:
                    continue
                f.write("      <%s>%s</%s>\n" % (element, value, element))
            if store_relative_paths:
                uri = os.path.basename(uri)
            f.write("      <location>file://%s</location>\n" %
                    urllib.quote(uri))
            f.write("    </track>\n")
        f.write("  </trackList>\n")
        f.write("</playlist>\n")

def xspf_parse(path):
    directory = os.path.dirname(path)
    name, uris = "", []
    try:
        with open(path, "r") as f:
            tree = ETree.ElementTree(None, f)
    except IOError:
        blaguiutil.error_dialog("Failed to parse playlist \"%s\"" % path)
        return None

    ns = "{http://xspf.org/ns/0/}"
    nodes = tree.find("%strackList" % ns).findall("%strack" % ns)
    name = tree.find("%stitle" % ns)
    if name is not None:
        name = name.text.strip()
    parse_url = urlparse.urlparse
    for node in nodes:
        uri = node.find("%slocation" % ns).text.strip()
        parse_result = parse_url(uri)
        uri = parse_result.path or parse_result.netloc
        if not os.path.isabs(uri):
            uri = os.path.join(directory, uri)
        uris.append(uri)
    return name, uris

