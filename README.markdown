### blaplay

**blaplay** is a media player for GNU/Linux with a clean and uncluttered user
interface. It is written in Python and uses PyGTK, PyGST and Mutagen to
implement its core functionality. Notable features include a monitored media
library, automatic cover art, lyrics and biography fetching, as well as support
for internet radio streams and video playback. It tightly integrates last.fm's
web services to support scrobbling, manage favorite songs, retrieve song and
artist metadata, and provide event and release recommendations based on the
user's last.fm library.

#### Installation
blaplay currently includes audio visualizations based on fftw3 which are
written in Cython to push computationally expensive operations to C code.
Building blaplay therefore requires a recent version of the Cython compiler as
well as the single-precision library of fftw3 and its development headers. To
prepare and run blaplay locally, issue
```bash
  $ ./setup.py build_ext --inplace
  $ ./blaplay.py
```

after having satisfied all build dependencies. To install blaplay system-wide
and run it, simply issue
```bash
  $ ./setup.py install
  $ blaplay
```

Below is a list of dependencies and recommended packages. Considering the
heterogeneity of Linux distributions and package naming conventions, the
following dependencies correspond to their respective Debian package names.

#### Build dependencies:
* python-dev (>= 2.7)
* Cython (>= 0.15.1)
* libfftw3-dev (>= 3.2.2)

#### Runtime dependencies:
* python (>= 2.7)
* python-gtk2 (>= 2.22)
* python-gst0.10
* python-numpy
* python-mutagen (>= 1.19)
* python-gobject (>= 2.21)
* libfftw3-3 (>= 3.2.2)

#### Recommended:
* gstreamer0.10-plugins-good
* gstreamer0.10-plugins-bad
* gstreamer0.10-plugins-ugly
* python-keybinder
* python-dbus (>= 0.83)


Note that the shebang of both setup.py and blaplay.py reads:
```
#!/usr/bin/env python2
```
This conforms to the way Arch Linux (among others) treats different Python
versions these days where \`python' is usually symlinked to some version of
Python 3, while \`python2' refers to the latest installed version of Python 2.

