# Copyright 2014-2020 Scalyr Inc.
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
# limitations under the License.K

from __future__ import absolute_import
from __future__ import unicode_literals
from __future__ import print_function

if False:
    from typing import Optional

import datetime
import time
import json
import re
import os

import pytest

from scalyr_agent.__scalyr__ import PACKAGE_INSTALL, DEV_INSTALL
from scalyr_agent import compat

from smoke_tests.tools.agent_runner import AgentRunner
from smoke_tests.tools.request import ScalyrRequest

from six.moves import range
import six

_TIMESTAMP_PATTERN = r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}.\d+Z"
_LEVEL_PATTERN = r"INFO|WARNING|ERROR|DEBUG"
_LOGGER_NAME_PATTERN = r"[^\]]*"
_FILE_NAME_PATTERN = r"[^\]:]*"

_AGENT_LOG_LINE_BASE_PATTERN = r"\s*(?P<timestamp>{0})\s+(?P<level>{1})\s+\[(?P<logger>{2})\]\s+\[(?P<file>{3}):\d+\]\s+"


def _make_agent_log_line_pattern(
        timestamp=_TIMESTAMP_PATTERN,
        level=_LEVEL_PATTERN,
        logger_name=_LOGGER_NAME_PATTERN,
        file_name=_FILE_NAME_PATTERN,
        message=None,
):
    base_pattern = _AGENT_LOG_LINE_BASE_PATTERN.format(timestamp, level, logger_name, file_name)
    if message:
        pattern_str = "{0}{1}".format(base_pattern, message)
    else:
        pattern_str = base_pattern
    pattern = re.compile(pattern_str)

    return pattern


NORMAL = 0
ITERATIVE = 1


class AgentVerifier(object):
    NAME = None  # type: Optional[six.text_type]
    DESCRIPTION = None  # type: Optional[six.text_type]
    TYPE = ITERATIVE
    RETRY_DELAY = 5

    def __init__(
            self, runner, server_address
    ):  # type: (AgentRunner, six.text_type) ->None
        self._runner = runner
        self._server_address = server_address

    def prepare(self):
        pass

    def _verify(self):
        pass

    def verify(self):
        if type(self).TYPE == ITERATIVE:
            retry_delay = type(self).RETRY_DELAY
            while True:
                print("========================================================")
                if self._verify():
                    print("Success.")
                    return True
                print("Retry in {0} sec.".format(retry_delay))
                print("========================================================")
                time.sleep(retry_delay)
        else:
            return self._verify()


class AgentLogVerifier(AgentVerifier):
    NAME = "Agent.log"
    DESCRIPTION = "Verify 'agent.log' file."

    def __init__(self, runner, server_address):
        super(AgentLogVerifier, self).__init__(runner, server_address)
        self.agent_log_file_path = runner.agent_log_file_path
        self._start_time = time.time()
        self._agent_host_name = compat.os_environ_unicode["AGENT_HOST_NAME"]

        # create request to fetch agent.log file data.
        request = ScalyrRequest(
            server_address=self._server_address,
            read_api_key=compat.os_environ_unicode["READ_API_KEY"],
            max_count=5000,
            start_time=self._start_time,
        )

        request.add_filter("$serverHost=='{0}'".format(self._agent_host_name))
        request.add_filter(
            "$logfile=='{0}'".format(
                self._runner.get_file_path_text(self.agent_log_file_path)
            )
        )
        self._request = request

    def _verify(self):
        local_agent_log_data = self._runner.read_file_content(
            self._runner.agent_log_file_path
        )

        if not local_agent_log_data:
            print("No data from '{0}'.".format(self._runner.agent_log_file_path))
            return

        print("Check that all collectors were found.")
        collector_line_pattern_str = _make_agent_log_line_pattern(
            level="INFO",
            logger_name=r"monitor:linux_system_metrics\(\)",
            message=r"spawned\s+(?P<collector>[^\.]+)\.py\s+\(pid=\d+\)",
        )

        collector_line_pattern = re.compile(collector_line_pattern_str)

        found_collectors = set(
            [
                m.group("collector")
                for m in collector_line_pattern.finditer(local_agent_log_data)
            ]
        )

        if len(found_collectors) != 5:
            print("Not all collectors were found. '{0}'".format(len(found_collectors)))
            return

        print("Send query to Scalyr server.")
        try:
            response_data = self._request.send()
        except:
            print("Query failed.")
            return

        print("Query response received.")
        response_log = "\n".join([msg["message"] for msg in response_data["matches"]])

        found_collectors_remote = set(
            [
                m.group("collector")
                for m in collector_line_pattern.finditer(response_log)
            ]
        )
        print("Check that all collectors were found in the log from Scalyr server.")
        if len(found_collectors_remote) != 5:
            print("Not all collectors were found. '{0}'".format(len(found_collectors)))
            return

        return True


