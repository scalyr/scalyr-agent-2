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


from __future__ import unicode_literals
from __future__ import absolute_import

import copy
import datetime
import os
import sys
import threading
import time
from abc import ABCMeta, abstractmethod
import multiprocessing.managers

if False:
    from typing import Dict
    from typing import Any
    from typing import List
    from typing import Optional

from scalyr_agent import scalyr_logging as scalyr_logging, StoppableThread
from scalyr_agent.agent_status import CopyingManagerWorkerStatus
from scalyr_agent.log_processing import LogFileProcessor
from scalyr_agent.util import RateLimiter
from scalyr_agent import util as scalyr_util
from scalyr_agent.configuration import Configuration
from scalyr_agent.scalyr_client import create_client, create_new_client
from scalyr_agent.copying_manager.common import write_checkpoint_state_to_file

import six

log = scalyr_logging.getLogger(__name__)


class CopyingParameters(object):
    """Tracks the copying parameters that should be used for sending requests to Scalyr and adjusts them over time
    according to success and failures of requests.

    The copying parameters boil down to two parameters:  the maximum number of bytes that can be sent to Scalyr
    in a request (self.current_bytes_allowed_to_send), and the minimum amount of time to wait between requests
    (self.current_sleep_interval).

    This implements a truncated binary backoff algorithm.
    """

    def __init__(self, configuration):
        """Initialize the parameters based on the thresholds defined in the configuration file.

        @param configuration: The configuration file.
        @type configuration: configuration.Configuration
        """
        # The current maximum number of bytes that can be sent in a single request to Scalyr.
        # This will be adjusted over time.
        self.current_bytes_allowed_to_send = configuration.max_allowed_request_size
        # The current time to sleep between requests to Scalyr.
        # This will be adjusted over time.
        self.current_sleep_interval = configuration.max_request_spacing_interval

        # The maximum value current_bytes_allowed_to_send can take.
        self.__max_allowed_request_size = configuration.max_allowed_request_size
        # The minimum value current_bytes_allowed_to_send can take.
        self.__min_allowed_request_size = configuration.min_allowed_request_size

        # The maximum value current_sleep_interval can take.
        self.__max_request_spacing_interval = configuration.max_request_spacing_interval
        # The minimum value current_sleep_interval can take.
        self.__min_request_spacing_interval = configuration.min_request_spacing_interval

        # The maximum value current_sleep_interval can take when there has been an error.
        self.__max_error_request_spacing_interval = (
            configuration.max_error_request_spacing_interval
        )

        # The low water mark for the number of bytes sent in a request.  If, when we go to collect the lines that
        # need to be sent from all logs, the amount is lower than this, then we will sleep more between requests.
        self.__low_water_bytes_sent = configuration.low_water_bytes_sent
        # The percentage to adjust the sleeping time if the lower_water_bytes_sent mark is not met.
        self.__low_water_request_spacing_adjustment = (
            configuration.low_water_request_spacing_adjustment
        )
        # The high water mark for the number of bytes sent in a request.  If, when we go to collect the lines that
        # need to be sent from all logs, the amount is higher than this, then we will sleep less between requests.
        self.__high_water_bytes_sent = configuration.high_water_bytes_sent
        # The percentage to adjust the sleeping time if the high_water_bytes_sent mark is exceeded.
        self.__high_water_request_spacing_adjustment = (
            configuration.high_water_request_spacing_adjustment
        )

        # The percentage to adjust the sleeping time if the last request was a failure.
        self.__failure_request_spacing_adjustment = (
            configuration.failure_request_spacing_adjustment
        )

        # The percentage to adjust the allowed request size if we get a back a 'requestTooLarge' response from
        # the server.
        self.__request_too_large_adjustment = configuration.request_too_large_adjustment

    def update_params(self, result, bytes_sent):
        """Updates the current_bytes_allowed_to_send and current_sleep_interval based on the result from the last
        request as well as the number of bytes sent.

        @param result: The status field from the response from the server for the last request.
        @param bytes_sent: The number of bytes sent in the last request.
        @type result: str
        @type bytes_sent: int
        """
        # The algorithm is as follows:
        #    For the sleep time:  If it is a success, then we multiple the current sleep time by either the
        #      lower or high water spacing adjustment, depending if we sent fewer than the lower water bytes or
        #      more than the high water bytes.  (If we sent a number between them, then no adjustment is made).
        #      If the request was a failure, we adjust it by the failure request failure adjustment.
        #   For the size, we only adjust the request downwards if we get a 'requestTooLarge' message from the server,
        #      but on success, we put the allowed size back up to the maximum.
        if result == "success":
            max_request_spacing_interval = self.__max_request_spacing_interval
            if bytes_sent < self.__low_water_bytes_sent:
                self.current_sleep_interval *= (
                    self.__low_water_request_spacing_adjustment
                )
            elif bytes_sent > self.__high_water_bytes_sent:
                self.current_sleep_interval *= (
                    self.__high_water_request_spacing_adjustment
                )
        else:
            self.current_sleep_interval *= self.__failure_request_spacing_adjustment
            max_request_spacing_interval = self.__max_error_request_spacing_interval

        if result == "success":
            self.current_bytes_allowed_to_send = self.__max_allowed_request_size
        elif "requestTooLarge" in result:
            self.current_bytes_allowed_to_send = int(
                bytes_sent * self.__request_too_large_adjustment
            )

        self.current_bytes_allowed_to_send = self.__ensure_within(
            self.current_bytes_allowed_to_send,
            self.__min_allowed_request_size,
            self.__max_allowed_request_size,
        )

        self.current_sleep_interval = self.__ensure_within(
            self.current_sleep_interval,
            self.__min_request_spacing_interval,
            max_request_spacing_interval,
        )

    def __ensure_within(self, value, min_value, max_value):
        """Return value subject to the constraints that it must be greater than min_value and less than max_value.

        @param value: The raw value.
        @param min_value: The minimum allowed value.
        @param max_value: The maximum allowed value.

        @type value: float
        @type min_value: float
        @type max_value: float

        @return: The value to use.  If it is between min_value and max_value, then the original value.  Otherwise,
            either min_value or max_value depending on which constraint was violated.
        @rtype: float
        """
        if value < min_value:
            value = min_value
        elif value > max_value:
            value = max_value
        return value


