#!/usr/bin/env python2
# -*- coding: utf-8 -*-

import os
import sys
import shutil
import subprocess
try: import numpy as np
except ImportError: pass
from distutils.core import setup, Command, Distribution
from distutils.command.clean import clean as d_clean
from distutils.dep_util import newer
from distutils.util import change_root
from distutils.command.build import build as d_build
from distutils.command.build_scripts import build_scripts as d_build_scripts
from distutils.command.install import install as d_install
from distutils.extension import Extension
from Cython.Distutils import build_ext

from blaplay import blaconst, blautils


def exec_(args, split=True, cwd="."):
    p = subprocess.Popen(args, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
    p = p.communicate()[0]
    return p.split() if split else p

class clean(d_clean):
    def run(self):
        d_clean.run(self)

        base = os.path.dirname(__file__)

        for mod in self.distribution.ext_modules:
            paths = ["%s.c" % blautils.toss_extension(src)
                    for src in mod.sources if "mmkeys" not in src]
            paths.append(
                os.path.join(base, "%s.so" % mod.name.replace(".", "/")))
            for f in paths:
                try:
                    print "removing '%s'" % f
                    os.unlink(f)
                except OSError: pass

        if not self.all: return

        for directory in ["build", "dist"]:
            path = os.path.join(base, directory)
            if os.path.isdir(path): shutil.rmtree(path)

class check(Command):
    description = "check installation requirements"
    user_options = []
    __NAME = "blaplay"

    def initialize_options(self): pass
    def finalize_options(self): pass

    def run(self):
        print "Checking Python version >= 2.6:",
        print ".".join(map(str, sys.version_info[:2]))
        if sys.version_info < (2, 6):
            raise SystemExit("%s requires at least Python 2.6. "
                    "(http://www.python.org)" % self.__NAME)

        print "Checking for PyGTK >= 2.21:",
        try:
            import pygtk
            pygtk.require("2.0")
            import gtk
            if gtk.pygtk_version < (2, 21) or gtk.gtk_version < (2, 21):
                raise ImportError
        except ImportError:
            raise SystemExit("not found\n%s requires PyGTK 2.21. "
                             "(http://www.pygtk.org)" % self.__NAME)
        else: print "found"

        print "Checking for gst-python >= 0.10.21:",
        try:
            import pygst
            pygst.require("0.10")
            import gst
            if gst.pygst_version < (0, 10, 21): raise ImportError
        except ImportError:
            have_pygst = False
            print "not found"
        else:
            have_pygst = True
            print "found"

        print "Checking for Mutagen >= 1.19:",
        try:
            import mutagen
            if mutagen.version < (1, 19): raise ImportError
        except ImportError:
            raise SystemExit("not found\n%s requires Mutagen 1.19.\n"
                "(http://code.google.com/p/mutagen/downloads/list)" %
                self.__NAME)
        else: print "found"

        print "Checking for PyGObject >= 2.21:",
        try:
            import gobject
            if gobject.pygobject_version < (2, 21): raise ImportError
        except ImportError:
            raise SystemExit("not found\n%s requires PyGObject 2.21.\n"
                "(https://live.gnome.org/PyGObject)" %
                self.__NAME)
        else: print "found"

        print "Checking for Cython >= 0.15.1:",
        try:
            import Cython
            if Cython.__version__ < "0.15.1": raise ImportError
        except ImportError:
            raise SystemExit("not found\n%s requires Cython 0.15.1.\n"
                "(http://http://www.cython.org/#download)" %
                self.__NAME)
        else: print "found"

        print "Checking for numpy >= 1.3:",
        try:
            import numpy.version
            if numpy.version.version < "1.3": raise ImportError
        except ImportError:
            raise SystemExit("not found\n%s requires python-numpy 1.3.\n"
                % self.__NAME)
        else: print "found"

class build_scripts(d_build_scripts):
    description = "copy scripts to build directory"

    def run(self):
        base = os.path.dirname(__file__)

        self.mkpath(self.build_dir)
        for script in self.scripts:
            newpath = os.path.join(
                    base, self.build_dir, os.path.basename(script))
            if newpath.lower().endswith(".py"):
                newpath = blautils.toss_extension(newpath)
            if newer(script, newpath) or self.force:
                self.copy_file(script, newpath)

class build_shortcuts(Command):
    build_base = None

    def initialize_options(self): pass

    def finalize_options(self):
        self.shortcuts = self.distribution.shortcuts
        self.set_undefined_options("build", ("build_base", "build_base"))

    def run(self):
        basepath = os.path.join(self.build_base, "share", "applications")
        self.mkpath(basepath)
        for shortcut in self.shortcuts:
            print shortcut, os.path.join(basepath, shortcut)
            self.copy_file(shortcut, os.path.join(basepath, shortcut))

class update_icon_cache(Command):
    def initialize_options(self): pass
    def finalize_options(self): pass

    def run(self):
        icon_dir = os.path.join(sys.prefix, "share/icons/hicolor")
        if os.access(icon_dir, os.W_OK):
            self.spawn(["gtk-update-icon-cache", "-f", icon_dir])

class install_shortcuts(Command):
    description = "install .desktop files"

    prefix = None
    skip_build = None
    shortcuts = None
    build_base = None
    root = None

    def initialize_options(self):
        pass

    def finalize_options(self):
        self.set_undefined_options("build", ("build_base", "build_base"))
        self.set_undefined_options("install", ("root", "root"),
                ("install_base", "prefix"), ("skip_build", "skip_build"))
        self.set_undefined_options(
                "build_shortcuts", ("shortcuts", "shortcuts"))

    def run(self):
        if not self.skip_build: self.run_command("build_shortcuts")
        basepath = os.path.join(self.prefix, "share", "applications")
        if self.root != None: basepath = change_root(self.root, basepath)
        srcpath = os.path.join(self.build_base, "share", "applications")
        self.mkpath(basepath)
        for shortcut in self.shortcuts:
            fullsrc = os.path.join(srcpath, shortcut)
            fullpath = os.path.join(basepath, shortcut)
            self.copy_file(fullsrc, fullpath)

class build(d_build):
    """Override the default build with new subcommands."""
    sub_commands = d_build.sub_commands
    sub_commands.extend([("build_shortcuts", lambda *x: True)])

class install(d_install):
    sub_commands = d_install.sub_commands
    # update the icon cache only after moving icons to the system directories
    sub_commands.extend([("install_shortcuts", lambda *x: True),
            ("update_icon_cache", lambda *x: True)])

class BlaDistribution(Distribution):
    shortcuts = []

    def __init__(self, *args, **kwargs):
        Distribution.__init__(self, *args, **kwargs)
        self.cmdclass.setdefault("build_shortcuts", build_shortcuts)
        self.cmdclass.setdefault("update_icon_cache", update_icon_cache)
        self.cmdclass.setdefault("install_shortcuts", install_shortcuts)
        self.cmdclass.setdefault("build", build)
        self.cmdclass.setdefault("install", install)

if __name__ == "__main__":
    description = "Minimalistic audio player for GNU/Linux written in Python"

    # visualizations
    visualizations = [f for f in os.listdir("visualizations") if
            blautils.get_extension(f) == "pyx"]
    extra_compile_args = ["-std=gnu99"]
    try: extra_compile_args.append("-I%s" % np.get_include())
    except NameError: pass
    ext_modules = [Extension("blaplay.visualizations.%s"
            % blautils.toss_extension(f), ["visualizations/%s" % f],
            libraries=["fftw3f"], extra_compile_args=extra_compile_args)
            for f in visualizations
    ]

    # mmkeys
    defs = exec_(
        "pkg-config --variable=defsdir pygtk-2.0".split())
    defs = " ".join(map(str.strip, defs))
    name = "_mmkeys"
    mmkeyspy = exec_((
        """pygobject-codegen-2.0 --prefix %s
        --register %s/gdk-types.defs
        --register %s/gtk-types.defs
        --override mmkeys.override
        mmkeys.defs""" % (name, defs, defs)).split(), split=False, cwd="mmkeys"
    )
    with open("mmkeys/mmkeyspy.c", "w") as f:
        f.write(mmkeyspy)
    ext_modules.append(Extension("blaplay.%s" % name, ["mmkeys/%s" % f
            for f in ("mmkeyspy.c", "mmkeys.c", "mmkeysmodule.c")],
            extra_compile_args=exec_(
            "pkg-config --cflags gtk+-2.0 pygtk-2.0".split()),
            extra_link_args=exec_(
            "pkg-config --libs gtk+-2.0 pygtk-2.0".split()))
    )

    src_base = "blaplay/images"
    images_comps = []
    for dirname, dirs, filenames in os.walk(src_base):
        for filename in filenames:
            images_comps.append(
                    os.path.join(dirname, filename)[len(src_base)+1:])

    base = os.path.join(sys.prefix, "share/icons/hicolor")
    src_base = "blaplay/images/hicolor"
    data_files = []
    for dirname, dirs, filenames in os.walk(src_base):
        for filename in filenames:
            src_leaf = os.path.join(dirname, filename)
            leaf = os.path.dirname(
                    os.path.join(base, src_leaf[len(src_base)+1:]))
            data_files.append((leaf, [src_leaf]))

    kwargs = {
        "name": blaconst.APPNAME,
        "version": blaconst.VERSION,
        "author": blaconst.AUTHOR,
        "author_email": blaconst.EMAIL,
        "url": blaconst.WEB,
        "description": description,
        "license": "GNU GPL v2",
        "packages": ["blaplay"] + ["blaplay.%s" % module
                for module in ["blagui", "formats", "visualizations"]],
        "package_data": {
            "": ["ChangeLog", "TODO"],
            "blaplay": ["images/%s" % comp for comp in images_comps]
        },
        "data_files": data_files,
        "scripts": ["blaplay.py"],
        "shortcuts": ["blaplay.desktop"],
        "distclass": BlaDistribution,
        "cmdclass": {
            "clean": clean,
            "check": check,
            "build_ext": build_ext,
            "build_scripts": build_scripts
        },
        "ext_modules": ext_modules
    }
    setup(**kwargs)

