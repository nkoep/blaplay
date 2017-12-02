#!/usr/bin/env python2
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
import fcntl

import gobject
gobject.threads_init()

import blaplay
from blaplay.blacore import blaconst
# TODO: Move bladbus to core
from blaplay.blautil import bladbus


def init_signals():
    def main_quit(*args):
        def idle_quit():
            blaplay.shutdown()
        gobject.idle_add(idle_quit, priority=gobject.PRIORITY_HIGH)
        return False

    r, w = os.pipe()
    gobject.io_add_watch(r, gobject.IO_IN, main_quit)

    import signal
    for sig in [signal.SIGTERM, signal.SIGINT, signal.SIGHUP]:
        signal.signal(sig, lambda *x: os.write(w, "bla")) # What else?


def parse_args():
    from argparse import ArgumentParser, RawTextHelpFormatter

    parser = ArgumentParser(
        add_help=False, description="%s - A bla that plays" % blaconst.APPNAME,
        prog=blaconst.APPNAME, formatter_class=RawTextHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-c", "--append", action="store_true",
                       help="Append URIs to current playlist")
    group.add_argument("-t", "--new", action="store_true",
                       help="Send URIs to new playlist")
    parser.add_argument(
        "URI", nargs="*", help="Input to be sent to the current playlist "
        "unless\noption -c or -n is specified")
    parser.add_argument("-d", "--debug", action="count", default=0,
                        dest="debug_level", help="print debug messages")
    parser.add_argument("-h", "--help", action="help",
                        help="display this help and exit")
    parser.add_argument(
        "-v", "--version", action="version",
        help="output version information and exit\n\n",
        version="%s %s" % (blaconst.APPNAME, blaconst.VERSION))

    return vars(parser.parse_args())


def init_logging(debug_level):
    import logging

    format_ = "*** %%(levelname)s%s: %%(message)s"
    level = logging.DEBUG

    if debug_level == 0:
        format_ %= ""
        level = logging.INFO
    elif debug_level == 1:
        format_ %= " (%(filename)s:%(lineno)d)"
    elif debug_level == 2:
        format_ %= " (%(asctime)s, %(filename)s:%(lineno)d)"
    else:
        raise SystemExit("Maximum debug level is 2")

    logging.basicConfig(format=format_, level=level,
            datefmt="%a %b %d %H:%M:%S %Y")

    colors = [
        (logging.INFO, "32"), (logging.DEBUG, "34"),
        (logging.WARNING, "31"), (logging.CRITICAL, "36")
    ]
    for level, color in colors:
        logging.addLevelName(level, "\033[1;%sm%s\033[1;m" %
                             (color, logging.getLevelName(level)))

    __builtins__.__dict__["print_d"] = logging.debug
    __builtins__.__dict__["print_i"] = logging.info
    __builtins__.__dict__["print_w"] = logging.warning
    __builtins__.__dict__["print_c"] = logging.critical
    def _die(msg):
        print_c(msg)
        sys.exit(1)
    __builtins__.__dict__["die"] = _die


def parse_uris(args):
    if args["append"]:
        action = "append"
    elif args["new"]:
        action = "new"
    else:
        action = "replace"

    def normalize_path(uri):
        return os.path.normpath(os.path.abspath(uri))
    # TODO: make cli_queue a FIFO we write to here. then connect a handler
    #       which monitors the FIFO in the main thread and adds tracks as
    #       they arrive
    isfile = os.path.isfile
    return action, filter(isfile, map(normalize_path, args["URI"]))


def main():
    # Initialize signal handling like SIGINT.
    init_signals()
    # Parse command-line arguments.
    args = parse_args()
    # Initialize the logging interfaces.
    init_logging(args["debug_level"])
    # Parse URIs.
    action, uris = parse_uris(args)

    # We use dbus to ensure that only one instance of blaplay is running at a
    # time by claiming a unique bus name. That means if we manage to get an
    # interface to the proxy object, we simply handle the command-line
    # arguments, raise the main window and exit.
    interface = bladbus.get_interface()
    if interface is not None:
        interface.raise_window()
        interface.handle_uris(action, uris)
        sys.exit()

    # Create the required application directories.
    blaplay.create_user_directories()

    # Instantiate the main application class.
    app = blaplay.Blaplay()

    # TODO: Handle command-line URIs.

    # This blocks until the shutdown sequence is initiated.
    app.run()

    print_d("Shutdown complete")


if __name__ == "__main__":
    main()