class AddEventsTask(object):
    """Encapsulates the state for a pending AddEventRequest."""

    def __init__(self, add_events_request, completion_callback):
        """Initializes the instance.

        @param add_events_request: The AddEventRequest to send using a ScalyrClientSession
        @param completion_callback:  The completion callback to invoke once the request has been successfully sent.
            It takes a single int argument, which must be one of the three values:  LogFileProcessor.SUCCESS,
            LogFileProcessor.FAIL_AND_RETRY, LogFileProcessor.FAIL_AND_DROP.
        @type add_events_request: scalyr_client.AddEventRequest
        @type completion_callback: function that takes an int argument
        """
        # The pending AddEventsRequest to send.
        self.add_events_request = add_events_request
        # The calllback to invoke once the request has completed.
        self.completion_callback = completion_callback
        # If there is a AddEventsTask object already created for the next request due to pipelining, this is set to it.
        # This must be the next request if this request is successful, otherwise, we will lose bytes.
        self.next_pipelined_task = None


class CopyingManagerWorker(six.with_metaclass(ABCMeta)):
    """
    The interface for the Copying manager worker classes.
    """

    @abstractmethod
    def start_worker(self):
        pass

    @abstractmethod
    def stop_worker(self, wait_on_join=True, join_timeout=5):
        """Stops the worker.

        @param wait_on_join: If True, will block on a join of the thread running the worker.
        @param join_timeout: The maximum number of seconds to block for the join.
        """
        pass

    @abstractmethod
    def generate_status(self, warn_on_rate_limit=False):
        """Generate the status for the copying manager worker to be reported.

        This is used in such features as 'scalyr-agent-2 status -v'.

        Note, this method is thread safe.  It needs to be since another thread will ask this object for its
        status.

        @return:  The status object containing the statistics for the copying manager.
        @rtype: CopyingManagerStatus
        """
        pass

    @abstractmethod
    def wait_for_copying_to_begin(self):
        """
        Block the current thread until worker's instance has begun copying.
        """
        pass

    @abstractmethod
    def create_and_schedule_new_log_processor(self, *args, **kwargs):
        """
        Creates and also schedules a new log processor. It will be added to the main collection only on the next iteration,
        so we don't have to guard the main collection with lock.
        """
        pass

    @abstractmethod
    def augment_user_agent_for_client_session(self, fragments):
        """
        Modifies User-Agent header of the session of the worker.

        @param fragments String fragments to append (in order) to the standard user agent data
        @type fragments: List of six.text_type
        """
        pass

    @abstractmethod
    def get_id(self):
        pass

    @abstractmethod
    def generate_scalyr_client_status(self):
        pass


