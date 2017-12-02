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

import os
import fcntl

import gobject
gobject.threads_init()

import blaplay
from blaplay.blacore import blaconst

cli_queue = None


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
    parser.add_argument("-d", "--debug", action="count",
                        help="print debug messages")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="only print fatal messages")
    parser.add_argument("-h", "--help", action="help",
                        help="display this help and exit")
    parser.add_argument(
        "-v", "--version", action="version",
        help="output version information and exit\n\n",
        version="%s %s" % (blaconst.APPNAME, blaconst.VERSION))

    return vars(parser.parse_args())


def init_logging(args):
    import logging

    format_ = "*** %%(levelname)s%s: %%(message)s"

    debug = args["debug"]
    if debug:
        if debug == 1:
            format_ %= " (%(filename)s:%(lineno)d)"
        elif debug == 2:
            format_ %= " (%(asctime)s, %(filename)s:%(lineno)d)"
        else:
            raise SystemExit("Maximum debug level is 2")
        level = logging.DEBUG
    else:
        format_ %= ""
        level = logging.INFO
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


def process_args(args):
    from blaplay.blautil import bladbus
    # FIXME: bladbus needs to be treated differently
    global cli_queue

    # Parse URIs given on the command-line.
    if args["URI"]:
        if args["append"]:
            action = "append"
        elif args["new"]:
            action = "new"
        else:
            action = "replace"

        def normpath(uri):
            return os.path.normpath(os.path.abspath(uri))
        # TODO: make cli_queue a FIFO we write to here. then connect a handler
        #       which monitors the FIFO in the main thread and adds tracks as
        #       they arrive
        isfile = os.path.isfile
        cli_queue = (action, filter(isfile, map(normpath, args["URI"])))
    else:
        cli_queue = ("raise_window", None)


def create_instance_lock():
    # TODO: Make python2-dbus a hard-dependency and ensure singleton behavior
    #       with owned bus names.

    # Set up user directories if necessary.
    directories = [blaconst.CACHEDIR, blaconst.USERDIR, blaconst.COVERS,
                   blaconst.ARTISTS]

    if not all(map(os.path.isdir, directories)):
        print_i("Setting up user directories")
        for directory in directories:
            try:
                os.makedirs(directory)
            except OSError as (errno, strerror):
                # inode exists, but it's a file. We can only bail in this case
                # and just re-raise the exception.
                if errno != 17:
                    raise

    lock_file = open(blaconst.PIDFILE, "w")
    try:
        fcntl.lockf(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        print_i("%s is already running" % blaconst.APPNAME)
        from blaplay.blautil import bladbus
        global cli_queue
        try:
            bladbus.query_bus(*cli_queue)
        except TypeError:
            pass
        else:
            cli_queue = None
        raise SystemExit
    lock_file.write(str(os.getpid()))
    return lock_file


def remove_instance_lock(lock_file):
    fcntl.lockf(lock_file, fcntl.LOCK_UN)
    lock_file.close()
    try:
        os.unlink(blaconst.PIDFILE)
    except OSError:
        pass


def main():
    # Initialize signal handling like SIGINT.
    init_signals()
    # Parse command-line arguments.
    args = parse_args()
    # Initialize the logging interfaces.
    init_logging(args)
    # Process and handle any remaining command-line arguments.
    process_args(args)

    # If we made it this far, create a lock file that we use to guarantee only
    # one instance is running at a time. The lock is only valid as long as the
    # file descriptor is alive. That's why we need to keep it open (and
    # referenced) which is why we assign and hold it here for the rest of the
    # application lifetime.
    lock_file = create_instance_lock()
    # Fire up the main application.
    app = blaplay.Blaplay()
    # This blocks until the shutdown sequence is initiated.
    app.run()

    # Get rid of the lock file again.
    remove_instance_lock(lock_file)
    print_d("Shutdown complete")


if __name__ == "__main__":
    main()
