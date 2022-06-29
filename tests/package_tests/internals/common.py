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

import pathlib as pl
import datetime
import enum
import io
import re
import logging
import time
from typing import Callable, List, Union, Tuple, Optional


# Regex pattern for the timestamp of the agent.log file.
# Example: 2021-08-18 23:25:41.825Z INFO [core] [scalyr-agent-2:1732] ...
AGENT_LOG_LINE_TIMESTAMP = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+Z"

# Root of the source code.
SOURCE_ROOT = pl.Path(__file__).parent.parent.parent.parent


class TestFail(Exception):
    pass


class LogVerifierCheckResult(enum.Enum):
    """
    Enum class which represents a result of the check process which is performed by the 'LogVerifierCheck' class.
    """

    SUCCESS = 0
    FAIL = 1
    RETRY = 2


class LogVerifierCheck:
    """
    Abstraction which represents a small test ot check which is performed by the 'LogVerifier' class.
    """

    DESCRIPTION = None

    @property
    def description(self):
        return type(self).DESCRIPTION

    def perform(
        self, new_text, whole_log_text
    ) -> Union[LogVerifierCheckResult, Tuple[LogVerifierCheckResult, str]]:
        """
        Perform test or check of the line. The check may be performed against new data of the whole data of the
        log file.
        :param new_text: new text that that has been added from the previous check.
        :param whole_log_text: the whole text of the log file.
        """
        pass


