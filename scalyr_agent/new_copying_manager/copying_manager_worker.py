from __future__ import unicode_literals
from __future__ import absolute_import
from __future__ import print_function

import threading
import time
import sys
import os
import collections
import datetime

if False:
    from typing import Dict
    from typing import List
    from typing import Set
    from typing import Optional

import scalyr_agent.util as scalyr_util
from scalyr_agent import scalyr_logging

from scalyr_agent.log_processing import LogFileProcessor

from scalyr_agent.util import StoppableThread, RateLimiter
from scalyr_agent.agent_status import CopyingManagerWorkerStatus

log = scalyr_logging.getLogger(__name__)
#log.setLevel(scalyr_logging.DEBUG_LEVEL_5)

import six


class LogProcessorSpawner(object):
    def __init__(self, *args, **kwargs):
        self.__args = args
        self.__log_config = args[2]
        self.__kwargs = kwargs

    def spawn_log_processor(self):
        new_processor = LogFileProcessor(*self.__args, **self.__kwargs)

        for rule in self.__log_config["redaction_rules"]:
            new_processor.add_redacter(
                rule["match_expression"],
                rule["replacement"],
                six.text_type(rule.get("hash_salt", default_value="")),
            )
        for rule in self.__log_config["sampling_rules"]:
            new_processor.add_sampler(
                rule["match_expression"], rule.get_float("sampling_rate", 1.0),
            )

        return new_processor


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


