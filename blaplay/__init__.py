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

import __builtin__
import sys
import os
import fcntl
import logging

import gobject

import blaconst, blautils
try: import bladbus
except ImportError:
    # if the dbus module isn't available we just define a class which acts on
    # behalf of the module, issuing warnings whenever it's used
    class bladbus:
        @classmethod
        def __warning(cls, force):
            print_w("Failed to import dbus module. Install dbus-python.",
                    force=force)
            sys.exit()
        @classmethod
        def setup_bus(cls, *args): cls.__warning(False)
        @classmethod
        def query_bus(cls, *args): cls.__warning(True)

lock_file = None
debug = False
quiet = False
metadata = {"bio": {}, "lyrics": {}}
cli_queue = None


def signal(n_args):
    return (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (object,) * n_args)

def init(filepath):
    # set up logging and messaging functions
    def critical(msg):
        logging.critical(msg)
        sys.exit()

    args = parse_args()

    format_ = "*** %%(levelname)s%s: %%(message)s"
    if debug:
        format_ %= " (%(filename)s:%(lineno)d)"
        level = logging.DEBUG
    else:
        format_ %= ""
        level = logging.INFO
    logging.basicConfig(format=format_, level=level)

    colors = [
        (logging.INFO, "34"), (logging.DEBUG, "35"),
        (logging.WARNING, "32"), (logging.CRITICAL, "31")
    ]
    for level, color in colors:
        logging.addLevelName(level, "\033[1;%sm%s\033[1;m"
                % (color, logging.getLevelName(level)))

    __builtin__.__dict__["print_d"] = logging.debug
    __builtin__.__dict__["print_i"] = logging.info
    __builtin__.__dict__["print_w"] = logging.warning
    __builtin__.__dict__["print_c"] = critical

    # parse command-line arguments and make sure only one instance of blaplay
    # will be run
    process_args(args)
    force_singleton(filepath)

def force_singleton(filepath):
    global lock_file, cli_queue

    # set up user directories
    directories = [blaconst.CACHEDIR, blaconst.USERDIR, blaconst.COVERS,
            blaconst.ARTISTS, blaconst.RELEASES, blaconst.EVENTS]

    if not all(map(os.path.isdir, directories)):
        print_i("Setting up user directories")
        for directory in [blaconst.USERDIR, blaconst.COVERS, blaconst.ARTISTS,
                blaconst.RELEASES, blaconst.EVENTS]:
            try: os.makedirs(directory)
            except OSError as (errno, strerror):
                # inode exists, but it's a file. we can only bail in this case
                if errno != 17: raise

    pid = os.getpid()
    lock_file = open(blaconst.PIDFILE, "w")
    try: fcntl.lockf(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        bladbus.query_bus(*cli_queue)
        cli_queue = None
        sys.exit()
    lock_file.write(str(pid))

def parse_args():
    from argparse import ArgumentParser, RawTextHelpFormatter
    global quiet, debug, cli_queue

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
                "title\n   %%b: album\n   %%y: year"
                "\n   %%g: genre\n   %%c: cover", action="append"
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

    return args

def process_args(args):
    # player info formatting
    if args["format"]: bladbus.query_bus(args["format"][0])

    if args["URI"]:
        if args["append"]: action = "append"
        elif args["new"]: action = "new"
        else: action = "replace"
        n = lambda uri: os.path.normpath(os.path.abspath(uri))
        cli_queue = (action, map(n, args["URI"]))

    # player commands
    if args["play_pause"]: bladbus.query_bus("play_pause")
    elif args["stop"]: bladbus.query_bus("stop")
    elif args["next"]: bladbus.query_bus("next")
    elif args["previous"]: bladbus.query_bus("previous")

def finalize():
    import ctypes
    import ctypes.util
    import gtk
    import signal
    from blaplay import blacfg, blafm
    global metadata

    def main_quit(*args): gtk.main_quit()
    signal.signal(signal.SIGTERM, main_quit)
    signal.signal(signal.SIGINT, main_quit)

    gobject.set_prgname(blaconst.APPNAME)
    try:
        soname = ctypes.util.find_library("c")
        # 15 == PR_SET_NAME
        ctypes.CDLL(soname).prctl(15, blaconst.APPNAME, 0, 0, 0)
    except AttributeError: pass

    # set up the D-Bus interface and last.fm services
    bladbus.setup_bus()
    blafm.init()

    # get cached metadata
    _metadata = blautils.deserialize_from_file(blaconst.METADATA_PATH)
    if _metadata: metadata = _metadata

    gtk.quit_add(0, shutdown)
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

def shutdown():
    print_i("Cleaning up")

    from blaplay import blacfg, blaplayer
    player = blaplayer.player

    player.stop()
    blautils.BlaThread.clean_up()
    save_metadata()
    blacfg.save()

    fcntl.lockf(lock_file, fcntl.LOCK_UN)
    try: os.unlink(blaconst.PIDFILE)
    except OSError: pass

    return 0