class CopyingManagerThreadedWorker(StoppableThread, CopyingManagerWorker):
    """
    Abstraction which is responsible for copying the log files to the Scalyr servers.

    This is run as its own thread.
    """

    def __init__(self, configuration, api_key_config_entry, worker_id, is_daemon=False):
        # type: (Configuration, Dict, six.text_type, bool) -> None
        """Initializes the copying manager worker.

        @param configuration: The configuration file containing which log files need to be copied listed in the
            configuration file.
        @param api_key_config_entry:
        @param worker_id: Id of the worker.
        @:param is_daemon: If true, start a worker thread as a daemon thread.

        """
        StoppableThread.__init__(
            self,
            name="copying manager worker thread #%s" % worker_id,
            is_daemon=is_daemon,
        )

        self._id = six.text_type(worker_id)
        self.__config = configuration
        self.__api_key_config_entry = api_key_config_entry

        self._session = None
        self.__new_scalyr_client = None

        # Rate limiter
        self.__rate_limiter = None
        if self.__config.parsed_max_send_rate_enforcement:
            self.__rate_limiter = RateLimiter(
                # Making the bucket size 4 times the bytes per second, it shouldn't affect the rate over a long time
                # meaningfully but we don't have a rationale for this value.
                # TODO: Make this configurable as part of the `max_send_rate_enforcement` configuration option
                self.__config.parsed_max_send_rate_enforcement * 4.0,
                self.__config.parsed_max_send_rate_enforcement,
            )

        # collect monitor-specific extra server-attributes.  seed with a copy of the attributes and converted to a dict.
        self.__expanded_server_attributes = self.__config.server_attributes.to_dict()

        # The dict of LogFileProcessors that are processing the lines from matched log files.
        self.__log_processors = []  # type: List[LogFileProcessor]

        # Temporary collection of recently added log processors.
        # Every log processor which is added during the iteration of the worker is placed in here.
        # All those log processors will be added to the main collection
        # on the beginning of the next iteration.
        # It stores all new log processors before they are added to the main log processors list.
        self.__new_log_processors = []  # type: List[LogFileProcessor]

        # A lock that protects the status variables and the __log_processors variable, the only variables that
        # are access in generate_status() which needs to be thread safe.
        self.__lock = threading.Lock()

        # The current pending AddEventsTask.  We will retry the contained AddEventsRequest serveral times.
        self.__pending_add_events_task = None

        # The next LogFileProcessor that should have log lines read from it for transmission.
        self.__current_processor = 0

        # The client to use for sending the data.  Set in the start_manager call.
        self.__scalyr_client = None  # type: Any
        # The last time we scanned for new files that match the __log_matchers.
        self.__last_new_file_scan_time = 0

        # Status variables that track statistics reported to the status page.
        self.__last_attempt_time = None
        self.__last_success_time = None
        self.__last_attempt_size = None
        self.__last_response = None
        self.__last_response_status = None
        self.__total_bytes_uploaded = 0
        self.__total_errors = 0
        self.__total_rate_limited_time = 0
        self.__rate_limited_time_since_last_status = 0

        # A semaphore that we increment when this object has begun copying files (after first scan).
        self.__copying_semaphore = threading.Semaphore(0)

        # debug leaks
        self.__disable_scan_for_new_bytes = configuration.disable_scan_for_new_bytes

        # Statistics for copying_manager_worker_status messages
        self.total_copy_iterations = 0
        self.total_read_time = 0
        self.total_waiting_time = 0
        self.total_blocking_response_time = 0
        self.total_request_time = 0
        self.total_pipelined_requests = 0

    @property
    def expanded_server_attributes(self):
        """Return deepcopy of expanded server attributes"""
        return copy.deepcopy(self.__expanded_server_attributes)

    def run(self):
        """Processes the log files as requested by the configuration, looking for matching log files, reading their
        bytes, applying redaction and sampling rules, and then sending them to the server.

        This method will not terminate until the thread has been stopped.
        """

        # So the scanning.. every scan:
        #   - Update the file length counts of all current scanners:
        #   - Then pick up where you left off, getting X bytes as determined that abstraction
        #   - Send it to the client
        #   - determine success or not.. if success, update it.
        #   - sleep

        if self.__config.copying_thread_profile_interval > 0:
            import cProfile

            profiler = cProfile.Profile()
            profiler.enable()
            profile_dump_interval = self.__config.copying_thread_profile_interval
        else:
            profiler = None
            profile_dump_interval = 0

        current_time = time.time()

        try:
            # noinspection PyBroadException
            try:
                # The copying params that tell us how much we are allowed to send and how long we have to wait between
                # attempts.
                copying_params = CopyingParameters(self.__config)

                current_time = time.time()

                # Just initialize the last time we had a success to now.  Make the logic below easier.
                # NOTE: We set this variable to current (start time) even if we never successfuly
                # establish a connection because we want eventually drop __pending_add_events_task
                # even if we can't establish a connection. If we didn't do that, that queue could
                # grow unbounded.
                # Because of that, we need to take this behavior into account when updating
                # "__last_success_time" variable which is used for status reporting. We do that by
                # utilizing another last_success_status variable which only gets updated when we
                # successfuly send the request to the server.
                last_success = current_time
                last_success_status = None

                # Force the agent to write a new full checkpoint as soon as it can
                last_full_checkpoint_write = 0.0

                pipeline_byte_threshold = self.__config.pipeline_threshold * float(
                    self.__config.max_allowed_request_size
                )

                log.info(
                    "Copying manager worker #%s started. Pid: '%s'"
                    % (self._id, os.getpid())
                )

                # Create new client for the worker
                self._init_scalyr_client()

                # We are about to start copying.  We can tell waiting threads.
                self.__copying_semaphore.release()
                while self._run_state.is_running():
                    log.log(
                        scalyr_logging.DEBUG_LEVEL_1,
                        "At top of copy log files loop on worker #%s. (Iteration #%s)"
                        % (self._id, self.total_copy_iterations),
                    )
                    current_time = time.time()
                    pipeline_time = 0.0
                    # noinspection PyBroadException
                    try:
                        # If we have a pending request and it's been too taken too long to send it, just drop it
                        # on the ground and advance.
                        if current_time - last_success > self.__config.max_retry_time:
                            if self.__pending_add_events_task is not None:
                                self.__pending_add_events_task.completion_callback(
                                    LogFileProcessor.FAIL_AND_DROP
                                )
                                self.__pending_add_events_task = None
                            # Tell all of the processors to go to the end of the current log file.  We will start
                            # copying
                            # from there.
                            for processor in self.__log_processors:
                                processor.skip_to_end(
                                    "Too long since last successful request to server.",
                                    "skipNoServerSuccess",
                                    current_time=current_time,
                                )

                        self.__add_new_log_processors()

                        # Collect log lines to send if we don't have one already.
                        if self.__pending_add_events_task is None:
                            self.__pending_add_events_task = self.__get_next_add_events_task(
                                copying_params.current_bytes_allowed_to_send
                            )
                        else:
                            log.log(
                                scalyr_logging.DEBUG_LEVEL_1,
                                "Have pending batch of events, retrying to send.",
                            )
                            # Take a look at the file system and see if there are any new bytes pending.  This updates
                            # the statistics for each pending file.  This is important to do for status purposes if we
                            # have not tried to invoke get_next_send_events_task in a while (since that already updates
                            # the statistics).
                            self.__scan_for_new_bytes(current_time=current_time)

                        # Try to send the request if we have one.
                        if self.__pending_add_events_task is not None:
                            log.log(
                                scalyr_logging.DEBUG_LEVEL_1,
                                "Sending an add event request",
                            )
                            # Send the request, but don't block for the response yet.
                            send_request_time_start = time.time()
                            get_response = None
                            if not self.__config.use_new_ingestion:
                                get_response = self._send_events(
                                    self.__pending_add_events_task
                                )

                            # Check to see if pipelining should be disabled
                            # TODO: uncomment this when the pipelining is enabled again.
                            # disable_pipelining = (
                            #     self.__has_pending_log_changes()
                            # )

                            # If we are sending very large requests, we will try to optimize for future requests
                            # by overlapping building the request with waiting for the response on the current request
                            # (pipelining).

                            if (
                                self.__pending_add_events_task.add_events_request.current_size
                                >= pipeline_byte_threshold
                                and self.__pending_add_events_task.next_pipelined_task
                                is None
                                # TODO: pipelining is temporarily disabled and should be enabled back after
                                #  other issues related to the transitioning to the sharded copying manager are solved..
                                # and not disable_pipelining
                            ):

                                # Time how long it takes us to build it because we will subtract it from how long we
                                # have to wait before we send the next request.
                                pipeline_time = time.time()
                                self.total_pipelined_requests += 1
                                self.__pending_add_events_task.next_pipelined_task = self.__get_next_add_events_task(
                                    copying_params.current_bytes_allowed_to_send,
                                    for_pipelining=True,
                                )
                            else:
                                pipeline_time = 0.0

                            # Now block for the response.
                            blocking_response_time_start = time.time()
                            if self.__config.use_new_ingestion:
                                result = "success"
                                bytes_sent = 0
                                full_response = ""
                            else:
                                (result, bytes_sent, full_response) = get_response()
                            blocking_response_time_end = time.time()
                            self.total_blocking_response_time += (
                                blocking_response_time_end
                                - blocking_response_time_start
                            )
                            self.total_request_time += (
                                blocking_response_time_end - send_request_time_start
                            )

                            if pipeline_time > 0:
                                pipeline_time = time.time() - pipeline_time
                            else:
                                pipeline_time = 0.0

                            log.log(
                                scalyr_logging.DEBUG_LEVEL_1,
                                'Sent %ld bytes and received response with status="%s".',
                                bytes_sent,
                                result,
                            )

                            if result != "success":
                                # Log the whole response body in case server returns non-success
                                # response so we can troubleshoot the error (aka is it bug in the
                                # agent code or similar)
                                log.log(
                                    scalyr_logging.DEBUG_LEVEL_5,
                                    'Received server response with status="%s" and body: %s',
                                    result,
                                    full_response,
                                )

                            log_bytes_sent = 0
                            if (
                                result == "success"
                                or "discardBuffer" in result
                                or "requestTooLarge" in result
                            ):
                                next_add_events_task = None
                                try:
                                    if result == "success":
                                        log_bytes_sent = self.__pending_add_events_task.completion_callback(
                                            LogFileProcessor.SUCCESS
                                        )
                                        next_add_events_task = (
                                            self.__pending_add_events_task.next_pipelined_task
                                        )
                                    elif "discardBuffer" in result:
                                        self.__pending_add_events_task.completion_callback(
                                            LogFileProcessor.FAIL_AND_DROP
                                        )
                                    else:
                                        self.__pending_add_events_task.completion_callback(
                                            LogFileProcessor.FAIL_AND_RETRY
                                        )
                                finally:
                                    # No matter what, we want to throw away the current event since the server said we
                                    # could.  We have seen some bugs where we did not throw away the request because
                                    # an exception was thrown during the callback.
                                    self.__pending_add_events_task = (
                                        next_add_events_task
                                    )
                                    self.__write_active_checkpoint_state(current_time)

                            if result == "success":
                                last_success = current_time
                                last_success_status = current_time

                            # Rate limit based on amount of copied log bytes in a successful request
                            if self.__rate_limiter:
                                time_slept = self.__rate_limiter.block_until_charge_succeeds(
                                    log_bytes_sent
                                )
                                self.__total_rate_limited_time += time_slept
                                self.__rate_limited_time_since_last_status += time_slept
                                self.total_waiting_time += time_slept

                        else:
                            result = "failedReadingLogs"
                            bytes_sent = 0
                            full_response = ""

                            log.error("Failed to read logs for copying.  Will re-try")

                        # Update the statistics and our copying parameters.
                        self.__lock.acquire()
                        copying_params.update_params(result, bytes_sent)
                        self.__last_attempt_time = current_time
                        self.__last_success_time = last_success_status
                        self.__last_attempt_size = bytes_sent
                        self.__last_response = six.ensure_text(full_response)
                        self.__last_response_status = result
                        if result == "success":
                            self.__total_bytes_uploaded += bytes_sent
                        self.__lock.release()

                        if profiler is not None:
                            seconds_past_epoch = int(time.time())
                            if seconds_past_epoch % profile_dump_interval == 0:
                                profiler.disable()
                                profiler.dump_stats(
                                    "%s%s%s"
                                    % (
                                        self.__config.copying_thread_profile_output_path,
                                        "copying_worker_",
                                        datetime.datetime.utcnow().strftime(
                                            "%H_%M_%S.out"
                                        ),
                                    )
                                )
                                profiler.enable()
                    except Exception:
                        # TODO: Do not catch Exception here.  That is too broad.  Disabling warning for now.
                        log.exception(
                            "Failed while attempting to scan and transmit logs"
                        )
                        log.log(
                            scalyr_logging.DEBUG_LEVEL_1,
                            "Failed while attempting to scan and transmit logs",
                        )
                        self.__lock.acquire()
                        self.__last_attempt_time = current_time
                        self.__total_errors += 1
                        self.__lock.release()

                    if (
                        current_time - last_full_checkpoint_write
                        > self.__config.full_checkpoint_interval
                    ):
                        self._write_full_checkpoint_state(current_time)
                        last_full_checkpoint_write = current_time

                    if pipeline_time < copying_params.current_sleep_interval:
                        self._sleep_but_awaken_if_stopped(
                            copying_params.current_sleep_interval - pipeline_time
                        )
                        self.total_waiting_time += (
                            copying_params.current_sleep_interval - pipeline_time
                        )

                    # End of the copy loop
                    self.total_copy_iterations += 1
            except Exception:
                # If we got an exception here, it is caused by a bug in the program.
                log.exception("Log copying failed due to exception")
                # if error has occurred earlier than this semaphore is released,
                # than we need to release it to be sure that the copying manager won't stuck in deadlock.
                self.__copying_semaphore.release()

                # stop worker's thread.
                sys.exit(1)
        finally:
            self._write_full_checkpoint_state(current_time)
            for processor in self.__log_processors:
                processor.close()

            if self.__scalyr_client is not None:
                self.__scalyr_client.close()
            if self.__new_scalyr_client is not None:
                self.__new_scalyr_client.close()

            if profiler is not None:
                profiler.disable()

            log.log(
                scalyr_logging.DEBUG_LEVEL_0, "Worker '%s' is finished." % self._id,
            )

    def wait_for_copying_to_begin(self):
        """
        Block the current thread until worker's instance has begun copying.
        """
        self.__copying_semaphore.acquire(True)
        return

    def generate_status(self, warn_on_rate_limit=False):
        # type: (bool) -> CopyingManagerWorkerStatus
        """Generate the status for the copying manager worker to be reported.

        This is used in such features as 'scalyr-agent-2 status -v'.

        Note, this method is thread safe.  It needs to be since another thread will ask this object for its
        status.

        @return:  The status object containing the statistics for the copying manager.
        @rtype: CopyingManagerStatus
        """
        try:
            self.__lock.acquire()

            result = CopyingManagerWorkerStatus()
            result.worker_id = self._id
            result.pid = os.getpid()
            result.total_bytes_uploaded = self.__total_bytes_uploaded
            result.last_success_time = self.__last_success_time
            result.last_attempt_time = self.__last_attempt_time
            result.last_attempt_size = self.__last_attempt_size
            result.last_response = self.__last_response
            result.last_response_status = self.__last_response_status
            result.total_errors = self.__total_errors
            result.total_rate_limited_time = self.__total_rate_limited_time
            result.rate_limited_time_since_last_status = (
                self.__rate_limited_time_since_last_status
            )
            result.total_copy_iterations = self.total_copy_iterations
            result.total_read_time = self.total_read_time
            result.total_waiting_time = self.total_waiting_time
            result.total_blocking_response_time = self.total_blocking_response_time
            result.total_request_time = self.total_request_time
            result.total_pipelined_requests = self.total_pipelined_requests

            for processor in self.__log_processors:
                log_processor_status = processor.generate_status()
                log_processor_status.worker_id = self._id
                result.log_processors.append(log_processor_status)

            if self.__last_attempt_time:
                result.health_check_result = "Good"
                if (
                    time.time()
                    > self.__last_attempt_time
                    + self.__config.healthy_max_time_since_last_copy_attempt
                ):
                    result.health_check_result = (
                        "Worker '%s' failed, max time since last copy attempt (%s seconds) exceeded"
                        % (
                            self._id,
                            self.__config.healthy_max_time_since_last_copy_attempt,
                        )
                    )

        finally:
            self.__lock.release()
        if warn_on_rate_limit:
            if self.__rate_limited_time_since_last_status > 0:
                log.warning(
                    "Warning, the maximum send rate has been exceeded (configured through "
                    "'max_send_rate_enforcement').  Log upload is being delayed and may result in skipped log "
                    "lines.  Copying has been delayed %.1f seconds in the last %.1f minutes. This may be "
                    "desired (due to excessive bytes from a problematic log file) or you may wish to adjust "
                    "the allowed send rate."
                    % (
                        self.__rate_limited_time_since_last_status,
                        self.__config.copying_manager_stats_log_interval / 60.0,
                    )
                )
            self.__rate_limited_time_since_last_status = 0

        return result

    def _sleep_but_awaken_if_stopped(self, seconds):
        """Makes the current thread (the copying manager thread) go to sleep for the specified number of seconds,
        or until the manager is stopped, whichever comes first.

        Note, this method is exposed for testing purposes.

        @param seconds: The number of seconds to sleep.
        @type seconds: float
        """
        self._run_state.sleep_but_awaken_if_stopped(seconds)

    def _create_add_events_request(self, session_info=None, max_size=None):
        """Creates and returns a new AddEventRequest.

        This is created using the current instance of the scalyr client.

        Note, this method is exposed for testing purposes.

        @param session_info:  The attributes to include as session attributes
        @param max_size:  The maximum number of bytes that request is allowed (when serialized)

        @type session_info: JsonObject or dict
        @type max_size: int

        @return: The add events request
        @rtype: AddEventsRequest
        """
        return self.__scalyr_client.add_events_request(
            session_info=session_info, max_size=max_size
        )

    def _send_events(self, add_events_task):
        """Sends the AddEventsRequest contained in the task but does not block on the response.

        Note, this method is exposed for testing purposes.

        @param add_events_task: The task whose request should be sent.
        @type add_events_task: AddEventsTask

        @return: A function, that when invoked, will block on the response and return a tuple containing the status
            message, the number of bytes sent, and the actual response itself.
        @rtype: func
        """
        # TODO: Re-enable not actually sending an event if it is empty.  However, if we turn this on, it
        # currently causes too much error output and the client connection closes too frequently.  We need to
        # actually send some sort of application level keep alive.
        # if add_events_task.add_events_request.total_events > 0:
        return self.__scalyr_client.send(
            add_events_task.add_events_request, block_on_response=False
        )
        # else:
        #    return "success", 0, "{ status: \"success\", message: \"RPC not sent to server because it was empty\"}"

    def __get_next_add_events_task(self, bytes_allowed_to_send, for_pipelining=False):
        """Returns a new AddEventsTask getting all of the pending bytes from the log files that need to be copied.

        @param bytes_allowed_to_send: The maximum number of bytes that can be copied in this request.
        @param for_pipelining:  True if this request is being used for a pipelined request.  We have slightly different
            behaviors for pipelined requests.  For example, we do not return a pipelined request if we do not have
            any events in it.  (For normal ones we do because they act as a keep-alive).

        @type bytes_allowed_to_send: int
        @type for_pipelining: bool

        @return: The new AddEventsTask
        @rtype: AddEventsTask
        """
        log.log(
            scalyr_logging.DEBUG_LEVEL_1,
            "Getting batch of events to send. (pipelining=%s)"
            % six.text_type(for_pipelining),
        )
        start_time = time.time()

        # We have to iterate over all of the LogFileProcessors, getting bytes from them.  We also have to
        # collect all of the callback that they give us and wrap it into one massive one.
        # all_callbacks maps the callback for a processor keyed by the processor's unique id.  We use the unique id to
        # provide a stable mapping, even if the list of log processors changes between now and when we process
        # the response (which it may if pipelining is turned on and we process the other request's response).
        all_callbacks = {}
        logs_processed = 0

        # Initialize the looping variable to the processor we last left off at on a previous run through this method.
        # This is an index into the __log_processors list.
        current_processor = self.__current_processor

        # The list could have shrunk since the last time we were in this loop, so adjust current_process if needed.
        if current_processor >= len(self.__log_processors):
            current_processor = 0

        # Track which processor we first look at in this method.
        first_processor = current_processor

        # Whether or not the max bytes allowed to send has been reached.
        buffer_filled = False

        add_events_request = self._create_add_events_request(
            session_info=self.__expanded_server_attributes,
            max_size=bytes_allowed_to_send,
        )

        if for_pipelining:
            add_events_request.increment_timing_data(**{"pipelined": 1.0})

        while not buffer_filled and logs_processed < len(self.__log_processors):
            # Iterate, getting bytes from each LogFileProcessor until we are full.
            processor = self.__log_processors[current_processor]
            (callback, buffer_filled) = processor.perform_processing(add_events_request)

            # A callback of None indicates there was some error reading the log.  Just retry again later.
            if callback is None:
                # We have to make sure we rollback any LogFileProcessors we touched by invoking their callbacks.
                for cb in six.itervalues(all_callbacks):
                    cb(LogFileProcessor.FAIL_AND_RETRY)
                end_time = time.time()
                self.total_read_time += end_time - start_time
                return None

            all_callbacks[processor.unique_id] = callback
            logs_processed += 1

            # Advance if the buffer if not filled.  Also, even if it is filled, if we are on the first
            # processor we tried, then make sure next time we come through this method, we use the next one.
            # This prevents us from getting stuck on one processor for too long.
            if not buffer_filled or current_processor == first_processor:
                self.__current_processor += 1
                if self.__current_processor >= len(self.__log_processors):
                    self.__current_processor = 0
                current_processor = self.__current_processor
            else:
                break
        end_time = time.time()
        self.total_read_time += end_time - start_time

        # Define the single callback we will return to wrap all of the callbacks we have collected.
        def handle_completed_callback(result):
            """Invokes the callback for all the LogFileProcessors that were touched, along with doing clean up work.

            @param result: The type of result of sending the AddEventRequest, one of LogFileProcessor.SUCCESS,
                LogFileProcessor.FAIL_AND_RETRY, LogFileProcessor.FAIL_AND_DROP.
            @type result: int

            @return: Return the log bytes copied in this request, the sum of all bytes copied as reported by individual
                processors.
            """
            # TODO:  This might not be bullet proof here.  We copy __log_processors and then update it at the end
            # We could be susceptible to exceptions thrown in the middle of this method, though now should.

            # Copy the processor list because we may need to remove some processors if they are done.
            processor_list = self.__log_processors[:]
            self.__log_processors = []

            add_events_request.close()

            total_bytes_copied = 0

            for processor in processor_list:
                # Iterate over all the processors, seeing if we had a callback for that particular processor.
                if processor.unique_id in all_callbacks:
                    # noinspection PyCallingNonCallable
                    # If we did have a callback for that processor, report the status and see if we callback is done.
                    (closed_processor, bytes_copied) = all_callbacks[
                        processor.unique_id
                    ](result)
                    keep_it = not closed_processor
                    total_bytes_copied += bytes_copied
                else:
                    keep_it = True

                if keep_it:
                    self.__log_processors.append(processor)
                else:
                    processor.close()

            return total_bytes_copied

        if for_pipelining and add_events_request.num_events == 0:
            handle_completed_callback(LogFileProcessor.SUCCESS)
            return None

        log.log(
            scalyr_logging.DEBUG_LEVEL_1,
            "Information for batch of events. (pipelining=%s): %s"
            % (six.text_type(for_pipelining), add_events_request.get_timing_data()),
        )
        return AddEventsTask(add_events_request, handle_completed_callback)

    def __scan_for_new_bytes(self, current_time=None):
        """For any existing LogFileProcessors, have them scan the file system to see if their underlying files have
        grown.

        This does not perform any processing on the file nor advances the file's position.

        This is mainly used to just update the statistics about the files for reporting purposes (i.e., the number
        of pending bytes, etc).
        """
        if self.__disable_scan_for_new_bytes:
            log.log(scalyr_logging.DEBUG_LEVEL_0, "Scanning for new bytes disabled.")
            return

        if current_time is None:
            current_time = time.time()
        for processor in self.__log_processors:
            processor.scan_for_new_bytes(current_time)

    def __write_checkpoint_state(
        self, log_processors, base_file, current_time, full_checkpoint
    ):
        # type: (List[LogFileProcessor], six.text_type, float, bool) -> None
        """Writes the current checkpoint state to disk.

        This must be done periodically to ensure that if the agent process stops and starts up again, we pick up
        from where we left off copying each file.
        """
        # Create the format that is expected.  An overall dict with the time when the file was written,
        # and then an entry for each file path.
        checkpoints = {}

        for processor in log_processors:
            if full_checkpoint or processor.is_active:
                checkpoints[processor.get_log_path()] = processor.get_checkpoint()

            if full_checkpoint:
                processor.set_inactive()

        file_path = os.path.join(self.__config.agent_data_path, base_file)

        write_checkpoint_state_to_file(checkpoints, file_path, current_time)

    def _write_full_checkpoint_state(self, current_time):
        """Writes the full checkpont state to disk.

        This must be done periodically to ensure that if the agent process stops and starts up again, we pick up
        from where we left off copying each file.

        """
        self.__write_checkpoint_state(
            self.__log_processors,
            "checkpoints-%s.json" % self._id,
            current_time,
            full_checkpoint=True,
        )
        self.__write_active_checkpoint_state(current_time)

    def __write_active_checkpoint_state(self, current_time):
        """Writes checkpoints only for logs that have been active since the last full checkpoint write
        """
        self.__write_checkpoint_state(
            self.__log_processors,
            "active-checkpoints-%s.json" % self._id,
            current_time,
            full_checkpoint=False,
        )

    def __has_pending_log_changes(self):
        return True

    def get_id(self):
        return self._id

    def get_log_processors(self):  # type: () -> List[LogFileProcessor]
        """
        List of log processors. Exposed only for test purposes.
        """
        return self.__log_processors[:]

    def start_worker(self):
        self.start()

    def stop_worker(self, wait_on_join=True, join_timeout=5):
        """Stops the worker.

        @param wait_on_join: If True, will block on a join of the thread running the worker.
        @param join_timeout: The maximum number of seconds to block for the join.
        """
        self.stop(wait_on_join=wait_on_join, join_timeout=join_timeout)

    def create_and_schedule_new_log_processor(self, *args, **kwargs):
        # type: (*Any, **Any) -> LogFileProcessor
        """
        Creates and also schedules a new log processor. It will be added to the main collection only on the next iteration,
        so we don't have to guard the main collection with lock.
        """
        log_processor = LogFileProcessor(*args, **kwargs)

        with self.__lock:
            self.__new_log_processors.append(log_processor)

        log.log(
            scalyr_logging.DEBUG_LEVEL_1,
            "Log processor for file '%s' is scheduled to be added"
            % log_processor.get_log_path(),
        )

        return log_processor

    def __add_new_log_processors(self):
        """
        Add all previously scheduled log processors to the main collection.
        :return:
        """
        with self.__lock:
            new_log_processors = self.__new_log_processors[:]
            self.__new_log_processors = []

        for new_log_processor in new_log_processors:
            log_path = new_log_processor.get_log_path()
            self.__log_processors.append(new_log_processor)
            log.log(
                scalyr_logging.DEBUG_LEVEL_1,
                "Log processor for file '%s' is added." % log_path,
            )

    def augment_user_agent_for_client_session(self, fragments):
        # type: (List[six.text_type]) -> None
        """
        Modifies User-Agent header of the session of the worker.

        @param fragments String fragments to append (in order) to the standard user agent data
        @type fragments: List of six.text_type
        """
        with self.__lock:
            self.__scalyr_client.augment_user_agent(fragments)

    def generate_scalyr_client_status(self):
        return self.__scalyr_client.generate_status()

    def _init_scalyr_client(self, quiet=False):
        """Creates and returns a new client to the Scalyr servers.

        @param quiet: If true, only errors should be written to stdout.
        @type quiet: bool

        @return: The client to use for sending requests to Scalyr, using the server address and API write logs
            key in the configuration file.
        """
        api_key = self.__api_key_config_entry["api_key"]
        if self.__config.use_new_ingestion:

            self.__new_scalyr_client = create_new_client(self.__config, api_key=api_key)
        else:
            self.__scalyr_client = create_client(
                self.__config, quiet=quiet, api_key=api_key
            )


