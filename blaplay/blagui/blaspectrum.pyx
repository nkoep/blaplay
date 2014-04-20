# blaplay, Copyright (C) 2012-2014  Niklas Koep

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
#       - http://docs.cython.org/src/userguide/parallelism.html

cimport cython
cimport numpy as np

import ctypes
import ctypes.util

import gtk
import gst
import cairo
import pango
import numpy as np

from blaplay.blacore import blaconst
from blaplay import blautil

cdef extern from "math.h":
    float fmaxf(float, float)
    float fminf(float, float)
    float logf(float)
    float log10f(float)
    float expf(float)
    float cosf(float)
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
    fftwf_plan fftwf_plan_dft_r2c_1d(
        size_t size, float *in_, fftwf_complex *out_, unsigned flags)
    void fftwf_execute(fftwf_plan plan)

cdef enum:
    FFTW_EXHAUSTIVE = 1 << 3

f32 = np.float32
ctypedef np.float32_t f32_t

cdef int BANDS_MAX = 195, NFFT = 4096, FS = 44100
cdef float eps = np.finfo(f32).eps, OFFSET = 2 * log10f(NFFT)

# Getting stored wisdom seems easier using ctypes than Cython.
soname = ctypes.util.find_library("fftw3f")
if soname is None:
    raise ImportError("Failed to locate the single-precision library of FFTW3")
lib = ctypes.CDLL(soname)

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
except IOError:
    # Cython doesn't cope well with a modified __builtins__, so we have to call
    # any messaging functions by manually looking them up in the module's dict.
    __builtins__.__dict__["print_i"](
        "Optimizing FFT routines. This may take a moment...")


cdef np.ndarray[f32_t, ndim=1] get_window(int n):
    # Hamming window
    cdef int i
    cdef np.ndarray[dtype=f32_t, ndim=1] window = np.zeros(n, dtype=f32)
    for i in range(n):
        window[i] = 0.54 - 0.46 * cosf(2 * np.pi * i / (n - 1))
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


