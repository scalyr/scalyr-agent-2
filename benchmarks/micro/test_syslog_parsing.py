# Copyright 2014-2023 Scalyr Inc.
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
Benchmarks which measure how long it takes to parse syslog data in the syslog monitor with
extended parsing (message templates) enabled.
"""

import mock
import pytest

from scalyr_agent.builtin_monitors.syslog_monitor import SyslogHandler

# TODO: Use Fixtures for various different types of syslog messages
MOCK_MESSAGE =  "<34>Oct 11 22:14:15 mymachine su: \'su root\' failed for lonvick on /dev/pts/8"

class MockConfig(object):
    def __init__(self, values):
        self._values = values

    def get(self, key):
        try:
            return self._values[key]
        except KeyError:
            return None

# TODO: Also exercise the following scenarios
# * Different syslog messages
# * Log watcher management, file creation, expiration

@pytest.mark.submit_result_to_codespeed
# fmt: off
@pytest.mark.parametrize(
    "message_template",
    [
        True,
        False,
    ],
    ids=[
        "message_template",
        "no_message_template",
    ],
)
# fmt: on
@pytest.mark.benchmark(group="syslog_monitor")
def test_handle_syslog_logs(benchmark, message_template):
    """
    Right now this micro benchmarks just measures how much overhead parsing message takes, but it
    doesn't really measure how much overhead other things such as logging, managing log watchers,
    etc. add.
    """
    extra = {
        "protoc": "tcp",
        "srcip": "127.0.0.1",
        "destport": 6000
    }

    if message_template:
        message_log_template = "test-$PROTO-$SRCIP.txt"
    else:
        message_log_template = None

    mock_logger = mock.Mock()
    mock_line_reporter = mock.Mock()
    mock_config = MockConfig(
        values={
            "expire_log": 300,
            "check_for_unused_logs_mins": 100,
            "check_for_unused_logs_hours": 10,
            "delete_unused_logs_hours": 10,
            "check_rotated_timestamps": False,
            "max_log_files": 1000,
            "message_log_template": message_log_template,
        }
    )

    handler = SyslogHandler(logger=mock_logger, line_reporter=mock_line_reporter, config=mock_config,
                            server_host="localhost", log_path="/tmp/", get_log_watcher=mock.Mock(),
                            rotate_options=(2, 200000), docker_options=mock.Mock())
    handler._SyslogHandler__get_log_watcher.return_value = mock.Mock(), mock.Mock()

    def run_benchmark():
        handler.handle(MOCK_MESSAGE, extra=extra)

    benchmark.pedantic(run_benchmark, iterations=100, rounds=100)
