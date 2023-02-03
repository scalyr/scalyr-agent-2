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

TODO: Also exercise the following scenarios / code paths:

* Different syslog messages
* Log watcher management, file creation, expiration, locking
"""

import os
import tempfile
import logging

import mock
import pytest
from faker import Faker

# Suppress very noisy faker debug logging
logging.getLogger('faker').setLevel(logging.ERROR)

from scalyr_agent.builtin_monitors.syslog_monitor import SyslogHandler
from scalyr_agent.json_lib import JsonObject

MOCK_MESSAGE =  "<34>Oct 11 22:14:15 mymachine su: \'su root\' failed for lonvick on /dev/pts/8"

# NOTE: We use faker + same static seed to ensure the result is fully repetable / deterministic
FAKER = Faker()
Faker.seed(1000)

class MockConfig(object):
    def __init__(self, values):
        self._values = values

    def get(self, key):
        try:
            return self._values[key]
        except KeyError:
            return None

class MockGlobalConfig(object):
    def __init__(self):
        self.log_configs = []

TEMP_DIRECTORY = tempfile.gettempdir()

MOCK_EXTRAS = []

for i in range(0, 1000):
    extra = {
        "proto": FAKER.random_element(["tcp", "udp"]),
        "srcip": "127.0.0." + str(FAKER.random_int(0, 250)),
        "destport": str(FAKER.random_int(10000, 60000))
    }
    MOCK_EXTRAS.append(extra)


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

    with tempfile.TemporaryDirectory() as tmp_directory:
        mock_global_config = MockGlobalConfig()
        mock_global_config.log_configs = [
            {
                "path": os.path.join(tmp_directory, "test-*-*.txt"),
                "attributes": JsonObject({"parser": "foobar"}),
            }
        ]

        handler = SyslogHandler(logger=mock_logger, line_reporter=mock_line_reporter, config=mock_config,
                                global_config=mock_global_config, server_host="localhost",
                                log_path=tmp_directory, get_log_watcher=mock.Mock(),
                                rotate_options=(2, 200000), docker_options=mock.Mock())
        handler._SyslogHandler__get_log_watcher.return_value = mock.Mock(), mock.Mock()

        assert len(os.listdir(tmp_directory)) == 0

        def run_benchmark():
            extra = FAKER.random_element(MOCK_EXTRAS)
            handler.handle(MOCK_MESSAGE, extra=extra)

        benchmark.pedantic(run_benchmark, iterations=200, rounds=100)

        # Verify that files which match message template notation have been created
        file_names = os.listdir(tmp_directory)

        if message_template:
            assert len(file_names) >= 100
            for file_name in file_names:
                assert (file_name.startswith("test-tcp-") or file_name.startswith("test-udp-"))
        else:
            assert len(file_names) == 0
