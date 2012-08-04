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

# TODO: - test the results/performance of performing constant-q/mfc transforms
#       - test sinc-interpolation for the transformation to log-scale
#       - test least-squares spectral analysis:
#         http://en.wikipedia.org/wiki/Least-squares_spectral_analysis
#       - test LPSD:
#         https://github.com/tobin/lpsd/blob/master/lpsd_demo.m

cimport cython
cimport numpy as np

from time import time
import ctypes
import ctypes.util

import gtk
import gst
import cairo
import pango
import numpy as np

import blaplay
from blaplay import blacfg, blaconst

cdef extern from "math.h":
    float fmaxf(float, float)
    float fminf(float, float)
    float logf(float)
    float log10f(float)
    float expf(float)
    float powf(float, float)
    float ceilf(float)
    float floorf(float)

cdef extern from "fftw3.h":
    ctypedef float fftwf_complex[2]
    struct fftwf_plan_s:
        pass
    ctypedef fftwf_plan_s *fftwf_plan

    void *fftwf_malloc(size_t size)
    void fftwf_destroy_plan(fftwf_plan plan)
    void fftwf_free(void *p)
    fftwf_plan fftwf_plan_dft_r2c_1d(size_t size, float *in_,
            fftwf_complex *out_, unsigned flags)
    void fftwf_execute(fftwf_plan plan)

cdef enum:
    FFTW_EXHAUSTIVE = 1 << 3

f32 = np.float32
ctypedef np.float32_t f32_t

cdef int BANDS_MAX = 195, NFFT = 4096, FS = 44100
cdef float eps = np.finfo(f32).eps, OFFSET = 2 * log10f(NFFT)

# getting stored wisdom seems easier using ctypes than cython
soname = ctypes.util.find_library("fftw3f")
if soname is None:
    raise ImportError("Failed to locate the single-precision library of fftw3")
lib = ctypes.cdll.LoadLibrary(soname)

PyFile_AsFile = ctypes.pythonapi.PyFile_AsFile
PyFile_AsFile.argtypes = [ctypes.py_object]
PyFile_AsFile.restype = ctypes.c_void_p

lib.fftwf_import_wisdom_from_file.argtypes = [ctypes.c_void_p]
lib.fftwf_import_wisdom_from_file.restype = ctypes.c_int
lib.fftwf_export_wisdom_to_file.argtypes = [ctypes.c_void_p]
lib.fftwf_export_wisdom_to_file.restype = None

try:
    with open(blaconst.WISDOM_PATH, "r") as f:
        lib.fftwf_import_wisdom_from_file(PyFile_AsFile(f))
except IOError: pass


cdef np.ndarray[f32_t, ndim=1] gauss_window(int n):
    cdef int i
    cdef float sigma = 0.4, c = (n-1) / 2.0
    cdef np.ndarray[dtype=f32_t, ndim=1] window = np.zeros(n, dtype=f32)
    for i in xrange(n):
        window[i] = expf(-0.5 * powf((i - c) / (sigma * c), 2.0))
    return window


cdef inline float cubic_interpolate(float y0, float y1, float y2, float y3,
        float x):
   cdef float a, b, c, d, xx, xxx

   a = y0 / -6.0 + y1 / 2.0 - y2 / 2.0 + y3 / 6.0
   b = y0 - 5.0 * y1 / 2.0 + 2.0 * y2 - y3 / 2.0
   c = -11.0 * y0 / 6.0 + 3.0 * y1 - 3.0 * y2 / 2.0 + y3 / 3.0
   d = y0
   xx = x * x
   xxx = xx * x

   return a * xxx + b * xx + c * x + d


