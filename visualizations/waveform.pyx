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

cimport cython
cimport numpy as np
from libc.stdlib cimport malloc, free

import gtk
import gst
import cairo
import numpy as np
import scipy.signal
resample = scipy.signal.resample

import blaplay
from blaplay import blacfg, blaconst, blautils

cdef extern from "math.h":
    float floorf(float)

f32 = np.float32
ctypedef np.float32_t f32_t

cdef int FS = 44100, DURATION = 200
cdef int SAMPLES = <int> floorf(FS * DURATION / 1000.0)

cdef class Waveform(object):
    identifier = "Waveform"
    property height:
        def __get__(self): return 60

    # variables needed to calculate the spectrum
    cdef object __lock
    cdef object __adapter
    cdef float *__buf

    # variables needed for drawing
    cdef int __width
    cdef float __padding
    cdef object __color_text
    cdef object __color_highlight
    cdef object __color_bg

    def __cinit__(self):
        self.__buf = NULL

    def __init__(self):
        self.__lock = blautils.BlaLock(strict=True)

        cdef int i
        self.__adapter = gst.Adapter()
        self.__buf = <float*> malloc(SAMPLES * 2 * sizeof(float))
        for i in xrange(SAMPLES * 2): self.__buf[i] = 0.0

    def __dealloc__(self):
        if self.__buf != NULL: free(self.__buf)
        self.__buf = NULL

    def __update_colors(self, style):
        if blacfg.getboolean("colors", "overwrite"):
            f = lambda c: gtk.gdk.color_parse(blacfg.getstring("colors", c))
            color_text, color_highlight, color_bg = map(
                    f, ["text", "highlight", "background"])
        else:
            color_text = style.text[gtk.STATE_NORMAL]
            color_highlight = style.base[gtk.STATE_ACTIVE]
            color_bg = style.bg[gtk.STATE_NORMAL]

        if (color_text != self.__color_text or
                color_highlight != self.__color_highlight or
                color_bg != self.__color_bg):
            self.__color_text = color_text
            self.__color_highlight = color_highlight
            self.__color_bg = color_bg

    @cython.cdivision(True)
    @cython.boundscheck(False)
    cpdef set_width(self, int width):
        self.__width = width
        self.__padding = <float> SAMPLES / self.__width

    @cython.boundscheck(False)
    cpdef new_buffer(self, object buf):
        # buffers are added and consumed in different threads so we need to
        # lock the GstAdapter as it's not thread-safe
        cdef int l
        with self.__lock:
            self.__adapter.push(buf)
            # when the main window is hidden the draw method isn't called which
            # means buffers are never flushed. therefore we make sure here that
            # we never store more than 500 ms worth of samples (two channels,
            # four bytes per sample, 22050 samples every 500 ms:
            # 44100 * 4 bytes)
            l = self.__adapter.available() - 44100 * 4
            if l > 0: self.__adapter.flush(l)

    @cython.boundscheck(False)
    cpdef flush_buffers(self):
        self.__adapter.flush(self.__adapter.available())

    @cython.cdivision(True)
    @cython.boundscheck(False)
    cpdef draw(self, object cr, object pc, object style):
        # get buffers from the adapter
        cdef np.ndarray[f32_t, ndim=1] np_buf
        with self.__lock:
            if self.__adapter.available() > 0:
                np_buf = np.frombuffer(self.__adapter.take_buffer(min(
                        self.__adapter.available(), SAMPLES * 2 * 4)),
                        dtype=f32
                )
            else: np_buf = np.zeros(SAMPLES * 2, f32)

        cdef int i, l
        cdef float *buf = self.__buf, *buf_new = <float*> np_buf.data
        l = min(len(np_buf), SAMPLES * 2)
        for i in xrange(l, SAMPLES * 2): buf[i-l] = buf[i]
        for i in xrange(l): buf[SAMPLES * 2 - l + i] = buf_new[i]

        # take the channel mean
        for i in xrange(SAMPLES): buf[i] = 0.5 * (buf[2*i] + buf[2*i+1])

        # update colors if necessary
        self.__update_colors(style)

        # draw the background
        cr.set_source_color(self.__color_bg)
        cr.rectangle(0, 0, self.__width, self.height)
        cr.fill()

        # setting the line width to 0.1 effectively reduces the opacity of the
        # line since we can't draw anything thinner than 1 px anyway
        cr.set_line_width(0.1)
        cr.set_source_color(self.__color_text)

        # draw the grid
        cdef float x, y, w = self.__width, h = self.height
        cdef int p = 2
        move_to = cr.move_to
        line_to = cr.line_to
        stroke = cr.stroke

        # horizontal grid
        y = floorf(h / 2) + 0.5
        move_to(p, y)
        line_to(w-p, y)
        stroke()

        # vertical grid
        cdef float f = floorf((w - 2*p) / 5.0)
        for i in xrange(4):
            x = (i+1) * f + 0.5
            move_to(x, p)
            line_to(x, h-p)
        stroke()

        # draw the graph
        cr.set_line_width(1.0)
        cr.set_source_color(self.__color_highlight)

        # TODO: perform frequency-domain resampling using fftw3
        pk = np.zeros(SAMPLES, f32)
        for i in xrange(SAMPLES): pk[i] = buf[i]
        pk = resample(pk, w)
        for i in xrange(<int> w - 1):
            y = 4 + (h-8) * (1-pk[i]) / 2.0
            move_to(i+0.5, y+0.5)
            y = 4 + (h-8) * (1-pk[i+1]) / 2.0
            line_to(i+1.5, y+0.5)
        stroke()

