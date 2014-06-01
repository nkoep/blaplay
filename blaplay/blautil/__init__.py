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
import ctypes
import ctypes.util
import re
import shutil
import urllib
import urlparse
import hashlib
import webbrowser
import subprocess
import inspect
import functools
from threading import Thread, ThreadError, Lock
import collections
import time

import gio
import gobject


def cdll(lib):
    soname = ctypes.util.find_library(lib)
    if soname is None:
        raise OSError("No shared library for '%s' found" % lib)
    return ctypes.CDLL(soname)

def thread_id():
    # From bits/syscall.h: 186 == SYS_gettid
    return cdll("c").syscall(186)

def clamp(min_, max_, value):
    if min_ > max_:
        raise ValueError("Lower bound must be smaller or equal to upper bound")
    return max(min_, min(max_, value))

def signal(n_args):
    return (gobject.SIGNAL_RUN_LAST | gobject.SIGNAL_ACTION,
            gobject.TYPE_NONE, (object,) * n_args)

def thread(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        t = BlaThread(target=func, args=args, kwargs=kwargs)
        t.daemon = True
        t.start()
        return t
    return wrapper

def thread_nondaemonic(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        t = Thread(target=func, args=args, kwargs=kwargs)
        t.start()
        return t
    return wrapper

def idle(func=None, **kwargs):
    # There is one case we cannot avoid which is `@idle(some_callable)' as this
    # looks like the regular use case
    #   @idle
    #   def some_func...
    # to us. Most other misuses should be handled properly though.

    if len(kwargs) > 1:
        raise ValueError("Only one keyword argument allowed")
    elif kwargs and "priority" not in kwargs:
        raise ValueError("Invalid keyword argument '%s'" % kwargs.keys()[0])

    if func is None:
        if not kwargs:
            raise ValueError("Keyword argument 'priority' expected")
        def wrapper(func):
            return idle(func, **kwargs)
        return wrapper

    @functools.wraps(func)
    def wrapper(*args):
        priority = kwargs.get("priority", gobject.PRIORITY_DEFAULT_IDLE)
        return gobject.idle_add(func, *args, priority=priority)
    return wrapper

def lock(lock_):
    def wrapper_(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with lock_:
                func(*args, **kwargs)
        return wrapper
    return wrapper_

def caches_return_value(func):
    """
    Caches the return value of the decorated function. Note that this does not
    support calling the decorated function with keyword arguments. For obvious
    reasons, it is only useful for pure functions that do not depend on global
    state and only accept immutable argument types.
    """

    if inspect.getargspec(func).keywords is not None:
        raise ValueError(
            "Decorator does not support functions with keyword arguments")

    _cache = {}

    @functools.wraps(func)
    def wrapper(*args):
        key = args
        try:
            value = _cache[key]
        except KeyError:
            value = _cache[key] = func(*args)
        return value
    return wrapper

def toss_extension(filepath):
    return os.path.splitext(filepath)[0]

def get_extension(filepath):
    return filepath.split(".")[-1]

def resolve_uris(uris):
    # The argument might be a tuple or a list. Either way turn it into a new
    # list so we don't mutate the iterable `uris' references when first calling
    # this function.
    uris = list(uris)
    parse_url = urlparse.urlparse
    url2pathname = urllib.url2pathname
    abspath = os.path.abspath
    for idx, uri in enumerate(uris):
        parse_result = parse_url(uri)
        # For relative URIs like file://some_file.mp3, the filename appears in
        # the network location attribute.
        uri = parse_result.path or parse_result.netloc
        if uri:
            uris[idx] = abspath(url2pathname(uri))
    return uris

def filepaths2uris(paths):
    quote = urllib.quote
    urljoin = urlparse.urljoin
    return [urljoin("file:", quote(filepath)) for filepath in paths]

def get_mimetype(path):
    file_ = gio.File(path)
    try:
        return file_.query_info("standard::content-type").get_content_type()
    except gio.Error:
        return ""

def md5(string):
    m = hashlib.md5()
    m.update(string)
    return m.hexdigest()

def remove_html_tags(string):
    return re.sub(r"<.*?>", "", string)

def format_date(date):
    # Parse a date tuple into a date string, e.g. Thursday 10. January 2013.
    return time.strftime("%A %d %B %Y", time.localtime(time.mktime(date)))

@thread
def open_url(url):
    # Redirect stdout to /dev/null for this thread to hide the status message
    # of the webbrowser module.
    stdout = os.dup(1)
    os.dup2(os.open(os.devnull, os.O_RDWR), 1)
    try:
        webbrowser.open(url, new=2)
    except OSError:
        pass
    finally:
        os.dup2(stdout, 1)

def open_directory(directory):
    open_with_filehandler(
        directory, "Failed to open directory \"%s\"" % directory)

def open_with_filehandler(f, msg):
    with open(os.devnull, "w") as devnull:
        try:
            subprocess.Popen(["gnome-open", f], stdout=devnull, stderr=devnull)
        except (OSError, ValueError):
            try:
                subprocess.Popen(
                    ["xdg-open", f], stdout=devnull, stderr=devnull)
            except (OSError, ValueError):
                error_dialog(msg)

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
            else:
                continue
            for filename in filenames:
                yield join(dirname, filename)

def serialize_to_file(data, path):
    # Write data to tempfile first.
    fd, tmp_path = tempfile.mkstemp()
    f = os.fdopen(fd, "wb")
    pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
    f.flush()
    os.fsync(f.fileno())
    f.close()

    # Move old file
    new_path = "%s.bak" % path
    try:
        os.unlink(new_path)
    except OSError:
        pass

    try:
        shutil.move(path, new_path)
    except IOError:
        pass

    # Move the tempfile to its proper location and remove the backup file on
    # success.
    try:
        shutil.move(tmp_path, path)
    except IOError:
        pass
    else:
        try:
            os.unlink(new_path)
        except OSError:
            pass

def deserialize_from_file(path):
    new_path = "%s.bak" % path
    data = None
    try:
        f = open(path, "rb")
    except IOError:
        try:
            f = open(new_path, "rb")
        except IOError:
            pass
    else:
        try:
            os.unlink(new_path)
        except OSError:
            pass

    # Reading the file into memory first allegedly reduces the number of
    # context switches compared to pickle.load(f).
    try:
        data = pickle.loads(f.read())
    except UnboundLocalError:
        pass
    except (EOFError, TypeError, pickle.UnpicklingError):
        f.close()

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
            if self.__strict:
                raise

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
        self.__threads.append(self)
        if len(self.__threads) > 25:
            # Use slice notation to mutate the referent, not the reference.
            self.__threads[:] = filter(BlaThread.is_alive, self.__threads)

    def run(self):
        sys.settrace(self.__globaltrace)
        Thread.run(self)

    def kill(self):
        self.__killed = True

    @classmethod
    def kill_threads(cls):
        map(cls.kill, cls.__threads)

    def __globaltrace(self, frame, event, arg):
        if event == "call":
            return self.__localtrace
        else:
            print_w("GLOBAL TRACE: " + event)
        return None

    def __localtrace(self, frame, event, arg):
        if self.__killed and event == "line":
            raise SystemExit
        return self.__localtrace

class BlaOrderedSet(collections.MutableSet):
    """
    set-like class which maintains the order in which elements were added.
    Modified version of http://code.activestate.com/recipes/576694
    """

    __KEY, __PREV, __NEXT = xrange(3)

    def __init__(self, iterable=None):
        self.end = end = []
        end += [None, end, end]
        self.map = {}
        if iterable is not None:
            self |= iterable

    def __len__(self):
        return len(self.map)

    def __contains__(self, key):
        return key in self.map

    def add(self, key):
        if key not in self.map:
            end = self.end
            curr = end[self.__PREV]
            curr[self.__NEXT] = end[self.__PREV] = self.map[key] = [
                key, curr, end]

    def discard(self, key):
        if key in self.map:
            key, prev, next = self.map.pop(key)
            prev[self.__NEXT] = next
            next[self.__PREV] = prev

    def __iter__(self):
        end = self.end
        curr = end[self.__NEXT]
        while curr is not end:
            yield curr[self.__KEY]
            curr = curr[self.__NEXT]

    def __reversed__(self):
        end = self.end
        curr = end[self.__PREV]
        while curr is not end:
            yield curr[self.__KEY]
            curr = curr[self.__PREV]

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

class BlaNotifyDict(dict):
    __slots__ = ("__callbacks")

    def __init__(self, *args, **kwargs):
        super(BlaNotifyDict, self).__init__(*args, **kwargs)
        self.__callbacks = []

    def connect(self, callback, user_data=()):
        self.__callbacks.append((callback, user_data))

    def __notify_wrap(method):
        def wrapper(self, *args, **kwargs):
            result = method(self, *args, **kwargs)
            for callback, user_data in self.__callbacks:
                callback(self, *user_data)
            return result
        return wrapper

    __setitem__ = __notify_wrap(dict.__setitem__)
    pop = __notify_wrap(dict.pop)
    popitem = __notify_wrap(dict.popitem)
    update = __notify_wrap(dict.update)
    __delitem__ = __notify_wrap(dict.__delitem__)
    clear = __notify_wrap(dict.clear)

# Note that assignment to an existing key is still possible by deleting the
# relevant entry first. It's still a decent precautionary measure to avoid
# accidental overrides of existing keys.
class BlaFrozenDict(dict):
    def setdefault(self, keys, default=None):
        raise NotImplementedError("Method not supported")

    def __setitem__(self, key, value):
        if key in self:
            raise ValueError("Entry for key '%s' already exists" % key)
        super(BlaFrozenDict, self).__setitem__(key, value)

class BlaInitiallyHidden(object):
    """
    Class hides  guarantees
    """

    def __new__(cls):
        if not gtk.Widget in cls.__bases__:
            raise TypeError("Class must have gtk.Widget in its bases")
        return super(BlaInitiallyHidden, cls).__new__(cls)

    def __init__(self):
        self._callback_id = self.connect_object(
            "map", BlaInitiallyHidden._on_map, self)

    def _on_map(self):
        self.disconnect(self._callback_id)
        self.set_visible(False)