cdef class Spectrum(object):
    # most numbers for this class were precomputed and just plugged in. this
    # makes the whole thing entirely unmaintainable. we might or might not
    # change this in the future. for now it really doesn't matter as the job is
    # done and the class does what it's supposed to do

    identifier = blaconst.VISUALIZATION_SPECTRUM
    property height:
        def __get__(self): return 154

    # variables needed to calculate the spectrum
    cdef object __adapter
    cdef int __bands
    cdef fftwf_plan __plan
    cdef np.ndarray __window
    cdef float *__in, *__buf, *__old, *__log_freq
    cdef fftwf_complex *__out

    # variables needed for drawing
    cdef int __width, __bin_width
    cdef float __padding, __margin
    cdef object __color_text
    cdef object __color_highlight
    cdef object __color_bg
    cdef object __gradient

    def __cinit__(self):
        self.__in = NULL
        self.__out = NULL
        self.__buf = NULL
        self.__old = NULL
        self.__log_freq = NULL

    def __init__(self):
        # basically we want a 65 dB dynamic range to cover the entire height.
        # we draw seven levels so we choose a height which is divisible by it,
        # i.e. 154 / 7 = 22. now we add a margin of 5 dB to the top and bottom
        # which corresponds to 11 px
        self.__padding = self.height / 7.0
        self.__margin = self.__padding / 2

        # get window and scale it such that it doesn't change the signal power
        self.__window = gauss_window(NFFT)
        self.__window *= 0.5 * powf(NFFT / np.sum(self.__window ** 2), 0.5)

        cdef int i
        self.__adapter = gst.Adapter()
        self.__buf = <float*> fftwf_malloc(NFFT * 2 * sizeof(float))
        for i in xrange(NFFT * 2): self.__buf[i] = 0.0

        # create fftw plan and allocate data. we use FFTW_EXHAUSTIVE to squeeze
        # every last bit of performance out of this module. beware though, on
        # slow systems this might cause a delay of several seconds the first
        # time blaplay is launched
        self.__in = <float*> fftwf_malloc(NFFT * sizeof(float))
        self.__out = <fftwf_complex*> fftwf_malloc((NFFT/2 + 1) *
                sizeof(fftwf_complex))
        self.__plan = fftwf_plan_dft_r2c_1d(NFFT, self.__in, self.__out,
                FFTW_EXHAUSTIVE)
        with open(blaconst.WISDOM_PATH, "w") as f:
            lib.fftwf_export_wisdom_to_file(PyFile_AsFile(f))

    def __dealloc__(self):
        if self.__in != NULL: fftwf_free(self.__in)
        if self.__out != NULL: fftwf_free(self.__out)
        if self.__buf != NULL: fftwf_free(self.__buf)
        if self.__log_freq != NULL: fftwf_free(self.__log_freq)
        if self.__plan != NULL: fftwf_destroy_plan(self.__plan)
        self.__in = NULL
        self.__out = NULL
        self.__buf = NULL
        self.__log_freq = NULL
        self.__plan = NULL

    def set_colors(self, *args):
        self.__color_text, self.__color_highlight, self.__color_bg = args
        self.__gradient = cairo.LinearGradient(
                0, 0, 0, self.height - self.__padding)
        self.__gradient.add_color_stop_rgb(
                0.5,
                self.__color_highlight.red / 65535.,
                self.__color_highlight.green / 65535.,
                self.__color_highlight.blue / 65535.
        )
        self.__gradient.add_color_stop_rgb(
                1.0,
                self.__color_text.red / 65535.,
                self.__color_text.green / 65535.,
                self.__color_text.blue / 65535.
        )

    @cython.cdivision(True)
    @cython.boundscheck(False)
    cpdef set_width(self, int width):
        self.__width = width
        # to draw all bins with a minimum width of 1 px and 1 px in between
        # each bin we need a width of 2 * bands - 1. from that width we need to
        # subtract the left margin (4 px) and some precomputed margin for the
        # labels on the right. solve this for bands and make sure we don't get
        # a negative number of bands (when the drawing area isn't realized yet
        # for instance) and we get the number of bands we transform to later
        self.__bands = <int> fmaxf(
                0, fminf((self.__width - 34) / 2, BANDS_MAX))

        cdef int i
        cdef float *f
        if self.__old != NULL: fftwf_free(self.__old)
        self.__old = <float*> fftwf_malloc(self.__bands * sizeof(float))
        f = self.__old
        for i in xrange(self.__bands): f[i] = -65.0

        # calculate frequencies on a logarithmic scale
        if self.__log_freq != NULL: fftwf_free(self.__log_freq)
        self.__log_freq = <float*> fftwf_malloc((self.__bands + 1) *
                    sizeof(float))
        f = self.__log_freq

        cdef float step
        f[0] = 50.0
        step = powf(2.0, logf(FS / 2 / f[0]) / logf(2) / self.__bands)
        for i in xrange(1, self.__bands+1): f[i] = f[i-1] * step
        self.__bin_width = <int> fmaxf((self.__width - 4 - (self.__bands-1)) /
                (<float> self.__bands), 1)

    @cython.boundscheck(False)
    cpdef new_buffer(self, object buf):
        self.__adapter.push(buf)
        # when the main window is hidden the draw method isn't called which
        # means buffers are never flushed. therefore we make sure here that we
        # never store more than 500 ms worth of buffers (two channels, four
        # bytes per sample, 22050 samples every 500 ms: 44100 * 4 bytes)
        cdef int l = self.__adapter.available() - 44100 * 4
        if l > 0: self.__adapter.flush(l)

    @cython.boundscheck(False)
    cpdef flush_buffers(self):
        self.__adapter.flush(self.__adapter.available())

    @cython.cdivision(True)
    @cython.boundscheck(False)
    cpdef draw(self, object cr, object pc):
        # attribute look-ups on the instance make the following loops
        # cripplingly slow. therefore we just assign everything to local
        # variables
        cdef int i, l
        cdef int bands = self.__bands
        cdef float *buf = self.__buf, *in_ = self.__in, *old_ = self.__old
        cdef float *_buf
        cdef fftwf_complex *out_ = self.__out
        cdef float *window = <float*> self.__window.data
        cdef float *log_freq = self.__log_freq
        cdef float offset = OFFSET

        cdef np.ndarray[f32_t, ndim=1] np_buf
        if self.__adapter.available() > 0:
            np_buf = np.frombuffer(self.__adapter.take_buffer(
                    min(self.__adapter.available(), 2 * 4 * 1260)), dtype=f32)
        else: np_buf = np.zeros(NFFT * 2, f32)

        _buf = <float*> np_buf.data
        l = min(len(np_buf), NFFT * 2)
        for i in xrange(l, NFFT * 2): buf[i-l] = buf[i]
        for i in xrange(l): buf[NFFT * 2-l+i] = _buf[i]

        # take the channel mean and calculate the forward transform
        for i in xrange(NFFT): in_[i] = window[i] * (buf[2*i] + buf[2*i+1])
        fftwf_execute(self.__plan)

        # fftw3 only returns the NFFT/2 + 1 non-redundant frequency
        # coefficients of the spectrum since the input signal is real (i.e. the
        # spectrum is line symmetric). to account for this we need to double
        # every coefficient except for the DC and Nyquist coefficients when
        # computing the energy. to avoid allocating memory in each call we just
        # reuse the input array of the FFT to store the energy coefficients.
        # note that energy gets transformed into power later when we subtract
        # 20 * log10(NFFT) from the log-energy
        l = NFFT/2 + 1
        in_[0] = out_[0][0] * out_[0][0] + out_[0][1] * out_[0][1]
        in_[l-1] = out_[l-1][0] * out_[l-1][0] + out_[l-1][1] * out_[l-1][1]
        for i in xrange(1, l-1):
            in_[i] = 4 * (out_[i][0] * out_[i][0] + out_[i][1] * out_[i][1])

        # this is a slightly modified method from audacity to interpolate and
        # sum frequency bins which correspond to a certain frequency range
        cdef float bin0, bin1, bin_width, binmid, value
        cdef float resolution = <float> NFFT / FS
        cdef int ibin
        for i in xrange(bands):
            bin0 = log_freq[i] * resolution
            bin1 = log_freq[i+1] * resolution
            bin_width = bin1 - bin0
            value = 0.0

            if bin_width < 1.0:
                binmid = (bin0 + bin1) / 2.0
                ibin = <int> binmid - 1
                if ibin < 1:
                    ibin = 1
                if ibin >= l - 3:
                    ibin = l - 4
                value = cubic_interpolate(in_[ibin], in_[ibin+1], in_[ibin+2],
                        in_[ibin+3], binmid - ibin)
            else:
                if bin1 > bin0:
                    value += in_[<int> bin0] * ((<int> bin0) + 1 - bin0)
                bin0 = <int> bin0 + 1
                while bin0 < <int> bin1:
                    value += in_[<int> bin0]
                    bin0 += 1.0
                value += in_[<int> bin1] * (bin1 - <int> bin1)
                value /= bin_width

            # store the value to draw in the real part of our output array
            value = fminf(fmaxf(10 * (log10f(value + eps) - offset), -65.0), 0)
            out_[i][0] = (value + old_[i]) / 2.0
            old_[i] = value

        # draw the background
        cr.set_source_color(self.__color_bg)
        cr.rectangle(0, 0, self.__width, self.height)
        cr.fill()

        # setting the line width to 0.1 effectively reduces the opacity of the
        # line since we can't draw anything thinner than 1 px anyway
        cr.set_line_width(0.1)
        cr.set_source_color(self.__color_text)

        # draw the levels
        layout = pango.Layout(pc)
        fdesc = gtk.widget_get_default_style().font_desc
        fdesc.set_size(6582)
        layout.set_font_description(fdesc)

        cdef int right_margin = 31
        cdef float x, y
        cdef float m = self.__margin, p = self.__padding, w = self.__width
        move_to = cr.move_to
        line_to = cr.line_to
        stroke = cr.stroke
        for i in xrange(7):
            y = m + floorf(i * p) + 0.5

            # draw the label (0 dB takes up less space than -10 dB etc., hence
            # the distinction between i == 0 and every other case)
            cr.move_to(w - (21 if i == 0 else 29), y - 8)
            layout.set_text("%d dB" % (i * (-10)))
            cr.show_layout(layout)

            # draw horizontal level indicator
            move_to(4, y)
            line_to(w - right_margin, y)
            stroke()

        # draw the frequency bins
        bin_width = self.__bin_width
        cr.set_source(self.__gradient)
        x = 7 * p - m
        rectangle = cr.rectangle
        for i in xrange(bands):
            value = floorf(x * out_[i][0] / 65.0)
            rectangle(4 + i * (bin_width + 1), m - value, bin_width,
                    x + value)
        cr.fill()

