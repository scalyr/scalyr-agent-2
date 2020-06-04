# Parts of this code
# Copyright 2001-2014 by Vinay Sajip. All Rights Reserved.
#
# Permission to use, copy, modify, and distribute this software and its
# documentation for any purpose and without fee is hereby granted,
# provided that the above copyright notice appear in all copies and that
# both that copyright notice and this permission notice appear in
# supporting documentation, and that the name of Vinay Sajip
# not be used in advertising or publicity pertaining to distribution
# of the software without specific, written prior permission.
# VINAY SAJIP DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS SOFTWARE, INCLUDING
# ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL
# VINAY SAJIP BE LIABLE FOR ANY SPECIAL, INDIRECT OR CONSEQUENTIAL DAMAGES OR
# ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER
# IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT
# OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

from __future__ import absolute_import

import threading
import os
from io import open

from six.moves import range


class AutoFlushingRotatingFile(object):
    def __init__(self, filename, max_bytes=0, backup_count=0, flush_delay=0):
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._flush_delay = flush_delay

        self._filename = os.path.abspath(filename)
        self._totalSize = 0
        self._open()
        self._lock = threading.Lock()

    def _open(self):
        self._file = open(self._filename, "a")
        self._totalSize = self._file.tell()

    def write(self, message):
        raw_message = message
        message = "%s\n" % message

        # NOTE: When opening file in text only mode, on Windows \n will automatically be converted
        # to \r\n on write, which means that the actual file will be larger if we don't take this
        # into account here
        size = len(raw_message + os.linesep)

        self._lock.acquire()
        try:
            if self.rotateRequired(size):
                self.rotateFile()

            f = self._file
            f.write(message)
            f.flush()
            self._totalSize += size
        finally:
            self._lock.release()

    def flush(self):
        self._flush()

    def _flush(self):
        if self._file:
            self._file.flush()

    def close(self):
        self.flush()
        if self._file:
            self._file.close()
            self._file = None

    def rotateRequired(self, size):
        return self._max_bytes > 0 and self._totalSize + size > self._max_bytes

    def rotateFile(self):
        self.close()

        if self._backup_count > 0:
            for i in range(self._backup_count - 1, 0, -1):
                sfn = "%s.%d" % (self._filename, i)
                dfn = "%s.%d" % (self._filename, i + 1)
                if os.path.exists(sfn):
                    if os.path.exists(dfn):
                        os.remove(dfn)
                    os.rename(sfn, dfn)
            dfn = self._filename + ".1"
            if os.path.exists(dfn):
                os.remove(dfn)
            if os.path.exists(self._filename):
                os.rename(self._filename, dfn)

        self._open()
