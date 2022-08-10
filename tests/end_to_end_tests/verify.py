# Copyright 2014-2022 Scalyr Inc.
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

import logging
import os
import platform
import re
import time
from urllib.parse import quote_plus, urlencode
from typing import Callable, List, Any

import requests

from tests.end_to_end_tests.tools import AgentCommander


log = logging.getLogger(__name__)


AGENT_LOG_LINE_TIMESTAMP = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+Z"




def preprocess_agent_log_messages(content: str):

    lines = content.splitlines(keepends=True)

    if not lines:
        return []

    # Remove last line if it's incomplete.
    if not lines[-1].endswith(os.linesep):
        lines.pop(-1)

    lines = [line.strip() for line in lines]

    messages = []
    for line in lines:
        line = line.strip()
        if re.match(rf"{AGENT_LOG_LINE_TIMESTAMP} .*", line):
            messages.append((line, []))
        else:
            # If line does not start with agent log preamble, then it has to be a multiline message
            # or error traceback, so we all those additional lines to previous message in additional list.
            messages[-1][1].append(line)

    return messages


def check_agent_log_for_errors(content: str):

    messages = preprocess_agent_log_messages(content=content)
    error_line_pattern = re.compile(rf"{AGENT_LOG_LINE_TIMESTAMP} (ERROR|CRITICAL) .*")
    for message, additional_lines in messages:
        # error is detected, normally fail the test, but also need to check for some particular error
        # that we may want pass.

        whole_error = message + "\n" + "\n".join(additional_lines)
        if error_line_pattern.match(message):

            to_fail = True

            # There is an issue with dns resolution on GitHub actions side, so we skip some error messages.
            connection_error_mgs = '[error="client/connectionFailed"] Failed to connect to "https://agent.scalyr.com" due to errno=-3.'
            if connection_error_mgs in message:
                # If the traceback that follows after error message contains particular error message,
                # then we are ok with that.
                errors_to_ignore = [
                    "socket.gaierror: [Errno -3] Try again",
                    "socket.gaierror: [Errno -3] Temporary failure in name resolution",
                ]
                for error_to_ignore in errors_to_ignore:
                    if error_to_ignore in additional_lines:
                        to_fail = False
                        log.info(f"Ignored error: {whole_error}")
                        break
            elif "get current leader: Temporary error seen while accessing api:" in message:
                errors_to_ignore = [
                    "socket.gaierror: [Errno -3] Try again",
                    "socket.gaierror: [Errno -3] Temporary failure in name resolution",
                ]
                for error_to_ignore in errors_to_ignore:
                    if error_to_ignore in additional_lines:
                        to_fail = False
                        log.info(f"Ignored error: {whole_error}")
                        break

            if to_fail:
                raise AssertionError(f"Agent log error: {whole_error}")


def check_requests_stats_in_agent_log(content: str) -> bool:
    # The pattern to match the periodic message lines with network request statistics.

    messages = preprocess_agent_log_messages(content)
    for line, _ in messages:
        m = re.match(
            rf"{AGENT_LOG_LINE_TIMESTAMP} INFO \[core] \[(scalyr_agent\.agent_main:\d+|scalyr-agent-2:\d+)] "
            r"agent_requests requests_sent=(?P<requests_sent>\d+) "
            r"requests_failed=(?P<requests_failed>\d+) "
            r"bytes_sent=(?P<bytes_sent>\d+) "
            r".+",
            line,
        )

        if m:
            log.info("Requests stats message has been found. Verify that stats...")
            # Also do a final check for a valid request stats.
            md = m.groupdict()
            requests_sent = int(md["requests_sent"])
            bytes_sent = int(md["bytes_sent"])
            assert (
                bytes_sent > 0
            ), "Agent log says that during the run the agent has sent zero bytes."
            assert (
                requests_sent > 0
            ), "Agent log says that during the run the agent has sent zero requests."

            log.info("Agent requests stats have been found and they are valid.")
            return True
    else:
        return False


class ScalyrQueryRequest:
    """
    Abstraction to create scalyr API requests.
    """

    def __init__(
        self,
        server_address,
        read_api_key,
        max_count=1000,
        start_time=None,
        end_time=None,
        filters=None,
        logger=log,
    ):
        self._server_address = server_address
        self._read_api_key = read_api_key
        self._max_count = max_count
        self._start_time = start_time
        self._end_time = end_time
        self._filters = filters or []

        self._logger = logger

    def build(self):
        params = {
            "maxCount": self._max_count,
            "startTime": self._start_time or time.time(),
            "token": self._read_api_key,
        }

        params_str = urlencode(params)

        quoted_filters = [quote_plus(f) for f in self._filters]
        filter_fragments_str = "+and+".join(quoted_filters)

        query = "{0}&filter={1}".format(params_str, filter_fragments_str)

        return query

    def send(self):
        query = self.build()

        protocol = "https://" if not self._server_address.startswith("http") else ""

        full_query = "{0}{1}/api/query?queryType=log&{2}".format(
            protocol, self._server_address, query
        )

        self._logger.info("Query server: {0}".format(full_query))

        with requests.Session() as session:
            resp = session.get(full_query)

        if resp.status_code != 200:
            self._logger.info(f"Query failed with {resp.text}.")
            return None

        data = resp.json()

        return data


