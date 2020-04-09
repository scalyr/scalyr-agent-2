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
# limitations under the License.

from __future__ import absolute_import
from __future__ import print_function
import abc
import datetime
import json
import re
import time

import six

from scalyr_agent import compat
from tests.utils.agent_runner import AgentRunner
from tests.smoke_tests.request import ScalyrRequest
from six.moves import range

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
    """
    Build regex pattern for 'agent.log' log lines.
    """
    base_pattern = _AGENT_LOG_LINE_BASE_PATTERN.format(
        timestamp, level, logger_name, file_name
    )
    if message:
        pattern_str = "{0}{1}".format(base_pattern, message)
    else:
        pattern_str = base_pattern
    pattern = re.compile(pattern_str)

    return pattern


@six.add_metaclass(abc.ABCMeta)
class AgentVerifier(object):
    """
    Base abstraction for agent log files verification.
    """

    RETRY_DELAY = 5

    def __init__(
        self, runner, server_address
    ):  # type: (AgentRunner, six.text_type) ->None
        self._runner = runner
        self._server_address = server_address
        self._agent_host_name = compat.os_environ_unicode["AGENT_HOST_NAME"]
        self._start_time = time.time()

        self._request = ScalyrRequest(
            server_address=self._server_address,
            read_api_key=compat.os_environ_unicode["READ_API_KEY"],
            max_count=5000,
            start_time=self._start_time,
        )

    def prepare(self):
        """
        Optional method, it can be overridden in subclass and called before verification.
        """
        pass

    @abc.abstractmethod
    def _verify(self):
        """
        This method must be overridden in subclass and it must contain the actual verification logic.
        """
        pass

    def verify(self, timeout=3 * 60):
        # type: (int) -> bool
        """"
        :param timeout: How to long to wait (in seconds) before timing out if no successful response is found.
        """
        self.prepare()

        retry_delay = type(self).RETRY_DELAY

        start_time = time.time()
        timeout_time = start_time + timeout

        while True:
            print("========================================================")
            if self._verify():
                print("Success.")
                return True

            if time.time() >= timeout_time:
                raise ValueError(
                    "Received no successful response in %s seconds. Timeout reached"
                    % (timeout)
                )

            print(("Retry in {0} sec.".format(retry_delay)))
            print("========================================================")
            time.sleep(retry_delay)


class AgentLogVerifier(AgentVerifier):
    """
    The verifier for the 'agent.log' file.
    """

    def __init__(self, runner, server_address):
        super(AgentLogVerifier, self).__init__(runner, server_address)
        self.agent_log_file_path = runner.agent_log_file_path

        self._request.add_filter("$serverHost=='{0}'".format(self._agent_host_name))
        self._request.add_filter(
            "$logfile=='{0}'".format(
                self._runner.get_file_path_text(self.agent_log_file_path)
            )
        )

    def _verify(self):
        local_agent_log_data = self._runner.read_file_content(
            self._runner.agent_log_file_path
        )

        if not local_agent_log_data:
            print(("No data from '{0}'.".format(self._runner.agent_log_file_path)))
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
            print(
                (
                    "Not all collectors were found. Expected '{0}', got '{1}'.".format(
                        5, len(found_collectors)
                    )
                )
            )
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
            print(
                (
                    "Not all remote collectors were found. Expected '{0}', got '{1}'.".format(
                        5, len(found_collectors_remote)
                    )
                )
            )
            return

        return True


class DataJsonVerifier(AgentVerifier):
    """
    Simple verifier that writes 1000 lines into the 'data.json' log file
    and then waits those lines from the Scalyr server.
    """

    def __init__(self, runner, server_address):
        super(DataJsonVerifier, self).__init__(runner, server_address)

        self._data_json_log_path = self._runner.add_log_file(
            self._runner.agent_logs_dir_path / "data.log"
        )
        self._timestamp = datetime.datetime.now().isoformat()

        self._request.add_filter("$serverHost=='{0}'".format(self._agent_host_name))
        self._request.add_filter(
            "$logfile=='{0}'".format(
                self._runner.get_file_path_text(self._data_json_log_path)
            )
        )
        self._request.add_filter("$stream_id=='{0}'".format(self._timestamp))

    def prepare(self):
        print(("Write test data to log file '{0}'".format(self._data_json_log_path)))
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

        matches = response["matches"]
        if len(matches) != 1000:
            print("Not all log lines were found.")
            return

        matches = [json.loads(m["message"]) for m in matches]

        if not all([m["stream_id"] == self._timestamp for m in matches]):
            print("Some of the fetched lines have wrong 'stream_id'")
            return

        # response matches must contain count values from 0 to 999
        if set(m["count"] for m in matches) != set(range(1000)):
            return

        return True


class SystemMetricsVerifier(AgentVerifier):
    """
    Verifier that checks that linux_system_metrics.log file was uploaded to the Scalyr server.
    """

    def __init__(self, runner, server_address):
        super(SystemMetricsVerifier, self).__init__(runner, server_address)

        self._system_metrics_log_path = self._runner.add_log_file(
            self._runner.agent_logs_dir_path / "linux_system_metrics.log"
        )

        self._request.add_filter("$serverHost=='{0}'".format(self._agent_host_name))
        self._request.add_filter(
            "$logfile=='{0}'".format(
                self._runner.get_file_path_text(self._system_metrics_log_path)
            )
        )

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
    """
    Verifier that checks that linux_process_metrics.log file was uploaded to the Scalyr server.
    """

    def __init__(self, runner, server_address):
        super(ProcessMetricsVerifier, self).__init__(runner, server_address)

        self._process_metrics_log_path = self._runner.add_log_file(
            self._runner.agent_logs_dir_path / "linux_process_metrics.log"
        )

        self._request.add_filter("$serverHost=='{0}'".format(self._agent_host_name))
        self._request.add_filter(
            "$logfile=='{0}'".format(
                self._runner.get_file_path_text(self._process_metrics_log_path)
            )
        )

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
