### Introduction

**blaplay** is a minimalist media player for GNU/Linux with a clean and
clutter-free user interface. It is written in Python and uses GTK+, GStreamer
and Mutagen to implement its core functionality. Notable features include a
monitored media library, a flexible playlist-centric layout, automatic cover
art and lyrics retrieval, as well as MPRIS2 support. In addition, it tightly
integrates last.fm's web services to support scrobbling and manage favorite
songs. Its feature set is kept small by design, and as such there are no
plans to add a full-fledged plugin system in the future.

Below is a list of (hard) dependencies and recommended packages. Considering
the heterogeneity of Linux distributions and package naming conventions, the
following dependencies correspond to their respective Debian package names.

#### Runtime dependencies:
* python (>= 2.7)
* python-gtk2 (>= 2.22)
* python-gst0.10
* python-mutagen (>= 1.19)
* python-gobject (>= 2.21)
* python-numpy (>= 1.3)
* python-dbus (>= 1.2.4)

#### Recommended:
* gstreamer0.10-plugins-good
* gstreamer0.10-plugins-bad
* gstreamer0.10-plugins-ugly
* python-keybinder