class LogVerifier:
    """
    Abstraction to test the content of the log file. It performs set of smaller tests or "checks" which are represented
        by the 'LogVerifierCheck' class. If at least one check fails, then the verifier fails too.
    """

    def __init__(self):

        # List of all instances of the 'LogVerifierCheck' class. The verification process will succeed only if all
        # check instances from this list also succeed.
        self._checks_required_to_pass: List[LogVerifierCheck] = []

        # List with all check instances.
        self._all_checks = []

        self._content = ""

        # Function which returns new content from the agent log.
        # If the whole content of the log file is not available from the beginning (for example, the log file is read
        # from the pipe), then this function can be used to fetch a new log data.
        self._get_new_content: Optional[Callable] = None

        # Since we can read log files from sources like pipes, there is a chance that the last line is incomplete,
        # so it is stored in this variable until new data is read and the line is complete.
        self._remaining_data: bytes = b""

    def set_new_content_getter(self, get_new_data_fn: Callable[[], bytes]):
        """
        Set callable object which wll be responsible for getting new content of the log file.
        :param get_new_data_fn: Callable without arguments which returns new data from the log file.
        """
        self._get_new_content = get_new_data_fn

    def add_line_check(self, check: LogVerifierCheck, required_to_pass=False):
        """
        Add new instance of the 'LogVerifierCheck' class, to perform some check during the run of the
        'LogVerifier.verify' function. A new check has to pass or the whole verification will fail.
        :param check: New instance of the check class.
        :param required_to_pass: If True and a new check is failed, then the whole verification process is failed too.
        """

        if required_to_pass:
            self._checks_required_to_pass.append(check)
        self._all_checks.append(check)

    def verify(self, timeout: int, retry_delay: int = 10):
        """
        The main function where all checks are done.
        :param timeout: Time in seconds until the timeout error is raised.
        :param retry_delay: Interval between reties in seconds.
        """
        timeout_time = datetime.datetime.now() + datetime.timedelta(seconds=timeout)

        while True:
            # Protect this function from hanging by adding timeout.
            if datetime.datetime.now() >= timeout_time:
                descriptions = "\n\t -".join(
                    [check.description for check in self._checks_required_to_pass]
                )
                raise TimeoutError(
                    f"Timeout of {timeout} seconds reached. The conditions of the next verifiers have not been met:\n\t{descriptions}.\n"
                    f"Logs accumulated so far:\n\n{self._content}\n"
                    f"Remaining data:\n\n{self._remaining_data}"
                )

            # Get new content of the log file.
            new_data = self._get_new_content()

            # There is no new data, skip and wait.
            if not new_data:
                time.sleep(retry_delay)
                continue

            # There is a new content in the log file. Get only full lines from the new data.

            # Join existing log data with a new.
            self._remaining_data = b"".join([self._remaining_data, new_data])

            # Find the last new line character to separate complete lines from the last incomplete one.
            last_new_line_index = self._remaining_data.rfind(b"\n")

            # There's no any new line, wait until there is enough data for a line.
            if last_new_line_index == -1:
                time.sleep(retry_delay)
                continue

            # There is at least one complete log line.
            # Separate data with only complete lines.
            new_lines_data = self._remaining_data[: last_new_line_index + 1 :]
            # Save last incomplete line.
            self._remaining_data = self._remaining_data[last_new_line_index + 1 :]

            # Decode new lines text.
            new_lines_text = new_lines_data.decode()

            self._content = "".join([self._content, new_lines_text])

            for line_check in list(self._all_checks):
                # apply check to the line and get the result of the check.
                result = line_check.perform(
                    new_text=new_lines_text, whole_log_text=self._content
                )

                # if the result is tuple, then the first element is a result and the second is an additional
                # message.
                if isinstance(result, tuple):
                    result, message = result
                else:
                    message = None

                # The check is successful.
                if result == LogVerifierCheckResult.SUCCESS:
                    # Print result message if presented.
                    if message:
                        logging.info(message)

                    if line_check in self._checks_required_to_pass:
                        # Remove the check instance to prevent further checks since it has been already checked
                        # successfully.
                        self._checks_required_to_pass.remove(line_check)
                        self._all_checks.remove(line_check)

                # The result has been failed. Stop the verifier with error.
                elif result == LogVerifierCheckResult.FAIL:
                    # TODO:  Retry on temporary connection errors or similar, e.g.
                    #  Agent log contains error line : 2021-12-22 12:14:31.879Z ERROR [core] [scalyr_logging.py:621] [error="client/connectionFailed"] Failed to connect to "https://agent.scalyr.com" due to exception.  Exception was "timed out".  Closing connection, will re-attempt :stack_trace:
                    error_message = f"The check '{line_check.description}' has failed."
                    if message:
                        error_message = message

                    error_message = f"{error_message}. Whole log: {self._content}"
                    raise TestFail(error_message)

                # Leave the check for the next iteration to retry it once more.
                elif result == LogVerifierCheckResult.RETRY:
                    if message:
                        logging.info(
                            f"Retry check '{line_check.description}'. Reason: {message}"
                        )
                else:
                    raise ValueError("Unknown Test Check result.")

            # All checks are successful, stop the verification as successful.
            if len(self._checks_required_to_pass) == 0:
                logging.info("All checks have passed.")
                return
            else:
                # There is still at least one unfinished required check. Wait and repeat the verification once more.
                logging.info(
                    f"Not all checks have passed. Retry in {retry_delay} seconds."
                )
                time.sleep(retry_delay)
                continue