if sys.version_info >= (3, 6, 0):

    def FixedRebuildProxy(func, token, serializer, kwds):
        """
        Function used for unpickling proxy objects. There is a bug in version >=3.6, so we need to monkeypatch it.
        """
        server = getattr(
            multiprocessing.process.current_process(), "_manager_server", None
        )
        if server and server.address == token.address:
            multiprocessing.util.debug(
                "Rebuild a proxy owned by manager, token=%r", token
            )
            kwds["manager_owned"] = True
            if token.id not in server.id_to_local_proxy_obj:
                server.id_to_local_proxy_obj[token.id] = server.id_to_obj[token.id]
            return server.id_to_obj[token.id][0]
        incref = kwds.pop("incref", True) and not getattr(
            multiprocessing.process.current_process(), "_inheriting", False
        )
        return func(token, serializer, incref=incref, **kwds)

    multiprocessing.managers.RebuildProxy = FixedRebuildProxy  # type: ignore


# create base proxy class for the LogFileProcessor, here we also specify all its methods that may be called through proxy.
_LogFileProcessorProxy = multiprocessing.managers.MakeProxyType(  # type: ignore
    six.ensure_str("LogFileProcessorProxy"),
    [
        six.ensure_str("is_closed"),
        six.ensure_str("close_at_eof"),
        six.ensure_str("close"),
        six.ensure_str("add_missing_attributes"),
        six.ensure_str("get_log_path"),
        six.ensure_str("generate_status"),
        six.ensure_str("add_sampler"),
        six.ensure_str("add_redacter"),
        six.ensure_str("skip_to_end"),
    ],
)