cdef class BlaSpectrum(object):
    # Most numbers for this class were precomputed and just plugged in. This
    # makes the whole thing entirely unmaintainable. We should go over this
    # again some time.

    property height:
        def __get__(self):
            return 154

    # Variables needed to calculate the spectrum
    cdef object __lock
    cdef object __adapter
    cdef int __bands
    cdef fftwf_plan __plan
    cdef np.ndarray __window
    cdef np.ndarray __np_buf
    cdef float *__in
    cdef float *__buf
    cdef float *__old
    cdef float *__log_freq
    cdef fftwf_complex *__out

    # Variables needed for drawing
    cdef int __width, __bin_width
    cdef float __padding, __margin
    cdef object __color_text
    cdef object __color_bg

    def __cinit__(self):
        self.__in = NULL
        self.__out = NULL
        self.__buf = NULL
        self.__old = NULL
        self.__log_freq = NULL

    def __init__(self):
        self.__lock = blautil.BlaLock(strict=True)

        # Basically we want a 65 dB dynamic range to cover the entire height.
        # We draw seven levels so we choose a height which is divisible by it,
        # i.e. 154 / 7 = 22. now we add a margin of 5 dB to the top and bottom
        # which corresponds to 11 px.
        self.__padding = self.height / 7.0
        self.__margin = self.__padding / 2

        # Get window and scale it such that it doesn't change the signal power.
        self.__window = get_window(NFFT)
        self.__window *= 0.5 * powf(NFFT / np.sum(self.__window ** 2), 0.5)

        self.__np_buf = np.zeros(2 * NFFT, f32)

        cdef int i
        self.__adapter = gst.Adapter()
        self.__buf = <float *>fftwf_malloc(2 * NFFT * sizeof(float))
        for i in range(2 * NFFT):
            self.__buf[i] = 0.0

        # Create FFTW plan and allocate data. We use FFTW_EXHAUSTIVE to squeeze
        # every last bit of performance out of this module. Beware though, on
        # slow systems this might cause a delay of several seconds the first
        # time blaplay is launched.
        self.__in = <float *>fftwf_malloc(NFFT * sizeof(float))
        self.__out = <fftwf_complex *>fftwf_malloc(
            (NFFT / 2 + 1) * sizeof(fftwf_complex))
        # FIXME: Creating the exhaustive plan needs to be moved somewhere else
        #        as it freezes up the GUI when it's already shown when the
        #        plugin is first selected.
        self.__plan = fftwf_plan_dft_r2c_1d(
            NFFT, self.__in, self.__out, FFTW_EXHAUSTIVE)
        with open(blaconst.WISDOM_PATH, "w") as f:
            lib.fftwf_export_wisdom_to_file(PyFile_AsFile(f))

    def __dealloc__(self):
        if self.__in != NULL:
            fftwf_free(self.__in)
        if self.__out != NULL:
            fftwf_free(self.__out)
        if self.__buf != NULL:
            fftwf_free(self.__buf)
        if self.__log_freq != NULL:
            fftwf_free(self.__log_freq)
        if self.__plan != NULL:
            fftwf_destroy_plan(self.__plan)
        self.__in = NULL
        self.__out = NULL
        self.__buf = NULL
        self.__log_freq = NULL
        self.__plan = NULL

    def update_colors(self, style):
        self.__color_text = style.text[gtk.STATE_NORMAL]
        self.__color_bg = style.bg[gtk.STATE_NORMAL]

    @cython.cdivision(True)
    @cython.boundscheck(False)
    cpdef set_width(self, int width):
        self.__width = width
        # To draw all bins with a minimum width of 1 px and 1 px in between
        # each bin we need a width of 2 * bands - 1. From that width we need to
        # subtract the left margin (4 px) and some precomputed margin for the
        # labels on the right. Solve this for bands and make sure we don't get
        # a negative number of bands (when the drawing area isn't realized yet
        # for instance) and we get the number of bands we transform to later.
        self.__bands = <int>fmaxf(
            0, fminf((self.__width - 34) / 2, BANDS_MAX))

        cdef int i
        cdef float *f
        if self.__old != NULL:
            fftwf_free(self.__old)
        self.__old = <float *>fftwf_malloc(self.__bands * sizeof(float))
        f = self.__old
        for i in range(self.__bands):
            f[i] = -65.0

        # Calculate frequencies on a logarithmic scale
        if self.__log_freq != NULL:
            fftwf_free(self.__log_freq)
        self.__log_freq = <float *>fftwf_malloc(
            (self.__bands + 1) * sizeof(float))
        f = self.__log_freq

        cdef float step
        f[0] = 50.0
        step = powf(2.0, logf(FS / 2 / f[0]) / logf(2) / self.__bands)
        for i in range(1, self.__bands + 1):
            f[i] = f[i-1] * step
        self.__bin_width = <int>fmaxf(
            (self.__width - 4 - (self.__bands-1)) / (<float>self.__bands), 1)

    @cython.boundscheck(False)
    cpdef new_buffer(self, object buf):
        cdef int l
        # Buffers are added and consumed in different threads so we need to
        # protect modifications of the GstAdapter as it's not thread-safe.
        with self.__lock:
            self.__adapter.push(buf)

    @cython.boundscheck(False)
    cpdef consume_buffer(self):
        # TODO: Account for jitter in this method. It is used as callback for a
        #       gobject.timeout_add call. This means that if the main thread is
        #       too busy it'll fall behind in calling this method. As a result,
        #       we'll accumulate more and more buffers over time.

        with self.__lock:
            if self.__adapter.available() > 0:
                # 44100 / 35 = 1260
                self.__np_buf = np.frombuffer(
                    self.__adapter.take_buffer(
                        min(self.__adapter.available(), 1260 * 2 * 4)),
                    dtype=f32)
            else:
                self.__np_buf = np.zeros(2 * NFFT, f32)
        return True

    @cython.boundscheck(False)
    cpdef flush_buffers(self):
        with self.__lock:
            self.__adapter.flush(self.__adapter.available())

    @cython.cdivision(True)
    @cython.boundscheck(False)
    cpdef draw(self, object cr, object pc):
        # Attribute look-ups in "hot" loops below make the following section
        # very slow. To remedy this we just assign everything to locals.
        cdef int i, l
        cdef int bands = self.__bands
        cdef float *buf = self.__buf
        cdef float *in_ = self.__in
        cdef float *old_ = self.__old
        cdef float *_buf
        cdef fftwf_complex *out_ = self.__out
        cdef float *window = <float *>self.__window.data
        cdef float *log_freq = self.__log_freq
        cdef float offset = OFFSET

        with self.__lock:
            _buf = <float *>self.__np_buf.data
        l = min(len(self.__np_buf), 2 * NFFT)
        for i in range(l, 2 * NFFT):
            buf[i-l] = buf[i]
        for i in range(l):
            buf[2 * NFFT - l + i] = _buf[i]

        # Take the channel mean and calculate the forward transform.
        for i in range(NFFT):
            in_[i] = window[i] * (buf[2 * i] + buf[2 * i + 1])
        fftwf_execute(self.__plan)

        # FFTW3 only returns the NFFT / 2 + 1 non-redundant frequency
        # coefficients of the spectrum since the input signal is real (i.e. the
        # spectrum is line symmetric). To account for this, we need to double
        # every coefficient except for the DC and Nyquist coefficients when
        # computing the energy. To avoid allocating memory in each call, we
        # just reuse the input array of the FFT to store the energy
        # coefficients. Note that energy gets transformed into power later when
        # we subtract 20 * log10(NFFT) from the log-energy.
        l = NFFT / 2 + 1
        in_[0] = out_[0][0] * out_[0][0] + out_[0][1] * out_[0][1]
        in_[l-1] = out_[l-1][0] * out_[l-1][0] + out_[l-1][1] * out_[l-1][1]
        for i in range(1, l-1):
            in_[i] = 4 * (out_[i][0] * out_[i][0] + out_[i][1] * out_[i][1])

        # This is a slightly modified method from audacity to interpolate and
        # sum frequency bins which correspond to a certain frequency range.
        cdef float bin0, bin1, bin_width, binmid, value
        cdef float resolution = <float>NFFT / FS
        cdef int ibin
        for i in range(bands):
            bin0 = log_freq[i] * resolution
            bin1 = log_freq[i+1] * resolution
            bin_width = bin1 - bin0
            value = 0.0

            # For low frequencies we need to interpolate as we have too few
            # frequency coefficients.
            if bin_width < 1.0:
                binmid = (bin0 + bin1) / 2.0
                ibin = <int>binmid - 1
                if ibin < 1:
                    ibin = 1
                if ibin >= l - 3:
                    ibin = l - 4
                value = cubic_interpolate(in_[ibin], in_[ibin+1], in_[ibin+2],
                                          in_[ibin+3], binmid - ibin)
            else:
                if bin1 > bin0:
                    value += in_[<int>bin0] * ((<int>bin0) + 1 - bin0)
                bin0 = <int>bin0 + 1

                while bin0 < <int>bin1:
                    value += in_[<int>bin0]
                    bin0 += 1.0
                value += in_[<int>bin1] * (bin1 - <int>bin1)
                value /= bin_width

            # Store the value to draw in the real part of our output array.
            value = fminf(fmaxf(10 * (log10f(value + eps) - offset), -65.0), 0)
            out_[i][0] = (value + old_[i]) / 2.0
            old_[i] = value

        # Draw the background.
        cr.set_source_color(self.__color_bg)
        cr.rectangle(0, 0, self.__width, self.height)
        cr.fill()

        # Setting the line width to 0.1 effectively reduces the opacity of the
        # line since we can't draw anything thinner than 1 px anyway.
        cr.set_line_width(0.1)
        cr.set_source_color(self.__color_text)

        # Draw the levels.
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
        for i in range(7):
            y = m + floorf(i * p) + 0.5

            # Draw the label: 0 dB takes up less space than -10 dB etc., hence
            # the distinction between i == 0 and every other case.
            # move_to(w - (21 if i == 0 else 29), y - 8)
            # layout.set_text("%d dB" % (i * (-10)))
            # cr.show_layout(layout)

            # Draw horizontal level indicator.
            move_to(4, y)
            line_to(w - 4, y)
            stroke()

        # Draw the frequency bins.
        bin_width = self.__bin_width
        cr.set_source_color(self.__color_text)
        x = 7 * p - m
        rectangle = cr.rectangle
        for i in range(bands):
            value = floorf(x * out_[i][0] / 65.0)
            rectangle(4 + i * (bin_width + 1), m - value, bin_width,
                      x + value)
        cr.fill()

