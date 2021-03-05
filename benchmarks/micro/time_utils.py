# Copyright 2014-2021 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Compatibility layer for Python 2 which exposes time.perf_counter and time.process_time under Python
2.

This also allows us to utilize time.process_time() counter under Python 2 on CI which results in
more accurate and less noisy data.
"""

from __future__ import absolute_import

import functools
import ctypes
import ctypes.util
import platform
import errno


clockid_t = ctypes.c_int
time_t = ctypes.c_long

# clock ID to be used in the time.process_time
CLOCK_PROCESS_CPUTIME_ID = 2

# clock ID to be used in the time.perf_counter
CLOCK_MONOTONIC_RAW = 4

rt_lib = ctypes.CDLL(ctypes.util.find_library("rt"), use_errno=True)  # type: ignore

# get the "clock_gettime" function. See here: https://linux.die.net/man/3/clock_gettime
_clock_gettime = rt_lib.clock_gettime  # type: ignore


class timespec(ctypes.Structure):
    _fields_ = [
        ("tv_sec", time_t),  # seconds
        ("tv_nsec", ctypes.c_long),  # nanoseconds
    ]


_clock_gettime.argtypes = [clockid_t, ctypes.POINTER(timespec)]


def clock_gettime_wrapper(clk_id):
    result_time_spec = timespec()
    if _clock_gettime(clk_id, ctypes.byref(result_time_spec)) < 0:

        error_code = ctypes.get_errno()
        message = errno.errorcode[error_code]

        # raise error in case of unsupported clock
        if error_code == errno.EINVAL:
            message = (
                " The clock ID is not supported on this system"
                " clk_id={0}r".format(clk_id)
            )
        raise OSError(error_code, message)

    return result_time_spec.tv_sec + result_time_spec.tv_nsec * 1e-9


try:
    from time import process_time, perf_counter
except ImportError:  # Python < 3.3
    if platform.system() == "Darwin":
        import time

        process_time = time.time
        perf_counter = time.time
    else:
        process_time = functools.partial(
            clock_gettime_wrapper, CLOCK_PROCESS_CPUTIME_ID
        )
        perf_counter = functools.partial(clock_gettime_wrapper, CLOCK_MONOTONIC_RAW)

        process_time.__name__ = "process_time"  # type: ignore
        perf_counter.__name__ = "perf_counter"  # type: ignore