# Create final proxy class for the LogFileProcessors by subclassing the base class.
class LogFileProcessorProxy(_LogFileProcessorProxy):  # type: ignore
    def __init__(self, *args, **kwargs):
        super(LogFileProcessorProxy, self).__init__(*args, **kwargs)
        self.__cached_log_path = None

    def get_log_path(self):
        """
        The log path does not change so it's better to cache it to reduce the load to IPC channel.
        """
        if self.__cached_log_path is None:
            self.__cached_log_path = self._callmethod("get_log_path")
        return self.__cached_log_path


# methods of the worker class that should be exposed through proxy object.
WORKER_PROXY_EXPOSED_METHODS = [
    six.ensure_str("start_worker"),
    six.ensure_str("stop_worker"),
    six.ensure_str("wait_for_copying_to_begin"),
    six.ensure_str("get_id"),
    six.ensure_str("augment_user_agent_for_client_session"),
    six.ensure_str("generate_status"),
    six.ensure_str("generate_scalyr_client_status"),
    six.ensure_str("schedule_new_log_processor"),
    six.ensure_str("generate_scalyr_client_status"),
    six.ensure_str("get_log_processors"),
    six.ensure_str("create_and_schedule_new_log_processor"),
]

# create base proxy class for the worker, here we also specify all its methods that may be called through proxy.
_CopyingManagerWorkerProxy = multiprocessing.managers.MakeProxyType(  # type: ignore
    six.ensure_str("CopyingManagerWorkerProxy"), WORKER_PROXY_EXPOSED_METHODS,
)


