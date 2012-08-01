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

from ConfigParser import RawConfigParser, NoOptionError, NoSectionError
cfg = RawConfigParser()

import blaconst


def init():
    import blaplay

    blaplay.print_i("Loading config")

    init = {
        "general":
        {
            "size": "",
            "position": "",
            "maximized": "no",
            "pane.pos.left": "",
            "pane.pos.right": "",
            "always.show.tray": "yes",
            "minimize.to.tray": "no",
            "close.to.tray": "yes",
            "tray.tooltip": "yes",
            "browsers": "yes",
            "playlist.tabs": "yes",
            "draw.tree.lines": "yes",
            "statusbar": "yes",
            "side.pane": "yes",
            "filesystem.directory": "",
            "view": blaconst.VIEW_PLAYLISTS,
            "browser.view": blaconst.BROWSER_LIBRARY,
            "metadata.view": blaconst.METADATA_LYRICS,
            "play.order": blaconst.ORDER_NORMAL,
            "columns.playlist": "",
            "columns.queue": "",
            "cursor.follows.playback": "yes",
            "queue.remove.when.activated": "yes",
            "search.after.timeout": "no",
            "visualization": blaconst.VISUALIZATION_SPECTRUM
        },

        "player":
        {
            "logarithmic.volume.control": "no",
            "use.equalizer": "no",
            "equalizer.profile": "",
            "volume": "1.0",
            "muted": "no"
        },

        "equalizer.profiles":
        {
        },

        "library":
        {
            "directories": "",
            "restrict.to": "*",
            "exclude": "",
            "organize.by": blaconst.ORGANIZE_BY_DIRECTORY,
            "doubleclick.action": blaconst.ACTION_SEND_TO_CURRENT,
            "middleclick.action": blaconst.ACTION_ADD_TO_CURRENT,
            "return.action": blaconst.ACTION_SEND_TO_NEW,
            "custom.browser": "yes",
            "update.on.startup": "yes"
        },

        "lastfm":
        {
            "user": "",
            "sessionkey": "",
            "scrobble": "yes",
            "nowplaying": "yes",
            "ignore.pattern": ""
        },

        "colors":
        {
            "overwrite": "no",
            "background": "#313131",
            "highlight": "#A51F1C",
            "alternate.rows": "#2E2E2E",
            "selected.rows": "#525252",
            "text": "#FAFAFA",
            "active.text": "#FAFAFA"
        }
    }

    for section, values in init.iteritems():
        cfg.add_section(section)
        for key, value in values.iteritems():
            cfg.set(section, key, value)

    if not cfg.read(blaconst.CFG_PATH): cfg.read("%s.bak" % blaconst.CFG_PATH)

def getstring(section, key):
    try: return str(cfg.get(section, key))
    except (ValueError, NoSectionError, NoOptionError): return None

def getint(section, key):
    try: return int(cfg.get(section, key))
    except (ValueError, NoSectionError, NoOptionError): return None

def getfloat(section, key):
    try: return float(cfg.get(section, key))
    except (ValueError, NoSectionError, NoOptionError): return None

def getboolean(section, key):
    try: return cfg.getboolean(section, key)
    except (ValueError, NoSectionError, NoOptionError): return None

def getlistint(section, key):
    try: return map(int, cfg.get(section, key).split(","))
    except (ValueError, NoSectionError, NoOptionError): return None

def getlistfloat(section, key):
    try: return map(float, cfg.get(section, key).split(","))
    except (ValueError, NoSectionError, NoOptionError): return None

def getliststr(section, key):
    try: return filter(None, cfg.get(section, key).split(","))
    except (ValueError, NoSectionError, NoOptionError): return None
    except AttributeError: return []

def getdotliststr(section, key):
    try: return filter(None, cfg.get(section, key).split(":"))
    except (NoSectionError, NoOptionError): return None
    except AttributeError: return []

def set(section, key, value):
    if not cfg.has_section(section): cfg.add_section(section)
    cfg.set(section, key, value)

def setboolean(section, key, value):
    if not cfg.has_section(section): cfg.add_section(section)
    if value: cfg.set(section, key, "yes")
    else: cfg.set(section, key, "no")

def save():
    import os
    import shutil
    import tempfile

    # write data to tempfile
    fd, tmp_path = tempfile.mkstemp()
    with os.fdopen(fd, "w") as f: cfg.write(f)

    # move old file
    try: shutil.move(blaconst.CFG_PATH, "%s.bak" % blaconst.CFG_PATH)
    except IOError: pass

    # move tempfile to actual location and remove backup file on success
    try: shutil.move(tmp_path, blaconst.CFG_PATH)
    except IOError: pass
    else:
        try: os.unlink("%s.bak" % blaconst.CFG_PATH)
        except OSError: pass

def add_section(section):
    if not cfg.has_section(section): cfg.add_section(section)

def delete_option(section, key):
    if cfg.has_section(section) and cfg.has_option(section, key):
        cfg.remove_option(section, key)

def has_option(section, key):
    if cfg.has_section(section) and cfg.has_option(section, key): return True
    return False

def get_keys(section):
    if cfg.has_section(section): return cfg.items(section)

