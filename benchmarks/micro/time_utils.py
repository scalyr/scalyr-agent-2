# Based on https://gist.github.com/zed/5073409

"""
Compatibility layer for Python 2 which exposes time.perf_counter and time.process_time under Python
2.

This also allows us to utilize time.process_time() counter under Python 2 on CI which results in
more accurate and less noisy data.
"""

from __future__ import absolute_import

import ctypes
import errno
import platform
from ctypes.util import find_library
from functools import partial

CLOCK_PROCESS_CPUTIME_ID = 2  # time.h
CLOCK_MONOTONIC_RAW = 4

clockid_t = ctypes.c_int
time_t = ctypes.c_long


class timespec(ctypes.Structure):
    _fields_ = [
        ("tv_sec", time_t),  # seconds
        ("tv_nsec", ctypes.c_long),  # nanoseconds
    ]


_clock_gettime = ctypes.CDLL(find_library("rt"), use_errno=True).clock_gettime  # type: ignore
_clock_gettime.argtypes = [clockid_t, ctypes.POINTER(timespec)]


def clock_gettime(clk_id):
    tp = timespec()
    if _clock_gettime(clk_id, ctypes.byref(tp)) < 0:
        err = ctypes.get_errno()
        msg = errno.errorcode[err]
        if err == errno.EINVAL:
            msg += (
                " The clk_id specified is not supported on this system" " clk_id=%r"
            ) % (clk_id,)
        raise OSError(err, msg)
    return tp.tv_sec + tp.tv_nsec * 1e-9


try:
    from time import perf_counter, process_time
except ImportError:  # Python <3.3
    if platform.system() == "Darwin":
        import time

        perf_counter = time.time
        process_time = time.time
    else:
        perf_counter = partial(clock_gettime, CLOCK_MONOTONIC_RAW)
        perf_counter.__name__ = "perf_counter"  # type: ignore
        process_time = partial(clock_gettime, CLOCK_PROCESS_CPUTIME_ID)
        process_time.__name__ = "process_time"  # type: ignore