# Create final proxy class for the worker class by subclassing the base class.
class CopyingManagerWorkerProxy(_CopyingManagerWorkerProxy):  # type: ignore
    pass


def create_shared_object_manager(worker_class, worker_proxy_class):
    """
    Creates and returns an instance of the subclass of the 'scalyr_utils.ParentAwareSyncManager' and also registers
    all proxy types that will be needed for the multiprocess worker.
    This is done in function, only to be reusable by the tests.
    :param worker_class: The worker class to "proxify"
    :param worker_proxy_class: The predefined worker proxy class.
    :return: a new instance of the 'scalyr_utils.ParentAwareSyncManager' with registered proxies.
    """

    class _SharedObjectManager(scalyr_util.ParentProcessAwareSyncManager):
        """
        The subclass of the 'scalyr_util.ParentAwareSyncManager' which also has access to the worker
        instance in order to stop it if the parent process is killed.

        According to the fact that the worker runs in manager's process in a separate thread, we have to
        handle the situation where the agent was killed and worker remain alive in the manager's process
        and keeps sending logs.
        """

        def __init__(self, *args, **kwargs):
            super(_SharedObjectManager, self).__init__(*args, **kwargs)

            self._worker = None  # type: Optional[CopyingManagerWorker]

        def _create_worker(self, configuration, api_key_config_entry, worker_id):
            # type: (Configuration, Dict, six.text_type) -> CopyingManagerWorker
            """
            Create a new worker and save it as an attribute.

            To be able to access the worker's instance within the local process.

            The arguments are the same as in the workers's constructor.
            :return: the proxy object for the worker instance.
            """

            # we set 'is_daemon' as True in order to be able to stop the
            # worker's thread if the  manager's main thread is exited.
            # but it is just a 'last stand' option when the graceful worker stop is failed.
            self._worker = worker_class(
                configuration, api_key_config_entry, worker_id, is_daemon=True
            )

            return self._worker  # type: ignore

        def _on_parent_process_kill(self):
            """
            Override the callback which is invoked when the parent process is killed,
            so we have to stop the workers before this process will be terminated.
            """
            log.error(
                "The main agent process does not exist. Probably it was forcibly killed. "
                "Checking if the worker is still alive."
            )
            if self._worker and self._worker.is_alive():
                log.error("The worker is alive. Stopping it.")
                try:
                    self._worker.stop_worker()
                except:
                    log.exception(
                        "Can not stop the worker. Waiting before killing the process..."
                    )
                    # can not stop worker gracefully, just wait for the main thread of the process exits and
                    # the worker's thread(since it is a daemon)  will be terminated too.

        @classmethod
        def _on_exit(cls, error=None):
            """
            Just add more log messages before the process is terminated.
            :return:
            """
            if error:
                log.error("The shared object manager thread has ended with an error.")
            else:
                log.info("The shared object manager of the worker has stopped.")

    manager = _SharedObjectManager()

    # pylint: disable=E1101
    manager.register(
        six.ensure_str("LogFileProcessorProxy"), proxytype=LogFileProcessorProxy
    )

    manager.register(
        six.ensure_str("create_worker"),
        manager._create_worker,
        worker_proxy_class,
        method_to_typeid={
            six.ensure_str("get_log_processors"): six.ensure_str("list"),
            six.ensure_str("create_and_schedule_new_log_processor"): six.ensure_str(
                "LogFileProcessorProxy"
            ),
        },
    )
    # pylint: enable=E1101

    return manager
