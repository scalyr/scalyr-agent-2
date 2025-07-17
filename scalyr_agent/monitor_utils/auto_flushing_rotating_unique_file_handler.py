# Copyright 2025 Scalyr Inc.
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

from scalyr_agent.scalyr_logging import AutoFlushingRotatingFileHandler

from logging import StreamHandler
import os
import os.path
import re
import threading


class AutoFlushingRotatingUniqueFileHandler(AutoFlushingRotatingFileHandler):
    """
    Automatic flushing, rotating file handler with unique file names

    File rotation is done such that each file name is unique and not reopened;
    this is unlike (AutoFlushing)RotatingFileHandler which renames the current file and reopens it.

    Ie for AutoFlushingRotatingFileHandler: paloalto.log, paloalto.log.0, ..., paloalto.log.n
    with log entries always being written to paloalto.log

    For AutoFlushingRotatingUniqueFileHandler: paloalto.log.0, paloalto.log.1, ..., paloalto.log.n
    with log entries written to paloalto.log.0 then paloalto.log.1, ..., then paloalto.log.n and then back to paloalto.log.0

    Use of this class is needed on Windows platforms because inodes are unavailable to identify file rotations.
    TODO Ideally the implementation of LogFileIterator would be modified to handle this transparently
         However this is not trivial due to the coupling with the checkpointing mechanism

    Example Scalyr agent config:
        {
            // ...
            monitors: [
                {
                    module: "scalyr_agent.builtin_monitors.syslog_monitor",
                    // ...
                    message_log: "paloalto.log",
                    max_log_size: 524288000, // 500 Mib
                    max_log_rotations: 5,
                    unique_file_log_rotation: true
                }
            ]
        }
    """

    def __init__(self, filename, mode="a", maxBytes=0, backupCount=0, delay=0, flushDelay=0):
        StreamHandler.__init__(self)

        self._max_bytes = maxBytes
        self._backup_count = backupCount
        self._flush_delay = flushDelay

        self._file_path = os.path.abspath(filename)

        if self._backup_count <= 0 or self._max_bytes <= 0:
            self._current_file = open(self._file_path, "a")

        else:
            # There may be existing files due to an agent restart, if so, start overwriting the oldest file
            existing_paths = []
            dirname = os.path.dirname(self._file_path)
            for entry in os.listdir(dirname):
                path = os.path.join(dirname, entry)
                if os.path.isfile(path):
                    match = re.match(re.escape(self._file_path) + r'\.(\d+)$', path)
                    if match:
                        existing_paths += [(path, os.path.getmtime(path), int(match.groups()[-1]))]
            existing_paths.sort(key=lambda x: x[1])

            self._current_postfix = existing_paths[0][2] if existing_paths else 0
            self._current_file = open(self._file_path + "." + str(self._current_postfix), "w")

        self._current_size = 0

        self._lock = threading.Lock()
        self._timer = None

    def flush(self):
        if self._flush_delay <= 0:
            self._flush()

        else:
            self._lock.acquire()
            try:
                if self._timer is not None:
                    self._timer = threading.Timer(self._flush_delay, self._flush)
                    self._timer.start()
            finally:
                self._lock.release()

    def _flush(self):
        self._current_file.flush()

        if self._flush_delay > 0:
            self._lock.acquire()
            try:
                if self._timer is not None:
                    self._timer.cancel()
                    self._timer = None
            finally:
                self._lock.release()

    def close(self):
        if self._flush_delay > 0:
            self._lock.acquire()
            try:
                if self._timer is not None:
                    self._timer.cancel()
                    self._timer = None
            finally:
                self._lock.release()

        self._current_file.close()

    def emit(self, record):
        size = len(self.format(record) + os.linesep)

        self._lock.acquire()
        try:
            if self._backup_count > 0 and self._max_bytes > 0:
                if self._current_size + size > self._max_bytes:
                    self._current_postfix = (self._current_postfix + 1) % self._backup_count
                    self._current_file.close()
                    self._current_file = open(self._file_path + "." + str(self._current_postfix), "w")
                    self._current_size = 0

            # NB The newline is automatically converted according to the platform
            self._current_file.write(self.format(record) + "\n")
            self.flush()
            self._current_size += size
        finally:
            self._lock.release()

    def doRollover(self):
        pass