# This check class is responsible for finding and validating the agent log message which contains network request
# statistics.
#
# Line example: 2021-08-18 23:25:41.825Z INFO [core] [scalyr-agent-2:1732] agent_requests requests_sent=24 ...
#
class AgentLogRequestStatsLineCheck(LogVerifierCheck):
    DESCRIPTION = "Find and validate the agent log line with request stats. (Starts with 'agent_requests')."

    def perform(
        self, new_text, whole_log_text
    ) -> Union[LogVerifierCheckResult, Tuple[LogVerifierCheckResult, str]]:
        # Match new lines for the requests status message.

        for line in io.StringIO(new_text):
            # The pattern to match the periodic message lines with network request statistics. This message is written only
            # when all startup messages are written, so it's a good time to stop the verification of the agent.log file.
            m = re.match(
                rf"{AGENT_LOG_LINE_TIMESTAMP} INFO \[core] \[(agent_main\.py:\d+|scalyr-agent-2:\d+)] "
                r"agent_requests requests_sent=(?P<requests_sent>\d+) "
                r"requests_failed=(?P<requests_failed>\d+) "
                r"bytes_sent=(?P<bytes_sent>\d+) "
                r".+",
                line,
            )

            if m:
                # The requests status message is found.
                # Also do a final check for a valid request stats.
                md = m.groupdict()
                requests_sent = int(md["requests_sent"])
                bytes_sent = int(md["bytes_sent"])
                if bytes_sent <= 0:
                    return (
                        LogVerifierCheckResult.FAIL,
                        f"Agent log says that during the run the agent has sent zero bytes.\n"
                        f"Whole log content: {whole_log_text}",
                    )
                if requests_sent <= 0:
                    return (
                        LogVerifierCheckResult.FAIL,
                        f"Agent log says that during the run the agent has sent zero requests.\n"
                        f"Whole log content: {whole_log_text}",
                    )

                return (
                    LogVerifierCheckResult.SUCCESS,
                    f"Agent requests stats have been found and they are valid.\n"
                    f"Whole log content: {whole_log_text}",
                )

        else:
            # The matching line hasn't been found yet. Retry.
            return LogVerifierCheckResult.RETRY


class AssertAgentLogLineIsNotAnErrorCheck(LogVerifierCheck):
    DESCRIPTION = "Check if the agent log line is not an error."

    def perform(
        self, new_text, whole_log_text
    ) -> Union[LogVerifierCheckResult, Tuple[LogVerifierCheckResult, str]]:

        new_lines = io.StringIO(new_text).readlines()

        error_line_pattern = re.compile(rf"{AGENT_LOG_LINE_TIMESTAMP} ERROR .*")

        def get_stack_trace_lines():
            """
            Closure that keeps iterating through lines in order to get lines of the expected traceback.
            """
            nonlocal i

            result = []

            i += 1
            while i < len(new_lines):
                _line = new_lines[i]

                # We know that this is a traceback line because it does not start with regular log message preamble.
                if re.match(rf"{AGENT_LOG_LINE_TIMESTAMP} .*", _line):
                    break

                result.append(_line)
                i += 1

            return result

        i = 0

        ignored_errors = []

        while i < len(new_lines):
            line = new_lines[i]
            if error_line_pattern.match(line):

                # There is an issue with dns resolution on GitHub actions side, so we skip some of the error messages.
                connection_error_mgs = '[error="client/connectionFailed"] Failed to connect to "https://agent.scalyr.com" due to errno=-3.'

                to_fail = True
                stack_trace = ""

                if connection_error_mgs in line:
                    stack_trace_lines = get_stack_trace_lines()
                    stack_trace = "".join(stack_trace_lines)

                    # If the traceback that follows after error message contains particular error message,
                    # then we are ok with that.
                    errors_to_ignore = [
                        "socket.gaierror: [Errno -3] Try again",
                        "socket.gaierror: [Errno -3] Temporary failure in name resolution",
                    ]
                    for error_to_ignore in errors_to_ignore:
                        if error_to_ignore in stack_trace:
                            to_fail = False
                            whole_error = "".join([line, stack_trace])
                            ignored_errors.append(whole_error)
                            break

                # For now we ignore those errors since we have different tests for K8s OM
                # Monitors
                if "ERROR [monitor:kubernetes_openmetrics_monitor()]" in line:
                    to_fail = False

                    stack_trace_lines = get_stack_trace_lines()
                    stack_trace = "".join(stack_trace_lines)

                    whole_error = "".join([line, stack_trace])
                    ignored_errors.append(whole_error)

                if to_fail:
                    return (
                        LogVerifierCheckResult.FAIL,
                        f"Agent log contains error line : {line}, traceback: {stack_trace}",
                    )

            i += 1

        message = None
        # Add additional message with ignored errors.
        if ignored_errors:
            message = "The next error lines have been ignored:\n"

            for i, error in enumerate(ignored_errors):
                message = f"{message}{i}:\n{error}\n"

        return LogVerifierCheckResult.SUCCESS, message
