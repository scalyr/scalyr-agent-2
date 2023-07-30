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
import json
import pathlib as pl
from urllib.parse import quote_plus, urlencode
from typing import Callable, List, Any

import requests

from tests.end_to_end_tests.tools import AgentCommander, TimeoutTracker


logger = logging.getLogger(__name__)


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


def check_agent_log_for_errors(
    content: str, ignore_predicates: List[Callable[[str, List[str]], bool]] = None
):
    """
    Checks content of the agent log for errors.
    :param content: String with content of the log.
    :param ignore_predicates: List of callables where each accepts error message line and following traceback (if exists)
        and returns True whether this message has to be ignored, so the overall check will not fail.
    """

    ignore_predicates = ignore_predicates or []

    def skip_temp_hostname_resolution_error(message, additional_lines):
        if (
            '[error="client/connectionFailed"] Failed to connect to "https://agent.scalyr.com" due to errno=-3.'
            not in message
        ):
            return False
        for additional_line in additional_lines:
            if "socket.gaierror: [Errno -3] Try again" in additional_line:
                return True
            if (
                "socket.gaierror: [Errno -3] Temporary failure in name resolution"
                in additional_line
            ):
                return True

        return False

    ignore_predicates.append(skip_temp_hostname_resolution_error)

    messages = preprocess_agent_log_messages(content=content)
    error_line_pattern = re.compile(rf"{AGENT_LOG_LINE_TIMESTAMP} (ERROR|CRITICAL) .*")
    for message, additional_lines in messages:
        # error is detected, normally fail the test, but also need to check for some particular error
        # that we may want pass.

        whole_error = message + "\n" + "\n".join(additional_lines)
        if error_line_pattern.match(message):

            to_fail = True

            for predicate in ignore_predicates:
                if predicate(message, additional_lines):
                    to_fail = False
                    logger.info(f"Ignored error: {whole_error}")
                    break

            if to_fail:
                logger.info(content)
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

            logger.info("Agent requests stats have been found and they are valid.")
            return True
    else:
        return False


def get_events_page_from_scalyr(
    scalyr_server,
    read_api_key,
    start_time,
    filters,
    timeout_tracker: TimeoutTracker,
    continuation_token: str = None
):
    """
    Query logs from Scalyr servers.
    """
    common_params = {
        "maxCount": 5000,
        "startTime": start_time,
        "token": read_api_key,
    }
    while True:

        params = common_params.copy()

        if continuation_token:
            params["continuationToken"] = continuation_token

        params_str = urlencode(params)

        quoted_filters = [quote_plus(f) for f in filters]
        filter_fragments_str = "+and+".join(quoted_filters)

        query = "{0}&filter={1}".format(params_str, filter_fragments_str)

        protocol = "https://" if not scalyr_server.startswith("http") else ""

        full_query = "{0}{1}/api/query?queryType=log&{2}".format(
            protocol, scalyr_server, query
        )

        logger.info("Query server: {0}".format(full_query))

        with requests.Session() as session:
            resp = session.get(full_query)

        if resp.status_code == 200:
            break

        logger.info(f"Query failed with status '{resp.status_code}' and test '{resp.text}'.")
        logger.info(f"Retry in {_QUERY_RETRY_DELAY} sec.")
        timeout_tracker.sleep(1, "Can not get all events.")

    data = resp.json()

    return data


def get_all_events_from_scalyr(
    scalyr_server,
    read_api_key,
    start_time,
    filters,
    timeout_tracker: TimeoutTracker,
) -> List:
    """
    Query all pages with logs from Scalyr servers.
    """
    events = []
    continuation_token = None
    while True:
        data = get_events_page_from_scalyr(
            scalyr_server=scalyr_server,
            read_api_key=read_api_key,
            start_time=start_time,
            filters=filters,
            timeout_tracker=timeout_tracker,
            continuation_token=continuation_token,
        )

        page_events = data["matches"]
        events.extend(page_events)

        continuation_token = data.get("continuationToken")
        if not continuation_token:
            break

    return events


TEST_LOG_MESSAGE_COUNT = 1000


_QUERY_RETRY_DELAY = 10


def write_counter_messages_to_test_log(
        upload_test_log_path: pl.Path,
        messages_count: int = None,
        logger: logging.Logger = None
):
    """
    Write special counter messages to a test log file. Those messages then will be queried from Scalyr to verify
    that they all were successfully ingested.
    """

    messages_count = messages_count or TEST_LOG_MESSAGE_COUNT
    if logger:
        logger.info(f"Write {messages_count} lines to the file {upload_test_log_path}")
    with upload_test_log_path.open("a") as test_log_write_file:
        for i in range(messages_count):
            data = {"count": i}
            data_json = json.dumps(data)
            test_log_write_file.write(data_json)
            test_log_write_file.write("\n")
            test_log_write_file.flush()

    return messages_count