TEST_LOG_MESSAGE_COUNT = 1000


_QUERY_RETRY_DELAY = 10


def verify_logs(
    scalyr_api_read_key: str,
    scalyr_server: str,
    get_agent_log_content: Callable[[], str],
    counters_verification_query_filters: List[str],
    counter_getter: Callable[[Any], int],
    write_counter_messages: Callable[[], None] = None,
    verify_ssl: bool = True,
):
    """
    Do a basic verifications on agent log file.
    It also writes test log with counter messages that are queried later from Scalyr servers to compare results.
    :param scalyr_api_read_key: Scalyr API key with read permissions.
    :param scalyr_server: Scalyr server hostname.
    :param get_agent_log_content: Function that has to return current contant of the running agent log.
        That function has to implemented accoring to a type of the running agent, e.g. kubernetes, docker, or package
    :param counters_verification_query_filters:  List of Scalyr query language filters which are required to fetch
        messages that are ingested by the 'write_counter_messages'
    :param counter_getter: Function which should return counter from the ingested message.
    :param write_counter_messages: Function that writes counter messages to upload the to Scalyr.
        Can be None, for example for the kubernetes image test, where writer pod is already started.
    """
    if write_counter_messages:
        log.info("Write test log file messages.")
        write_counter_messages()

    agent_log_content = get_agent_log_content()

    if verify_ssl:
        # Verify agent start up line
        assert "Starting scalyr agent" in agent_log_content
        # Ensure CA validation is not disabled with default install
        assert "sslverifyoff" not in agent_log_content
        assert (
            "Server certificate validation has been disabled" not in agent_log_content
        )

    first_check_agent_log_content = agent_log_content
    if not first_check_agent_log_content.endswith("\n"):
        # Get only complete lines.
        first_check_agent_log_content = first_check_agent_log_content.rsplit(os.linesep, 1)[0]
    check_agent_log_for_errors(content=first_check_agent_log_content)

    log.info("Wait for agent log requests stats.")
    while not check_requests_stats_in_agent_log(content=get_agent_log_content()):
        time.sleep(10)

    log.info(
        "Verify that previously written test log file content has been uploaded to server."
    )
    while True:
        resp = ScalyrQueryRequest(
            server_address=scalyr_server,
            read_api_key=scalyr_api_read_key,
            # We max count more that the actual written counter message to be sure that
            # no more messages were left hidden in the next search page.
            max_count=TEST_LOG_MESSAGE_COUNT + 2,
            start_time=time.time() - 60 * 5,
            filters=counters_verification_query_filters,
        ).send()

        if not resp:
            log.info(f"Retry in {_QUERY_RETRY_DELAY} sec.")
            time.sleep(_QUERY_RETRY_DELAY)
            continue

        events = resp["matches"]

        if not events:
            log.info(
                f"No events have been uploaded yet, retry in {_QUERY_RETRY_DELAY} sec."
            )
            time.sleep(_QUERY_RETRY_DELAY)
            continue

        if len(events) < TEST_LOG_MESSAGE_COUNT:
            log.info(
                f"Not all events have been uploaded. "
                f"Expected: {TEST_LOG_MESSAGE_COUNT}. "
                f"Actual: {len(events)}"
            )
            time.sleep(_QUERY_RETRY_DELAY)
            continue

        assert len(events) == TEST_LOG_MESSAGE_COUNT, (
            f"Number of uploaded event more that "
            f"expected ({TEST_LOG_MESSAGE_COUNT})."
        )

        event_counts = [counter_getter(e) for e in events]

        assert event_counts == list(
            range(TEST_LOG_MESSAGE_COUNT)
        ), "Counters in the uploaded event not in the right order."

        log.info(f"All {TEST_LOG_MESSAGE_COUNT} events have been uploaded.")
        break

    # Do a final error check for agent log.
    # We also replace agent log part from the first check, so it will check only new lines.
    second_check_agent_log_content = get_agent_log_content().replace(first_check_agent_log_content, "")
    check_agent_log_for_errors(content=second_check_agent_log_content)


def verify_agent_status(agent_version: str, agent_commander: AgentCommander):
    """
    Perform basic verification of the agent output.
    """

    log.info("Verifying agent status output")
    # Verify text status
    string_status = agent_commander.get_status()

    assert "agent.log" in string_status
    if platform.system() == "Linux":
        assert "linux_system_metrics" in string_status
        assert "linux_process_metrics" in string_status

    # Verify json status
    json_status = agent_commander.get_status_json()
    assert agent_version == json_status["version"]
