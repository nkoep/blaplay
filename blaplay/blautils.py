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
import sys
import tempfile
import cPickle as pickle
import re
import shutil
import urllib
import hashlib
import webbrowser
import subprocess
import functools
from threading import Thread, ThreadError, Lock

import gtk

def get_thread_id():
    import ctypes
    lib = ctypes.CDLL("libc.so.6")
    return lib.syscall(186) # SYS_gettid

def thread(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        t = BlaThread(target=f, args=args, kwargs=kwargs)
        t.setDaemon(True)
        t.start()
        return t
    return wrapper

def gtk_thread(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        gtk.gdk.threads_init()
        gtk.gdk.threads_enter()
        f(*args, **kwargs)
        gtk.gdk.threads_leave()
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
    if uri.startswith("file://"): uri = uri[7:]
    elif uri.startswith("file:"): uri = uri[5:]
    uri = urllib.url2pathname(uri)
    return uri.strip("\n\r\x00")

def md5(string):
    m = hashlib.md5()
    m.update(string)
    return m.hexdigest()

def remove_html_tags(string):
    p = re.compile(r"<.*?>")
    return p.sub("", string)

@thread
def open_url(url):
    # redirect output of stdout to /dev/null for this thread to hide the status
    # message of the webbrowser module
    stdout = os.dup(1)
    os.close(1)
    os.open(os.devnull, os.O_RDWR)
    try: webbrowser.open(url, new=2)
    finally: os.dup2(stdout, 1)

def open_directory(directory):
    open_with_filehandler(
            directory, "Failed to open directory \"%s\"" % directory)

def open_with_filehandler(f, errmsg):
    try: subprocess.Popen(["gnome-open", f])
    except (OSError, ValueError):
        try: subprocess.Popen(["xdg-open", f])
        except (OSError, ValueError):
            error_dialog(errmsg)

def discover(d, directories_only=False):
    checked_directories = []
    if not hasattr(d, "__iter__"): d = [d]

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

    def __init__(self, strict=False):
        self.__strict = strict
        self.__lock = Lock()

    def acquire(self):
        self.__lock.acquire()

    def release(self):
        try: self.__lock.release()
        except ThreadError:
            if self.__strict: raise

    def locked(self):
        return self.__lock.locked()

    def __enter__(self, *args):
        self.acquire()

    def __exit__(self, *args):
        self.release()

class BlaThread(Thread):
    """ A kill'able thread class. """

    threads = []

    def __init__(self, *args, **kwargs):
        super(BlaThread, self).__init__(*args, **kwargs)

        # clean up when there's more than 100 threads in the reference list
        if len(BlaThread.threads) > 100:
            remove = BlaThread.threads.remove
            map(remove, [t for t in BlaThread.threads if not t.is_alive()])

        self.__killed = False
        BlaThread.threads.append(self)

    def start(self):
        self.__run_ = self.run
        self.run = self.__run
        Thread.start(self)

    def kill(self):
        self.__killed = True

    @classmethod
    def clean_up(cls):
        try:
            for t in cls.threads:
                t.kill()
                t._Thread__stop()
                while t.is_alive(): pass
        except AttributeError: pass

    def __run(self):
        sys.settrace(self.__globaltrace)
        self.__run_()
        self.run = self.__run_

    def __globaltrace(self, frame, why, arg):
        if why == "call": return self.__localtrace
        return None

    def __localtrace(self, frame, why, arg):
        if self.__killed and why == "line":
            BlaThread.threads.remove(self)
            raise SystemExit()
        return self.__localtrace

