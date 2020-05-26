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

from pprint import pprint

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

    def verify(self, timeout=2 * 60):
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
                end_time = time.time()
                print("Success.")
                print("Duration: %s" % (int(end_time - start_time)))
                return True

            if time.time() >= timeout_time:
                # If we reach a timeout, also print agent status output since this may help us with
                # troubleshooting a failure / timeout
                try:
                    status = json.loads(self._runner.status_json())
                except Exception:
                    status = None
                else:
                    print("Agent status:")
                    pprint(status)

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

    def verify(self, timeout=2 * 60):
        # Give agent some time to start up before checking for version string.
        # This version check is done against a local agent.log file and status -v --format=json
        # output and not Scalyr API so we don't need to retry it and wait for logs to be shipped to
        # Scalyr API.
        time.sleep(2)
        self._verify_agent_version_string()

        # Now call the parent verify method which calls _verify()
        return super(AgentLogVerifier, self).verify(timeout=timeout)

    def _verify_agent_version_string(self):
        """
        Check that the local agent.log file and status output contains the correct version string.

        This method is different from main _verify() method in a sense that we only run it once and
        don't retry it since this data should be immediately available so there is no need to retry
        and wait on the Scalyr API since we query the local file and not the Scalyr API.
        """
        local_agent_log_data = self._runner.read_file_content(
            self._runner.agent_log_file_path
        )

        if not local_agent_log_data:
            raise ValueError(
                ("No data in '{0}' file.".format(self._runner.agent_log_file_path))
            )

        print("Check start line contains correct version and revision string")
        match = re.search(
            r"Starting scalyr agent... \(version=(.*?)\) \(revision=(.*?)\)",
            local_agent_log_data,
        )

        if not match:
            raise ValueError(
                "Unable to retrieve package version and revision from agent.log file"
            )

        expected_package_version, expected_package_revision = match.groups()

        status = json.loads(self._runner.status_json())

        actual_package_version = status["version"]
        actual_package_revision = status["revision"]

        # NOTE: Ideally we would also pass in expected version and revision to make this more robust
        # and correct
        if expected_package_version != actual_package_version:
            raise ValueError(
                "Expected package version %s, got %s"
                % (expected_package_version, actual_package_version)
            )

        if expected_package_revision != actual_package_revision:
            raise ValueError(
                "Expected package revision %s, got %s"
                % (expected_package_revision, actual_package_revision)
            )

        print("Correct agent version and revision string found.")

    def _verify(self):
        """
        Verify that the agent has successfuly started.

        Right now we do that by ensuring has produced 5 "spawned collector" log messages which have
        also been shipped to the Scalyr API.
        """
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
                    "Not all collectors were found. Expected '{0}', got '{1}'. Found collectors: {2}".format(
                        5, len(found_collectors), ", ".join(found_collectors)
                    )
                )
            )
            print("Data received: %s" % (local_agent_log_data))
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
                    "Not all remote collectors were found. Expected '{0}', got '{1}'. Found collectors: {2}".format(
                        5,
                        len(found_collectors_remote),
                        ", ".join(found_collectors_remote),
                    )
                )
            )
            print("Data received: %s" % (response_log))
            return

        print("Local agent logs and Scalyr API returned correct data.")
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

        self._lines_count = 100  # TODO: change back to 1000

    def prepare(self):
        print(("Write test data to log file '{0}'".format(self._data_json_log_path)))
        for i in range(self._lines_count):
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
        if len(matches) < self._lines_count:
            print(
                "Less than all log lines were found (found %s, expected %s)."
                % (len(matches), self._lines_count)
            )
            return
        if len(matches) > self._lines_count:
            print(
                "Too many log lines were found (found %s, expected %s)."
                % (len(matches), self._lines_count)
            )
            return

        matches = [json.loads(m["message"]) for m in matches]

        if not all([m["stream_id"] == self._timestamp for m in matches]):
            print("Some of the fetched lines have wrong 'stream_id'")
            return

        # response matches must contain count values from 0 to self._lines_count
        if set(m["count"] for m in matches) != set(range(self._lines_count)):
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
