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

import queue
import threading
import re
from typing import IO

AGENT_LOG_LINE_TIMESTAMP = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+Z"

# The pattern to match the periodic message lines with network request statistics. This message is written only when
# all startup messages are written, so it's a good time to stop the verification of the agent.log file.
AGENT_LOG_REQESTS_STATS_LINE_PATTERN = rf"{AGENT_LOG_LINE_TIMESTAMP} INFO \[core] \[scalyr-agent-2:\d+] " \
                                       r"agent_requests requests_sent=(?P<requests_sent>\d+) " \
                                       r"requests_failed=(?P<requests_failed>\d+) " \
                                       r"bytes_sent=(?P<bytes_sent>\d+) " \
                                       r".+"

# 5 min.
COMMON_TIMEOUT = 5 * 60

class TestFail(Exception):
    pass


class PipeReader:
    """
    Simple reader to read process pipes. Since it's not possible to perform a non-blocking read from pipe,
    we just read it in a separate thread and put it to the queue.
    """
    def __init__(self, pipe: IO):
        self._pipe = pipe
        self._queue = queue.Queue()
        self._started = False
        self._thread = None

    def read_pipe(self):
        """
        Reads lines from pipe. Runs in a separate thread.
        """
        while True:
            line = self._pipe.readline()
            if line == b'':
                break
            self._queue.put(line.decode())

    def next_line(self, timeout: int):
        """
        Return lines from queue if presented.
        """
        if not self._thread:
            self._thread = threading.Thread(target=self.read_pipe)
            self._thread.start()
        return self._queue.get(timeout=timeout)


def check_agent_log_request_stats_in_line(line: str) -> bool:
    # Match for the requests status message.
    m = re.match(AGENT_LOG_REQESTS_STATS_LINE_PATTERN, line)

    if m:
        # The requests status message is found.
        # Also do a final check for a valid request stats.
        md = m.groupdict()
        requests_sent = int(md["requests_sent"])
        bytes_sent = int(md["bytes_sent"])
        if bytes_sent <= 0 and requests_sent <= 0:
            raise TestFail(
                "Agent log says that during the run the agent has sent zero bytes or requests."
            )
        return True
    else:
        return False


def check_if_line_an_error(line: str):
    """
    Check if the agent log line is error.
    """
    if re.match(rf"{AGENT_LOG_LINE_TIMESTAMP} ERROR .*", line):
        raise TestFail(f'The next line message is an error:\n"{line}"')

