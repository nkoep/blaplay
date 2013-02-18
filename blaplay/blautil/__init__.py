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
import sys
import tempfile
import cPickle as pickle
import re
import shutil
import urllib
import urlparse
import hashlib
import webbrowser
import subprocess
import functools
from threading import Thread, ThreadError, Lock
import collections
import ctypes
import time

import gobject
import gtk

KEY, PREV, NEXT = xrange(3)


def signal(n_args):
    return (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (object,) * n_args)

def thread(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        t = BlaThread(target=f, args=args, kwargs=kwargs)
        t.daemon = True
        t.start()
        return t
    return wrapper

def thread_nondaemonic(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        t = Thread(target=f, args=args, kwargs=kwargs)
        t.start()
        return t
    return wrapper

# TODO: add optional argument to adjust the priority
def idle(f):
    @functools.wraps(f)
    def wrapper(*args):
        gobject.idle_add(f, *args)
    return wrapper

# there's nothing complicated about this decorator at all...
def lock(lock_):
    def func(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            with lock_: f(*args, **kwargs)
        return wrapper
    return func

def toss_extension(filepath):
    return os.path.splitext(filepath)[0]

def get_extension(filepath):
    return filepath.split(".")[-1]

def resolve_uri(uri):
    uri = urlparse.urlparse(uri).path
    uri = os.path.abspath(urllib.url2pathname(uri))
    return uri

def md5(string):
    m = hashlib.md5()
    m.update(string)
    return m.hexdigest()

def remove_html_tags(string):
    return re.sub(r"<.*?>", "", string)

def format_date(date):
    # parses a date tuple into a date string, e.g. Thursday 10. January 2013
    return time.strftime("%A %d %B %Y", time.localtime(time.mktime(date)))

@thread
def open_url(url):
    # redirect stdout to /dev/null for this thread to hide the status message
    # of the webbrowser module
    stdout = os.dup(1)
    os.dup2(os.open(os.devnull, os.O_RDWR), 1)
    try: webbrowser.open(url, new=2)
    except OSError: pass
    finally: os.dup2(stdout, 1)

def open_directory(directory):
    open_with_filehandler(
            directory, "Failed to open directory \"%s\"" % directory)

def open_with_filehandler(f, msg):
    with open(os.devnull, "w") as devnull:
        try:
            subprocess.Popen(
                    ["gnome-open", f], stdout=devnull, stderr=devnull)
        except (OSError, ValueError):
            try:
                subprocess.Popen(
                        ["xdg-open", f], stdout=devnull, stderr=devnull)
            except (OSError, ValueError): error_dialog(msg)

def discover(d, directories_only=False):
    checked_directories = []
    if not hasattr(d, "__iter__"):
        d = [d]

    realpath = os.path.realpath
    walk = os.walk
    append = checked_directories.append
    join = os.path.join

    for directory in d:
        directory = realpath(directory)
        for dirname, dirs, filenames in walk(directory, followlinks=True):
            dirname = realpath(dirname)
            if dirname not in checked_directories:
                append(dirname)
                if directories_only:
                    yield dirname
                    continue
            else: continue
            for filename in filenames: yield join(dirname, filename)

def serialize_to_file(data, path):
    # write data to tempfile
    fd, tmp_path = tempfile.mkstemp()
    f = os.fdopen(fd, "wb")
    pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
    f.flush()
    os.fsync(f.fileno())
    f.close()

    # move old file
    new_path = "%s.bak" % path
    try: os.unlink(new_path)
    except OSError: pass

    try: shutil.move(path, new_path)
    except IOError: pass

    # move tempfile to actual location and remove backup file on success
    try: shutil.move(tmp_path, path)
    except IOError: pass
    else:
        try: os.unlink(new_path)
        except OSError: pass

def deserialize_from_file(path):
    new_path = "%s.bak" % path
    data = None
    try: f = open(path, "rb")
    except IOError:
        try: f = open(new_path, "rb")
        except IOError: pass
    else:
        try: os.unlink(new_path)
        except OSError: pass

    # reading the file into memory first possibly reduces the number of context
    # switches compared to pickle.load(f)
    try: data = pickle.loads(f.read())
    except UnboundLocalError: pass
    except (EOFError, TypeError, pickle.UnpicklingError): f.close()

    return data


class BlaLock(object):
    """
    Simple wrapper class for the thread.lock class which only raises an
    exception when trying to release an unlocked lock if it's initialized with
    strict=True.
    """

    def __init__(self, strict=False, blocking=True):
        self.__strict = strict
        self.__blocking = blocking
        self.__lock = Lock()

    def acquire(self):
        self.__lock.acquire(self.__blocking)

    def release(self):
        try:
            self.__lock.release()
        except ThreadError:
            if self.__strict: raise

    def locked(self):
        return self.__lock.locked()

    def __enter__(self, *args):
        self.acquire()

    def __exit__(self, *args):
        self.release()

class BlaThread(Thread):
    """
    A kill'able thread class. This is certainly a bit of an overkill solution
    as the class inserts a bytecode trace which checks for the kill condition
    before every function call or line interpretation to break out of loops as
    soon as possible. However, it's the only way to make it work without adding
    kill condition checks to the threaded function/method itself. Additionally,
    it's the only way we can guarantee that daemonic threads are terminated
    before the interpreter shuts down. In theory this is supposed to be readily
    handled by threading.Thread. However, instead of suppressing exceptions
    from daemon threads on interpreter shutdown the Thread class tries to
    reconstruct the backtrace of the exception and prints it to stderr (which
    we can't catch). Those are (almost surely) AttributeError exceptions caused
    by accessing a member of a globals() dict which gets wiped clean by CPython
    on shutdown.
    """

    __threads = []

    def __init__(self, *args, **kwargs):
        super(BlaThread, self).__init__(*args, **kwargs)
        self.__killed = False
        BlaThread.__threads = filter(BlaThread.is_alive, BlaThread.__threads)
        BlaThread.__threads.append(self)

    def start(self):
        self.__run_ = self.run
        self.run = self.__run
        Thread.start(self)

    def kill(self):
        self.__killed = True

    @classmethod
    def kill_threads(cls):
        map(cls.kill, cls.__threads)

    def __run(self):
        sys.settrace(self.__globaltrace)
        self.__run_()
        self.run = self.__run_

    def __globaltrace(self, frame, event, arg):
        if event == "call": return self.__localtrace
        return None

    def __localtrace(self, frame, event, arg):
        try:
            if self.__killed and event == "line":
                BlaThread.__threads.remove(self)
                raise SystemExit
            return self.__localtrace
        except AttributeError:
            raise SystemExit

class BlaOrderedSet(collections.MutableSet):
    """
    set-like class which maintains the order in which elements were added.
    implementation from http://code.activestate.com/recipes/576694
    """

    def __init__(self, iterable=None):
        self.end = end = []
        end += [None, end, end]
        self.map = {}
        if iterable is not None: self |= iterable

    def __len__(self): return len(self.map)
    def __contains__(self, key): return key in self.map

    def add(self, key):
        if key not in self.map:
            end = self.end
            curr = end[PREV]
            curr[NEXT] = end[PREV] = self.map[key] = [key, curr, end]

    def discard(self, key):
        if key in self.map:
            key, prev, next = self.map.pop(key)
            prev[NEXT] = next
            next[PREV] = prev

    def __iter__(self):
        end = self.end
        curr = end[NEXT]
        while curr is not end:
            yield curr[KEY]
            curr = curr[NEXT]

    def __reversed__(self):
        end = self.end
        curr = end[PREV]
        while curr is not end:
            yield curr[KEY]
            curr = curr[PREV]

    def pop(self, last=True):
        if not self:
            raise KeyError("set is empty")
        key = next(reversed(self)) if last else next(iter(self))
        self.discard(key)
        return key

    def __repr__(self):
        if not self:
            return "%s()" % (self.__class__.__name__,)
        return "%s(%r)" % (self.__class__.__name__, list(self))

    def __eq__(self, other):
        if isinstance(other, OrderedSet):
            return len(self) == len(other) and list(self) == list(other)
        return set(self) == set(other)

    def __del__(self):
        self.clear()

