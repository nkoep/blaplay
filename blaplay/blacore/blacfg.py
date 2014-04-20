# blaplay, Copyright (C) 2012-2013  Niklas Koep

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

import gobject

import blaconst
from blaplay import blautil


class BlaCfg(RawConfigParser, gobject.GObject):
    __gsignals__ = {
        "changed": blautil.signal(2)
    }

    def __init__(self):
        RawConfigParser.__init__(self)
        gobject.GObject.__init__(self)

        self._timeout_id = -1

    def init(self):
        print_i("Loading config")

        default = {
            "general": {
                "size": "",
                "position": "",
                "maximized": "no",
                "pane.pos.left": "",
                "pane.pos.right": "",
                "always.show.tray": "yes",
                "close.to.tray": "yes",
                "filesystem.directory": "",
                "filechooser.directory": "",
                "browser.view": blaconst.BROWSER_LIBRARY,
                "metadata.view": blaconst.METADATA_LYRICS,
                "play.order": blaconst.ORDER_NORMAL,
                "columns.playlist": "",
                "columns.queue": "",
                "cursor.follows.playback": "yes",
                "queue.remove.when.activated": "yes",
                "search.after.timeout": "no",
                "show.visualization": "yes"
            },
            "player": {
                "logarithmic.volume.scale": "no",
                "use.equalizer": "no",
                "equalizer.profile": "",
                "volume": "1.0",
                "muted": "no"
            },
            "equalizer.profiles": {
            },
            "library": {
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
            "keybindings": {
                "playpause": "",
                "pause": "",
                "stop": "",
                "previous": "",
                "next": "",
                "volup": "",
                "voldown": "",
                "mute": ""
            },
            "lastfm": {
                "user": "",
                "sessionkey": "",
                "scrobble": "yes",
                "now.playing": "yes",
                "ignore.pattern": ""
            }
        }

        for section, values in default.iteritems():
            self.add_section(section)
            for key, value in values.iteritems():
                self.set_(section, key, value)

        if not self.read(blaconst.CFG_PATH):
            self.read("%s.bak" % blaconst.CFG_PATH)

        def schedule_save(*args):
            gobject.source_remove(self._timeout_id)
            self._timeout_id = gobject.timeout_add(15000, self.save)
        self.connect("changed", schedule_save)

    # getter
    def __get(self, section, key, context):
        try:
            return context(self.get(section, key))
        except (ValueError, NoSectionError, NoOptionError):
            return None

    def getstring(self, section, key):
        return self.__get(section, key, context=str)

    def getint(self, section, key):
        # The call int("1.2") raises a ValueError so convert to float first to
        # be a bit more generous in terms of what constitutes an error.
        return self.__get(section, key, context=lambda v: int(float(v)))

    def getfloat(self, section, key):
        return self.__get(section, key, context=float)

    def getboolean(self, section, key):
        try:
            return super(BlaCfg, self).getboolean(section, key)
        except (ValueError, NoSectionError, NoOptionError):
            return None

    def getlistint(self, section, key):
        return self.__get(section, key,
                          context=lambda v: map(int, v.split(",")))

    def getlistfloat(self, section, key):
        return self.__get(section, key,
                          context=lambda v: map(float, v.split(",")))

    def getliststr(self, section, key):
        def context(v):
            try:
                return filter(None, v.split(","))
            except AttributeError:
                pass
            return []
        return self.__get(section, key, context=context)

    def getdotliststr(self, section, key):
        def context(v):
            try:
                return filter(None, v.split(":"))
            except AttributeError:
                pass
            return []
        return self.__get(section, key, context=context)

    # setter
    def set_(self, section, key, value):
        if not self.has_section(section):
            self.add_section(section)

        try:
            old_value = super(BlaCfg, self).get(section, key)
        except NoOptionError:
            old_value = None
        super(BlaCfg, self).set(section, key, value)
        if old_value != value:
            self.emit("changed", section, key)

    def setboolean(self, section, key, value):
        if not self.has_section(section):
            self.add_section(section)
        if value:
            self.set_(section, key, "yes")
        else:
            self.set_(section, key, "no")

    def save(self):
        import os
        import shutil
        import tempfile

        print_d("Saving config")

        # Write data to tempfile.
        fd, tmp_path = tempfile.mkstemp()
        with os.fdopen(fd, "w") as f:
            self.write(f)

        # Move the old file.
        try:
            shutil.move(blaconst.CFG_PATH, "%s.bak" % blaconst.CFG_PATH)
        except IOError:
            pass

        # Move the tempfile to the actual location and remove the backup file
        # on success.
        try:
            shutil.move(tmp_path, blaconst.CFG_PATH)
        except IOError:
            pass
        else:
            try:
                os.unlink("%s.bak" % blaconst.CFG_PATH)
            except OSError:
                pass

        return False

    def delete_option(self, section, key):
        if self.has_section(section) and self.has_option(section, key):
            self.remove_option(section, key)

    def get_keys(self, section):
        if self.has_section(section):
            return self.items(section)
        return []

