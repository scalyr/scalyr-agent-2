from __future__ import absolute_import
from __future__ import unicode_literals
from __future__ import print_function

from typing import Optional
import os
import datetime
import time
import json
import re

import six
import pytest

from scalyr_agent.tests.smoke_tests.tools.agent_runner import AgentRunner
from scalyr_agent.tests.smoke_tests.tools.request import ScalyrRequest, RequestSender

TIMESTAMP_PATTERN = r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}.\d+Z"
LEVEL_PATTERN = r"INFO|WARNING|ERROR|DEBUG"
LOGGER_NAME_PATTERN = r"[^\]]*"
FILE_NAME_PATTERN = r"[^\]:]*"

BASE_LINE_PATTERN = r"\s*(?P<timestamp>{})\s+(?P<level>{})\s+\[(?P<logger>{})\]\s+\[(?P<file>{}):\d+\]\s+"


def make_agent_log_line_pattern(
        timestamp=TIMESTAMP_PATTERN,
        level=LEVEL_PATTERN,
        logger_name=LOGGER_NAME_PATTERN,
        file_name=FILE_NAME_PATTERN,
        message=None
):
    base_pattern = BASE_LINE_PATTERN.format(
        timestamp,
        level,
        logger_name,
        file_name,
    )
    if message:
        pattern_str = "{}{}".format(base_pattern, message)
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
    TIME_LIMIT = 300
    RETRY_DELAY = 5

    def __init__(self, runner, request_sender):  # type: (AgentRunner, RequestSender) ->None
        self._runner = runner
        self._request_sender = request_sender

    def prepare(self):
        pass

    def _verify(self):
        pass

    def verify(self):
        if type(self).TYPE == ITERATIVE:
            start_time = time.time()
            while True:
                if self._verify():
                    return True
                if time.time() - start_time >= type(self).TIME_LIMIT:
                    raise IOError("Verifier - '{}' reached timeout.".format(type(self).NAME))
                time.sleep(type(self).RETRY_DELAY)
        else:
            return self._verify()


class AgentLogVerifier(AgentVerifier):
    NAME = "Agent.log"
    DESCRIPTION = "Verify 'agent.log' file."

    def __init__(self, runner, request_sender):
        super(AgentLogVerifier, self).__init__(runner, request_sender)
        self.agent_log_file_path = runner.agent_log_file_path
        self._start_time = time.time()
        self._agent_host_name = os.environ["AGENT_HOST_NAME"]

        # create request to fetch agent.log file data.
        request = ScalyrRequest(
            read_api_key=os.environ["READ_API_KEY"],
            max_count=5000,
            start_time=self._start_time
        )

        request.add_filter("$serverHost=='{}'".format(self._agent_host_name))
        request.add_filter(
            "$logfile=='{}'".format(
                self._runner.get_file_path_text(self.agent_log_file_path)
            )
        )
        self._request = request

    def _verify(self):
        local_agent_log_data = self._runner.read_file_content(self._runner.agent_log_file_path)

        if not local_agent_log_data:
            return

        collector_line_pattern_str = make_agent_log_line_pattern(
            level="INFO",
            logger_name=r"monitor:linux_system_metrics\(\)",
            message=r"spawned\s+(?P<collector>[^\.]+)\.py\s+\(pid=\d+\)",
        )

        collector_line_pattern = re.compile(collector_line_pattern_str)

        found_collectors = set([m.group("collector") for m in collector_line_pattern.finditer(local_agent_log_data)])

        if len(found_collectors) != 5:
            return

        response_data = self._request_sender.send_request(self._request)
        response_log = "\n".join([msg["message"] for msg in response_data["matches"]])

        found_collectors_remote = set([m.group("collector") for m in collector_line_pattern.finditer(response_log)])

        if len(found_collectors_remote) != 5:
            return

        return True


class DataJsonVerifier(AgentVerifier):
    def __init__(self, runner, request_sender):
        super(DataJsonVerifier, self).__init__(runner, request_sender)

        self._data_json_log_path = self._runner.add_log_file(self._runner.agent_logs_dir_path / "data.log")
        self._timestamp = datetime.datetime.now().isoformat()
        self._start_time = time.time()
        self._agent_host_name = os.environ["AGENT_HOST_NAME"]

        request = ScalyrRequest(
            read_api_key=os.environ["READ_API_KEY"],
            max_count=5000,
            start_time=self._start_time
        )

        request.add_filter("$serverHost=='{}'".format(self._agent_host_name))
        request.add_filter(
            "$logfile=='{}'".format(
                self._runner.get_file_path_text(self._data_json_log_path)
            )
        )
        request.add_filter("$stream_id=='{}'".format(self._timestamp))

        self._request = request

    def prepare(self):
        for i in range(1000):
            json_data = json.dumps({
                "count": i, "stream_id": self._timestamp
            })
            self._runner.write_line(
                self._data_json_log_path,
                json_data
            )
        return

    def _verify(self):
        response = self._request_sender.send_request(self._request)

        if len(response["matches"]) != 1000:
            return

        return True


@pytest.mark.usefixtures("agent_environment")
def test_uploaded_data(agent_settings):
    runner = AgentRunner()

    request_sender = RequestSender(
        server_address=agent_settings["SCALYR_SERVER"],
    )

    agent_log_verifier = AgentLogVerifier(runner, request_sender)
    data_json_verifier = DataJsonVerifier(runner, request_sender)

    runner.start()

    assert agent_log_verifier.verify(), "Verification of the file: 'agent.log' failed"

    data_json_verifier.prepare()
    assert data_json_verifier.verify(), "Verification of the file: 'data.json' failed"

    runner.stop()