class DataJsonVerifier(AgentVerifier):
    def __init__(self, runner, server_address):
        super(DataJsonVerifier, self).__init__(runner, server_address)

        self._data_json_log_path = self._runner.add_log_file(
            self._runner.agent_logs_dir_path / "data.log"
        )
        self._timestamp = datetime.datetime.now().isoformat()
        self._start_time = time.time()
        self._agent_host_name = compat.os_environ_unicode["AGENT_HOST_NAME"]

        request = ScalyrRequest(
            server_address=self._server_address,
            read_api_key=compat.os_environ_unicode["READ_API_KEY"],
            max_count=5000,
            start_time=self._start_time,
        )

        request.add_filter("$serverHost=='{0}'".format(self._agent_host_name))
        request.add_filter(
            "$logfile=='{0}'".format(
                self._runner.get_file_path_text(self._data_json_log_path)
            )
        )
        request.add_filter("$stream_id=='{0}'".format(self._timestamp))

        self._request = request

    def prepare(self):
        print("Write test data to log file '{0}'".format(self._data_json_log_path))
        for i in range(1000):
            json_data = json.dumps({"count": i, "stream_id": self._timestamp})
            self._runner.write_line(self._data_json_log_path, json_data)
        return

    def _verify(self):
        try:
            response = self._request.send()
        except:
            print("Query failed.")
            return

        if len(response["matches"]) != 1000:
            print("Not all log lines were found.")
            return

        return True


class SystemMetricsVerifier(AgentVerifier):
    def __init__(self, runner, server_address):
        super(SystemMetricsVerifier, self).__init__(runner, server_address)

        self._system_metrics_log_path = self._runner.add_log_file(
            self._runner.agent_logs_dir_path / "linux_system_metrics.log"
        )
        self._timestamp = datetime.datetime.now().isoformat()
        self._start_time = time.time()
        self._agent_host_name = compat.os_environ_unicode["AGENT_HOST_NAME"]

        request = ScalyrRequest(
            server_address=self._server_address,
            read_api_key=compat.os_environ_unicode["READ_API_KEY"],
            max_count=5000,
            start_time=self._start_time,
        )

        request.add_filter("$serverHost=='{0}'".format(self._agent_host_name))
        request.add_filter(
            "$logfile=='{0}'".format(
                self._runner.get_file_path_text(self._system_metrics_log_path)
            )
        )
        self._request = request

    def _verify(self):
        try:
            response = self._request.send()
        except:
            print("Query failed.")
            return

        if len(response["matches"]) < 220:
            print("Not enough system metrics were loaded to Scalyr.")
            return

        return True


class ProcessMetricsVerifier(AgentVerifier):
    def __init__(self, runner, server_address):
        super(ProcessMetricsVerifier, self).__init__(runner, server_address)

        self._process_metrics_log_path = self._runner.add_log_file(
            self._runner.agent_logs_dir_path / "linux_process_metrics.log"
        )
        self._timestamp = datetime.datetime.now().isoformat()
        self._start_time = time.time()
        self._agent_host_name = compat.os_environ_unicode["AGENT_HOST_NAME"]

        request = ScalyrRequest(
            server_address=self._server_address,
            read_api_key=compat.os_environ_unicode["READ_API_KEY"],
            max_count=5000,
            start_time=self._start_time,
        )

        request.add_filter("$serverHost=='{0}'".format(self._agent_host_name))
        request.add_filter(
            "$logfile=='{0}'".format(
                self._runner.get_file_path_text(self._process_metrics_log_path)
            )
        )
        self._request = request

    def _verify(self):
        try:
            response = self._request.send()
        except:
            print("Query failed.")
            return

        if len(response["matches"]) < 14:
            print("Not enough process metrics were loaded to Scalyr.")
            return

        return True


@pytest.mark.usefixtures("agent_environment")
@pytest.mark.timeout(300)
def test_standalone_smoke(request):
    """
    Agent standalone test to run within the same machine.
    """
    print("")
    print("Agent host name: {0}".format(os.environ["AGENT_HOST_NAME"]))

    # configure DEV_INSTALL or PACKAGE_INSTALL installation type from command line.
    runner_type = request.config.getoption("--runner-type")
    if runner_type == "PACKAGE":
        installation_type = PACKAGE_INSTALL
    else:
        installation_type = DEV_INSTALL
    runner = AgentRunner(installation_type)

    agent_log_verifier = AgentLogVerifier(runner, os.environ["SCALYR_SERVER"])
    data_json_verifier = DataJsonVerifier(runner, os.environ["SCALYR_SERVER"])
    system_metrics_verifier = SystemMetricsVerifier(runner, os.environ["SCALYR_SERVER"])
    process_metrics_verifier = ProcessMetricsVerifier(runner, os.environ["SCALYR_SERVER"])

    runner.start()
    print("Verify 'agent.log'")
    assert agent_log_verifier.verify(), "Verification of the file: 'agent.log' failed"
    print("Verify 'linux_system_metrics.log'")
    assert system_metrics_verifier.verify(), "Verification of the file: 'linux_system_metrics.log' failed"
    print("Verify 'linux_process_metrics.log'")
    assert process_metrics_verifier.verify(), "Verification of the file: 'linux_process_metrics.log' failed"

    data_json_verifier.prepare()
    assert data_json_verifier.verify(), "Verification of the file: 'data.json' failed"

    runner.stop()
