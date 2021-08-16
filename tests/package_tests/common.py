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
import datetime
import re
import selectors
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
    The reader for the file-like objects (for now, just for pipes), which uses the 'selectors' module to poll the
    pip and to read from it in a non-blocking fashion.
    """
    def __init__(self, pipe: IO):
        """
        :param pipe: file_like object to read from.
        """
        self._pipe = pipe

        # create a selector which will poll the pipe.
        self._selector = selectors.DefaultSelector()

        # register the needed events, for us, it's just all read events.
        self._selector.register(pipe, selectors.EVENT_READ)

        # Buffer with the part of the incomplete line which is remaining from a previous line read.
        self._remaining_data = b""

    def next_line(self, timeout: int):
        """
        Read the next line from the pipe or block until there is enough data.
        :param timeout: Time in seconds to wait until the timeout error is raised.
        """
        timeout_time = datetime.datetime.now() + datetime.timedelta(seconds=timeout)

        # polling the pipe until there is a complete line, or throw a timeout error.
        while True:
            time_until_timeout = timeout_time - datetime.datetime.now()
            if time_until_timeout.seconds <= 0:
                raise TimeoutError("Can not read line. Time out.")

            # look for the first line.
            first_new_line_index = self._remaining_data.find(b"\n")

            # There are no new lines, keep polling the pipe for new data.
            if first_new_line_index == -1:

                events = self._selector.select(
                    timeout=time_until_timeout.seconds
                )

                # Add newly read data.
                for _, _ in events:
                    self._remaining_data = b"".join([self._remaining_data, self._pipe.read()])

                continue

            # Get the first line.
            line = self._remaining_data[:first_new_line_index + 1]

            # Update the remaining data.
            self._remaining_data = self._remaining_data[first_new_line_index+1:]

            return line.decode()

    def close(self):
        self._selector.close()















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


def assert_and_throw_if_line_an_error(line: str):
    """
    Check if the agent log line is error.
    """
    if re.match(rf"{AGENT_LOG_LINE_TIMESTAMP} ERROR .*", line):
        raise TestFail(f'The next line message is an error:\n"{line}"')