class CopyingManagerWorker(StoppableThread):
    def __init__(self, configuration, worker_config_entry, worker_id):
        super(CopyingManagerWorker, self).__init__(
            name="copying manager worker thread #%s" % worker_id
        )

        self._id = six.text_type(worker_id)
        self.__config = configuration
        self.__worker_config_entry = worker_config_entry

        self.__rate_limiter = None
        if self.__config.parsed_max_send_rate_enforcement:
            self.__rate_limiter = RateLimiter(
                # Making the bucket size 4 times the bytes per second, it shouldn't affect the rate over a long time
                # meaningfully but we don't have a rationale for this value.
                # TODO: Make this configurable as part of the `max_send_rate_enforcement` configuration option
                self.__config.parsed_max_send_rate_enforcement * 4.0,
                self.__config.parsed_max_send_rate_enforcement,
            )

        # The client to use for sending the data.  Set in the start_manager call.
        self.__scalyr_client = None

        # A lock that protects the status variables, the only variables that
        # are access in generate_status() which needs to be thread safe.
        self.__lock = threading.Lock()

        # A semaphore that we increment when this object has begun copying files (after first scan).
        self.__copying_semaphore = threading.Semaphore(0)

        # collect monitor-specific extra server-attributes.  seed with a copy of the attributes and converted to a dict.
        self.__expanded_server_attributes = self.__config.server_attributes.to_dict()

        # The current pending AddEventsTask.  We will retry the contained AddEventsRequest serveral times.
        self.__pending_add_events_task = None

        # The list of LogFileProcessors that are processing the lines from matched log files.

        self.__log_processors = (
            collections.OrderedDict()
        )  # type: Dict[six.text_type, LogFileProcessor]

        self.__log_processors_to_close = {}
        self.__log_processors_to_close_at_eof = []
        self.__closed_processors = []
        self.__log_processors_to_remove = []

        self.__log_processors_closed_at_eof = {}

        # Temporary collection of recently added log processors.
        # Every log processor which is added during the iteration of the worker is placed in here.
        # All those log processors will be added to the main collection
        # on the beginning of the next iteration.
        # It stores all new log processors before they are added to the main log processors list.

        self.__pending_log_processors = collections.OrderedDict()

        self.__log_processors_scheduled_for_removal = dict()

        # The next LogFileProcessor that should have log lines read from it for transmission.
        self.__current_processor = 0

        self.__id = None

        # debug leaks
        self.__disable_scan_for_new_bytes = configuration.disable_scan_for_new_bytes

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

        # Statistics for copying_manager_status messages
        self.total_copy_iterations = 0
        self.total_read_time = 0
        self.total_waiting_time = 0
        self.total_blocking_response_time = 0
        self.total_request_time = 0
        self.total_pipelined_requests = 0

    @property
    def log_processors(self):
        # type: () -> Dict[six.text_type, LogFileProcessor]
        """
        List of log processors. Exposed only for test purposes.
        """
        with self.__lock:
            return self.__log_processors.copy()

    @property
    def worker_config_entry(self):
        return self.__worker_config_entry

    def add_log_processors(self, log_processors_infos):
        # type: (LogFileProcessor) -> None
        """
        Add new log_processor.
        """
        with self.__lock:
            for info in log_processors_infos:
                self.__pending_log_processors[info.path] = info.spawn_log_processor()

    def close_processors(self, processors_paths, at_eof=False):
        with self.__lock:
            for path in processors_paths:
                processor = self.__log_processors[path]
                if at_eof:
                    processor.close_at_eof()
                else:
                    processor.close()

    def move_closed_processors(self):
        pass

        self.__lock.acquire()
        try:
            logs_to_remove = self.__log_processors_scheduled_for_removal.copy()

            self.__log_processors_scheduled_for_removal = {}

            for path, processor in logs_to_remove.items():
                if path not in self.__log_processors:
                    log.warning(
                        (
                            "Can not remove log processor for file: '{0}' from worker '{1}'. "
                            "There is no such log processor."
                        ).format(path, self._id)
                    )
                    continue

                self.__log_processors.pop(path)
                log.log(
                    scalyr_logging.DEBUG_LEVEL_0,
                    "Log processor for file '%s' has been removed from worker #%s"
                    % (path, self._id),
                )
        finally:
            self.__lock.release()

    def start_worker(self, scalyr_client):
        self.__scalyr_client = scalyr_client
        self.start()
        log.info("Worker started.")

    def stop_worker(self, wait_on_join=True, join_timeout=5):
        """Stops the worker.

        @param wait_on_join: If True, will block on a join of the thread running the worker.
        @param join_timeout: The maximum number of seconds to block for the join.
        """
        self.stop(wait_on_join=wait_on_join, join_timeout=join_timeout)

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

        # Make sure start_manager was invoked to start the thread and we have a scalyr client instance.
        assert self.__scalyr_client is not None

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
                            with self.__lock:
                                for processor in self.__log_processors.values():
                                    processor.skip_to_end(
                                        "Too long since last successful request to server.",
                                        "skipNoServerSuccess",
                                        current_time=current_time,
                                    )

                        # # add pending log processors.
                        # log.log(
                        #     scalyr_logging.DEBUG_LEVEL_5,
                        #     "Start adding pending log processors on worker #%s"
                        #     % self._id,
                        # )

                        # Collect log lines to send if we don't have one already.
                        if self.__pending_add_events_task is None:
                            with self.__lock:
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
                            with self.__lock:
                                self.__scan_for_new_bytes(current_time=current_time)

                        # Try to send the request if we have one.
                        if self.__pending_add_events_task is not None:
                            log.log(
                                scalyr_logging.DEBUG_LEVEL_1,
                                "Sending an add event request",
                            )
                            # Send the request, but don't block for the response yet.
                            send_request_time_start = time.time()
                            get_response = self._send_events(
                                self.__pending_add_events_task
                            )

                            # If we are sending very large requests, we will try to optimize for future requests
                            # by overlapping building the request with waiting for the response on the current request
                            # (pipelining).
                            if (
                                self.__pending_add_events_task.add_events_request.current_size
                                >= pipeline_byte_threshold
                                and self.__pending_add_events_task.next_pipelined_task
                                is None
                            ):

                                # Time how long it takes us to build it because we will subtract it from how long we
                                # have to wait before we send the next request.
                                pipeline_time = time.time()
                                self.total_pipelined_requests += 1
                                with self.__lock:
                                    self.__pending_add_events_task.next_pipelined_task = self.__get_next_add_events_task(
                                        copying_params.current_bytes_allowed_to_send,
                                        for_pipelining=True,
                                    )
                            else:
                                pipeline_time = 0.0

                            # Now block for the response.
                            blocking_response_time_start = time.time()
                            with self.__lock:
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

                        # log.log(
                        #     scalyr_logging.DEBUG_LEVEL_2,
                        #     "Start removing log processors.",
                        # )
                        #
                        # log.log(
                        #     scalyr_logging.DEBUG_LEVEL_2,
                        #     "Done removing log processors.",
                        # )

                        if profiler is not None:
                            seconds_past_epoch = int(time.time())
                            if seconds_past_epoch % profile_dump_interval == 0:
                                profiler.disable()
                                profiler.dump_stats(
                                    "%s%s"
                                    % (
                                        self.__config.copying_thread_profile_output_path,
                                        datetime.datetime.now().strftime(
                                            "%H_%M_%S.out"
                                        ),
                                    )
                                )
                                profiler.enable()
                    except Exception as e:
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
                        with self.__lock:
                            self.__write_full_checkpoint_state(current_time)
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
                # If we got an exception here, it is caused by a bug in the program, so let's just terminate.
                log.exception("Log copying failed due to exception")
                sys.exit(1)
        finally:
            with self.__lock:
                self.__write_full_checkpoint_state(current_time)
                for processor in self.__log_processors.values():
                    processor.close()
                if profiler is not None:
                    profiler.disable()

        print("WORKER END")

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
        log_processors = list(self.__log_processors.values())

        current_processor = self.__current_processor

        # The list could have shrunk since the last time we were in this loop, so adjust current_process if needed.
        if current_processor >= len(log_processors):
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

        while not buffer_filled and logs_processed < len(log_processors):
            # Iterate, getting bytes from each LogFileProcessor until we are full.
            processor = log_processors[current_processor]
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
                if self.__current_processor >= len(log_processors):
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
            processor_list = self.__log_processors
            self.__log_processors = collections.OrderedDict()

            add_events_request.close()

            total_bytes_copied = 0

            for path, processor in processor_list.items():
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
                    self.__log_processors[path] = processor
                else:
                    self.__log_processors_closed_at_eof[path] = processor
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
        """For any existing LogProcessors, have them scan the file system to see if their underlying files have
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
        for processor in self.__log_processors.values():
            processor.scan_for_new_bytes(current_time)

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

    def __write_checkpoint_state(
        self, log_processors, base_file, current_time, full_checkpoint
    ):
        """Writes the current checkpoint state to disk.

        This must be done periodically to ensure that if the agent process stops and starts up again, we pick up
        from where we left off copying each file.
        """
        # Create the format that is expected.  An overall dict with the time when the file was written,
        # and then an entry for each file path.
        checkpoints = {}
        state = {
            "time": current_time,
            "checkpoints": checkpoints,
        }

        for path, processor in log_processors.items():
            if full_checkpoint or processor.is_active:
                checkpoints[path] = processor.get_checkpoint()

            if full_checkpoint:
                processor.set_inactive()

        checkpoints_dir_path = os.path.join(
            self.__config.agent_data_path, "checkpoints"
        )

        try:
            os.mkdir(checkpoints_dir_path)
        except OSError as e:
            # re-raise if there is no 'already exists' error.
            if e.errno != 17:
                raise
            if os.path.isfile(checkpoints_dir_path):
                # if there is a file, remove it.
                os.unlink(checkpoints_dir_path)

        # We write to a temporary file and then rename it to the real file name to make the write more atomic.
        # We have had problems in the past with corrupted checkpoint files due to failures during the write.
        file_path = os.path.join(
            self.__config.agent_data_path, checkpoints_dir_path, base_file
        )
        tmp_path = os.path.join(
            self.__config.agent_data_path, checkpoints_dir_path, base_file + "~"
        )
        scalyr_util.atomic_write_dict_as_json_file(file_path, tmp_path, state)

    def __write_active_checkpoint_state(self, current_time):
        """Writes checkpoints only for logs that have been active since the last full checkpoint write
        """
        self.__write_checkpoint_state(
            self.__log_processors,
            "active-checkpoints-%s.json" % self._id,
            current_time,
            full_checkpoint=False,
        )

    def __write_full_checkpoint_state(self, current_time):
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

            for path, processor in self.__log_processors.items():
                result.log_processors[path] = processor.generate_status()

            if self.__last_attempt_time:
                result.health_check_result = "Good"
                if (
                    time.time()
                    > self.__last_attempt_time
                    + self.__config.healthy_max_time_since_last_copy_attempt
                ):
                    result.health_check_result = (
                        "Failed, max time since last copy attempt (%s seconds) exceeded"
                        % self.__config.healthy_max_time_since_last_copy_attempt
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

    def wait_for_copying_to_begin(self):
        """Block the current thread until this instance has finished its first scan and has begun copying.

        It is good to wait for the first scan to finish before possibly creating new files to copy because
        if the first scan has not completed, the copier will just begin copying at the end of the file when
        it is first noticed.  However, if the first scan has completed, then the copier will know that the
        new file was just newly created and should therefore have all of its bytes copied to Scalyr.

        TODO:  Make it so that this thread does not block indefinitely if the copying never starts.  However,
        we do not do this now because the CopyManager's run method will sys.exit if the copying fails to start.
        """
        self.__copying_semaphore.acquire(True)

    def _sleep_but_awaken_if_stopped(self, seconds):
        """Makes the current thread (the copying manager worker thread) go to sleep for the specified number of seconds,
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

    @property
    def worker_id(self):  # type: () -> six.text_type
        return self._id

    def interact(
        self,
        new_processor_spawners=None,
        processors_to_close=None,
        processors_to_close_at_eof=None
    ):
        # type: (Optional[List[LogProcessorSpawner]], Optional[Set[six.text_type]], Optional[Set[six.text_type]]) -> Tuple[Set[six.text_type], Set[six.text_type]
        """
        This function does all needed interaction with the worker instance.
        NOTE: Since workers can work in multiprocessing mode, this function is also the main and single point
        of the IPC between worker processes and process of the main manager.
        Due to that this is important to keep all its arguments picklable.

        :param new_processor_spawners: Callables that creates new log processor. As mentioned above,
        this method gets only picklable objects, so we can not pass a new log processors directly from the master manager.
        That's why it gets only a "spawner" objects which are just store all information that is needed to create log processor.
        new processors argument contains only
        :param processors_to_close: dict that stores information about processors that need to be close
        where key is a path of the file and value is a bool. If value is True,
        then processor must be closed only when it reaches "EOF"
        :return:
        """

        if processors_to_close:
            a =10

        if processors_to_close is None:
            processors_to_close = {}

        if processors_to_close_at_eof is None:
            processors_to_close_at_eof = {}

        # it is important to create log processors as soon as possible
        # to open and to keep holding the file descriptor.
        new_processors = collections.OrderedDict()
        if new_processor_spawners:
            for spawner in new_processor_spawners:
                new_processor = spawner.spawn_log_processor()
                new_processors[new_processor.log_path] = new_processor

        closed_processors = {}
        active_processors = set()
        with self.__lock:
            # add newly create processors to the main collection.
            self.__log_processors.update(new_processors)
            active_processors.update(new_processors)

            # remove closing log processors from the main collection and
            # store them in separate list to close them outside of the lock.
            for path, log_processor in list(self.__log_processors.items()):
                if path in processors_to_close:
                    closed_processors[path] = log_processor
                elif path in processors_to_close_at_eof:
                    log_processor.close_at_eof()
                else:
                    active_processors.add(log_processor.log_path)

                # # if log processor is presented this dict that means that it should be closed.
                # # Also, the returned value shows how exactly log processor should be closed.
                # is_close_at_eof = processors_to_close.get(path)
                #
                # is_removed = False
                #
                # if is_close_at_eof is not None:
                #     if is_close_at_eof:
                #         # wait for close, do not remove from log processors main collection.
                #         log_processor.close_at_eof()
                #     else:
                #         # prepare to close and remove this log processor.
                #         is_removed = True
                # if log_processor.is_closed():
                #     # also remove log processor if it was closed by itself.
                #     is_removed = True
                #
                # if is_removed:
                #     # if processor is closed immediately, so we also remove it from the main collection.
                #     self.__log_processors.pop(path)
                #     # also add it to separate collection to be able to close all processors outside of the lock.
                #     self.__log_processors.pop(log_processor.log_path)
                #     closed_processors[log_processor.log_path] = log_processor
                # else:
                #     active_processors.add(log_processor.log_path)

            closed_processors.update(self.__log_processors_closed_at_eof)
            self.__log_processors_closed_at_eof = {}



        # finally close needed log processors.
        for processor in closed_processors.values():
            processor.close()






        log.log(
            scalyr_logging.DEBUG_LEVEL_0,
            "Worker #{0} has interacted with copying manager. Log file processors active: [{1}], closed [{2}]".format(
                self._id,
                "".join(active_processors),
                "".join(closed_processors)
            )
        )

        return active_processors, set(closed_processors)