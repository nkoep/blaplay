#!/usr/bin/env python2
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
import fcntl

import gobject

from blaplay.blacore import blaconst

lock_file = None
cli_queue = None


def init_signals():
    import signal

    def main_quit(*args):
        def idle_quit():
            import blaplay
            try: blaplay.bla.window.destroy()
            except AttributeError: pass
        gobject.idle_add(idle_quit, priority=gobject.PRIORITY_HIGH)
        return False

    # writing to a file descriptor that's monitored by gobject is buffered,
    # i.e. we can write to it here and the event gets handled as soon as a main
    # loop is started. we use this to defer shutdown instructions during
    # startup
    r, w = os.pipe()
    gobject.io_add_watch(r, gobject.IO_IN, main_quit)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda sig, frame: os.write(w, "bla"))

def parse_args():
    from argparse import ArgumentParser, RawTextHelpFormatter

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

def init_logging(debug, quiet):
    import __builtin__
    import logging

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

    def critical(msg):
        logging.critical(msg)
        raise SystemExit

    __builtin__.__dict__["print_d"] = logging.debug
    __builtin__.__dict__["print_i"] = logging.info
    __builtin__.__dict__["print_w"] = logging.warning
    __builtin__.__dict__["print_c"] = critical

def process_args(args):
    from blaplay.blautil import bladbus
    # FIXME: bladbus needs to be treated differently
    global cli_queue

    # player info formatting
    if args["format"]: bladbus.query_bus(args["format"][0])

    if args["URI"]:
        if args["append"]: action = "append"
        elif args["new"]: action = "new"
        else: action = "replace"
        n = lambda uri: os.path.normpath(os.path.abspath(uri))
        # TODO: make cli_queue a FIFO we write to here. then connect a handler
        #       which monitors the FIFO in the main thread and adds tracks as
        #       they arrive
        cli_queue = (action, map(n, args["URI"]))
    else: cli_queue = ("raise_window", None)

    # player commands
    for cmd in ["play_pause", "stop", "next", "previous"]:
        if args[cmd]: bladbus.query_bus(cmd)

    if args["play_pause"]: bladbus.query_bus("play_pause")
    elif args["stop"]: bladbus.query_bus("stop")
    elif args["next"]: bladbus.query_bus("next")
    elif args["previous"]: bladbus.query_bus("previous")

def force_singleton():
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

    # we use a lock file to ensure a singleton for blaplay. however, the lock
    # is only valid as long as the file descriptor is valid. that's why we need
    # to keep it open (and referenced)
    global lock_file
    lock_file = open(blaconst.PIDFILE, "w")
    try: fcntl.lockf(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        print_i("%s is already running" % blaconst.APPNAME)
        from blaplay.blautil import bladbus
        global cli_queue
        try: bladbus.query_bus(*cli_queue)
        except TypeError: pass
        else: cli_queue = None
        raise SystemExit
    lock_file.write(str(os.getpid()))

def main():
    init_signals()

    args = parse_args()

    init_logging(args["debug"], args["quiet"])

    process_args(args)

    force_singleton()

    # finish startup
    import blaplay
    blaplay.finalize()

    # clean up lock file
    fcntl.lockf(lock_file, fcntl.LOCK_UN)
    lock_file.close()
    try: os.unlink(blaconst.PIDFILE)
    except OSError: pass

    print_d("Shutdown complete")

if __name__ == "__main__":
    main()

