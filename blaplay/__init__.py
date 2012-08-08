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

import sys
import os

import gobject

import blaconst, blautils
try: import bladbus
except ImportError:
    # if the dbus module isn't available we just define a class which acts on
    # behalf of the module, issuing warnings whenever it's used
    class BlaDBus:
        def setup_bus(self, *args): pass
        def query_bus(self, *args):
            print_w("Failed to import dbus module. Install dbus-python.",
                    force=True)
            sys.exit()
    bladbus = BlaDBus()

debug = False
quiet = False
metadata = {"bio": {}, "lyrics": {}}


def signal(nargs):
    return (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (object,) * nargs)

# some very crude message functions
# TODO: enhance output of these and add them to __builtin__ so we don't have to
#       import blaplay to use them
def print_d(msg):
    if debug and not quiet: print "*** DEBUG: %s ***" % msg

def print_i(msg):
    if quiet: return
    print "*** INFO: %s ***" % msg

def print_w(msg, force=False):
    if quiet and not force: return
    print "*** WARNING: %s ***" % msg

def print_e(msg):
    if quiet: return
    print "*** ERROR: %s ***" % msg
    sys.exit()

def manage_pidfile(filepath):
    directories = [blaconst.USERDIR, blaconst.COVERS, blaconst.ARTISTS,
                blaconst.RELEASES, blaconst.EVENTS]
    if not all(map(os.path.isdir, directories)):
        print_i("Setting up user directories")
        for directory in [blaconst.USERDIR, blaconst.COVERS, blaconst.ARTISTS,
                blaconst.RELEASES, blaconst.EVENTS]:
            try: os.makedirs(directory)
            except OSError as (errno, strerror):
                # file exists
                if errno != 17: raise

    pid = os.getpid()
    if os.path.isfile(blaconst.PIDFILE):
        filepath = os.path.realpath(filepath)
        # pidfile exists so check if it names a zombie or re-assigned pid
        try:
            with open(blaconst.PIDFILE, "r") as f: old_pid = f.read()
        except IOError: pass

        try:
            with open("/proc/%s/cmdline" % old_pid, "r") as f:
                cmdline = f.read().strip()
        except IOError:
            # there is no process associated with old_pid so get rid of it
            os.unlink(blaconst.PIDFILE)
        else:
            # old_pid actually has an entry in /proc, so check if the cmdline
            # corresponds to an invocation of blaplay or if the pid was
            # reassigned to another process
            cmdline = filter(None, cmdline.split("\x00"))
            if ("python" in cmdline[0].lower() and
                    filepath == os.path.realpath(cmdline[-1])):
                bladbus.query_bus("raise_window")
                return True

    # we're running the first instance of `blaplay' so create a proper pidfile
    with open(blaconst.PIDFILE, "w") as f: f.write(str(pid))
    return False

def parse_args():
    from argparse import ArgumentParser, RawTextHelpFormatter
    global quiet, debug

    def parse_cmdline(args=None):
        parser = ArgumentParser(add_help=False,
                description="%s - A bla that plays" % blaconst.APPNAME,
                prog=blaconst.APPNAME, formatter_class=RawTextHelpFormatter
        )
        group = parser.add_mutually_exclusive_group()
        group.add_argument("-c", "--append", action="store_true",
                help="Append URIs to current playlist")
        group.add_argument("-t", "--new", action="store_true",
                help="Send URIs to new playlist")
        parser.add_argument("URI", nargs="*", help="Input to be sent to the "
                "current playlist unless\noption -c or -n is specified")
        parser.add_argument("-a", "--play-pause", action="store_true",
                help="play or pause playback")
        parser.add_argument("-s", "--stop", action="store_true",
                help="stop playback")
        parser.add_argument("-n", "--next", action="store_true",
                help="play next track in current playlist")
        parser.add_argument("-p", "--previous", action="store_true",
                help="play previous track in current playlist")
        parser.add_argument("-f", "--format", nargs=1, help="print track "
                "information and exit\n   %%a: artist\n   %%t: "
                "title\n   %%b: album\n   %%c: cover", action="append"
        )
        parser.add_argument("-d", "--debug", action="store_true", help="print "
                "debug messages")
        parser.add_argument("-q", "--quiet", action="store_true", help="only "
                "print fatal messages")
        parser.add_argument("-h", "--help", action="help", help="display this "
                "help and exit")
        parser.add_argument("-v", "--version", action="version", help="output "
                "version information and exit\n\n", version="%s %s"
                % (blaconst.APPNAME, blaconst.VERSION)
        )
        return vars(parser.parse_args())

    # process command-line arguments
    args = parse_cmdline()

    # flags
    if args["quiet"]: quiet = True
    if args["debug"]: debug = True

    # player info formatting
    if args["format"]: bladbus.query_bus(args["format"][0])

    # TODO: if URI is not empty on first run we need to wait for blaplay to be
    #       initialized before we can add the URIs to any playlist
    if args["URI"]:
        uris = args["URI"]
        if args["append"]: action = "append"
        elif args["new"]: action = "new"
        else: action = "replace"
#        bladbus.query_bus(uris, action)

    # player commands
    if args["play_pause"]: bladbus.query_bus("play_pause")
    elif args["stop"]: bladbus.query_bus("stop")
    elif args["next"]: bladbus.query_bus("next")
    elif args["previous"]: bladbus.query_bus("previous")

def init():
    import ctypes
    import gtk
    import signal
    from blaplay import blacfg, blafm
    global metadata

    def main_quit(*args): gtk.main_quit()
    signal.signal(signal.SIGTERM, main_quit)
    signal.signal(signal.SIGINT, main_quit)

    gobject.set_prgname(blaconst.APPNAME)
    lib = ctypes.CDLL("libc.so.6")
    # 15 == PR_SET_NAME
    lib.prctl(15, blaconst.APPNAME, 0, 0, 0)

    # set up the D-Bus interface and last.fm services
    bladbus.setup_bus()
    blafm.init()

    # get cached metadata
    _metadata = blautils.deserialize_from_file(blaconst.METADATA_PATH)
    if _metadata: metadata = _metadata

    gtk.quit_add(0, clean_up)
    # write config to disk every 10 minutes
    gobject.timeout_add(10 * 60 * 1000, blacfg.save, False)
    gtk.main()

def add_metadata(section, key, value):
    global metadata
    metadata[section][key] = value

def get_metadata(section, key):
    try: return metadata[section][key]
    except KeyError: return None

def save_metadata():
    blautils.serialize_to_file(metadata, blaconst.METADATA_PATH)

def clean_up():
    print_i("Cleaning up")

    from blaplay import blacfg, blaplayer

    blaplayer.player.stop()
    blautils.BlaThread.clean_up()
    save_metadata()
    blacfg.save()
    try: os.unlink(blaconst.PIDFILE)
    except OSError: pass

    return 0