def verify_logs(
    scalyr_api_read_key: str,
    scalyr_server: str,
    get_agent_log_content: Callable[[], str],
    counters_verification_query_filters: List[str],
    counter_getter: Callable[[Any], int],
    timeout_tracker: TimeoutTracker,
    write_counter_messages: Callable[[], int],
    verify_ssl: bool = True,
    ignore_agent_errors_predicates: List[Callable[[str, List[str]], bool]] = None,
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
    :param timeout_tracker: Instance of the TimeoutTracker.
    :param write_counter_messages: Function that writes counter messages to upload the to Scalyr.
        Can be None, for example for the kubernetes image test, where writer pod is already started.
    :param verify_ssl: Verify that agent connected with ssl enabled.
    :param ignore_agent_errors_predicates: List of callables where each accepts error message line and following traceback
        (if exists) and returns True whether this message has to be ignored, so the overall check will not fail.
    """

    logger.info("Write test log file messages.")
    messages_count = write_counter_messages()

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
        first_check_agent_log_content = first_check_agent_log_content.rsplit(
            os.linesep, 1
        )[0]
    check_agent_log_for_errors(
        content=first_check_agent_log_content,
        ignore_predicates=ignore_agent_errors_predicates,
    )

    logger.info("Wait for agent log requests stats...")

    with timeout_tracker(80, "Can not wait more for requests stats."):
        while not check_requests_stats_in_agent_log(content=get_agent_log_content()):
            logger.info("   Request stats haven't been found yet, retry...")
            timeout_tracker.sleep(10)

    logger.info(
        "Verify that previously written counter messages have been uploaded to server."
    )

    timeout_tracker.sleep(_QUERY_RETRY_DELAY, "Could not fetch data from Scalyr.")
    start_time = time.time() - 60 * 5
    while True:
        events = get_all_events_from_scalyr(
            scalyr_server=scalyr_server,
            read_api_key=scalyr_api_read_key,
            start_time=start_time,
            filters=counters_verification_query_filters,
            timeout_tracker=timeout_tracker,
        )

        if len(events) < messages_count:
            logger.info(
                f"Not all events have been uploaded. "
                f"Expected: {messages_count}. "
                f"Actual: {len(events)}"
            )
            time.sleep(_QUERY_RETRY_DELAY)
            continue

        assert (
            len(events) == messages_count
        ), f"Expected number of events: {messages_count}, got {len(events)}."

        event_counts = [counter_getter(e) for e in events]

        assert event_counts == list(
            range(messages_count)
        ), "Counters in the uploaded event not in the right order."

        logger.info(f"All {messages_count} events have been uploaded.")
        break

    # Do a final error check for agent log.
    # We also replace agent log part from the first check, so it will check only new lines.
    second_check_agent_log_content = get_agent_log_content().replace(
        first_check_agent_log_content, ""
    )
    check_agent_log_for_errors(
        content=second_check_agent_log_content,
        ignore_predicates=ignore_agent_errors_predicates,
    )


def verify_agent_status(
    agent_version: str, agent_commander: AgentCommander, timeout_tracker: TimeoutTracker
):
    """
    Perform basic verification of the agent output.
    """

    logger.info("Verifying agent status output")
    while True:
        json_status = agent_commander.get_status_json()
        copying_manager_status = json_status.get("copying_manager_status")

        if copying_manager_status is None:
            timeout_tracker.sleep(
                1, "Can't wait further for agent's copying_manager_status."
            )
            continue

        last_response_status = copying_manager_status.get("last_response_status")
        if last_response_status is None:
            timeout_tracker.sleep(
                1,
                "Can't wait further for agent's copying manager last_response_status.",
            )
            continue

        assert (
            last_response_status == "success"
        ), f"last_response_status is not successful, status:{last_response_status}"
        break

    string_status = agent_commander.get_status()
    assert "agent.log" in string_status
    if platform.system() == "Linux":
        message = f"Can not find linux system metrics monitor is agent's status. Status: {string_status}"
        assert "linux_system_metrics" in string_status, message
        message = f"Can not find linux process metrics monitor is agent's status. Status: {string_status}"
        assert "linux_process_metrics" in string_status, message

    # Verify json status
    json_status = agent_commander.get_status_json()
    assert agent_version == json_status["version"]