# Copyright 2004 Joe Wreschnig. Released under the terms of the GNU GPL.

PYTHON_VERSION = `python2 -c 'import sys; print sys.version[:3]'`
CFLAGS += -O2 -fPIC `pkg-config --cflags gtk+-2.0 pygtk-2.0` \
	-I/usr/include/python$(PYTHON_VERSION)
LDFLAGS += `pkg-config --libs gtk+-2.0 pygtk-2.0`

mmkeys.so: mmkeyspy.o mmkeys.o mmkeysmodule.o
	$(CC) $(LDFLAGS) -shared $^ -o $@

DEFS=`pkg-config --variable=defsdir pygtk-2.0`

mmkeyspy.c: mmkeys.defs mmkeys.override
	pygobject-codegen-2.0 --prefix mmkeys \
	--register $(DEFS)/gdk-types.defs \
	--register $(DEFS)/gtk-types.defs \
	--override mmkeys.override \
	mmkeys.defs > gen-tmp
	mv gen-tmp $@

clean:
	rm -f mmkeys.so *.o mmkeyspy.c

distclean: clean
	rm -f *~ gen-tmp
