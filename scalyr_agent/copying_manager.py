# Copyright 2014 Scalyr Inc.
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
# ------------------------------------------------------------------------
#
#
# author: Steven Czerwinski <czerwin@scalyr.com>

__author__ = 'czerwin@scalyr.com'

import os
import threading
import time
import sys

import scalyr_agent.scalyr_logging as scalyr_logging
import scalyr_agent.util as scalyr_util

from scalyr_agent import json_lib
from scalyr_agent.util import StoppableThread
from scalyr_agent.log_processing import LogMatcher, LogFileProcessor
from scalyr_agent.agent_status import CopyingManagerStatus

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
        self.__max_error_request_spacing_interval = configuration.max_error_request_spacing_interval

        # The low water mark for the number of bytes sent in a request.  If, when we go to collect the lines that
        # need to be sent from all logs, the amount is lower than this, then we will sleep more between requests.
        self.__low_water_bytes_sent = configuration.low_water_bytes_sent
        # The percentage to adjust the sleeping time if the lower_water_bytes_sent mark is not met.
        self.__low_water_request_spacing_adjustment = configuration.low_water_request_spacing_adjustment
        # The high water mark for the number of bytes sent in a request.  If, when we go to collect the lines that
        # need to be sent from all logs, the amount is higher than this, then we will sleep less between requests.
        self.__high_water_bytes_sent = configuration.high_water_bytes_sent
        # The percentage to adjust the sleeping time if the high_water_bytes_sent mark is exceeded.
        self.__high_water_request_spacing_adjustment = configuration.high_water_request_spacing_adjustment

        # The percentage to adjust the sleeping time if the last request was a failure.
        self.__failure_request_spacing_adjustment = configuration.failure_request_spacing_adjustment

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
        if result == 'success':
            max_request_spacing_interval = self.__max_request_spacing_interval
            if bytes_sent < self.__low_water_bytes_sent:
                self.current_sleep_interval *= self.__low_water_request_spacing_adjustment
            elif bytes_sent > self.__high_water_bytes_sent:
                self.current_sleep_interval *= self.__high_water_request_spacing_adjustment
        else:
            self.current_sleep_interval *= self.__failure_request_spacing_adjustment
            max_request_spacing_interval = self.__max_error_request_spacing_interval

        if result == 'success':
            self.current_bytes_allowed_to_send = self.__max_allowed_request_size
        elif 'requestTooLarge' in result:
            self.current_bytes_allowed_to_send = int(bytes_sent * self.__request_too_large_adjustment)

        self.current_bytes_allowed_to_send = self.__ensure_within(self.current_bytes_allowed_to_send,
                                                                  self.__min_allowed_request_size,
                                                                  self.__max_allowed_request_size)

        self.current_sleep_interval = self.__ensure_within(self.current_sleep_interval,
                                                           self.__min_request_spacing_interval,
                                                           max_request_spacing_interval)

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


class CopyingManager(StoppableThread):
    """Manages the process of copying all configured log files to the Scalyr server.

    This is run as its own thread.
    """
    def __init__(self, scalyr_client, configuration, logs_initial_positions):
        """Initializes the manager.

        @param scalyr_client: The client to use to send requests to Scalyr.
        @param configuration: The configuration file containing which log files need to be copied.
        @param logs_initial_positions: A dict mapping file paths to the offset with the file to begin copying
            if none can be found from the checkpoint files.  This can be used to override the default behavior of
            just reading from the current end of the file if there is no checkpoint for the file

        @type scalyr_client: scalyr_client.ScalyrClientSession
        @type configuration: configuration.Configuration
        @type logs_initial_positions: dict
        """
        StoppableThread.__init__(self, name='log copier thread')
        self.__config = configuration
        # The list of LogMatcher objects that are watching for new files to appear.
        self.__log_matchers = configuration.logs

        # The list of LogFileProcessors that are processing the lines from matched log files.
        self.__log_processors = []
        # A dict from file path to the LogFileProcessor that is processing it.
        self.__log_paths_being_processed = {}
        # A lock that protects the status variables and the __log_matchers variable, the only variables that
        # are access in generate_status() which needs to be thread safe.
        self.__lock = threading.Lock()

        # The current pending AddEventsTask.  We will retry the contained AddEventsRequest serveral times.
        self.__pending_add_events_task = None

        # The next LogFileProcessor that should have log lines read from it for transmission.
        self.__current_processor = 0

        # The client to use for sending the data.
        self.__scalyr_client = scalyr_client
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

        # The positions to use for a given file if there is not already a checkpoint for that file.
        self.__logs_initial_positions = logs_initial_positions

        # A semaphore that we increment when this object has begun copying files (after first scan).
        self.__copying_semaphore = threading.Semaphore()

    @staticmethod
    def build_log(log_config):
        """Returns a LogMatcher instance that will handle matching the log specified in the config.

        @param log_config:  The configuration object containing the log file path to copy, including also
            the attributes that should be included on all copied lines and the redaction and sampling rules.
        @type log_config: dict

        @return:  The LogMatcher that will handle the requested log.
        @rtype: LogMatcher
        """
        return LogMatcher(log_config)

    def run(self):
        """Processes the log files as requested by the configuration, looking for matching log files, reading their
        bytes, applying redaction and sampling rules, and then sending them to the server.

        This method will not terminate until the thread has been stopped.
        """
        # So the scanning.. every scan:
        #   - See if any of the loggers have new files that are being matched
        #   - Update the file length counts of all current scanners:
        #   - Then pick up where you left off, getting X bytes as determined that abstraction
        #   - Send it to the client
        #   - determine success or not.. if success, update it.
        #   - sleep
        # noinspection PyBroadException
        try:
            # Try to read the checkpoint state from disk.
            current_time = time.time()
            checkpoints_state = self.__read_checkpoint_state()
            if checkpoints_state is None:
                log.info('The checkpoints could not be read.  All logs will be copied starting at their current end')
            elif (current_time - checkpoints_state['time']) > self.__config.max_allowed_checkpoint_age:
                log.warn('The current checkpoint is too stale (written at "%s").  Ignoring it.  All log files will be '
                         'copied starting at their current end.', scalyr_util.format_time(
                         checkpoints_state['time']), error_code='staleCheckpointFile')
                checkpoints_state = None

            if checkpoints_state is None:
                checkpoints = None
            else:
                checkpoints = checkpoints_state['checkpoints']

            # Do the initial scan for any log files that match the configured logs we should be copying.  If there
            # are checkpoints for them, make sure we start copying from the position we left off at.
            self.__scan_for_new_logs_if_necessary(current_time=current_time,
                                                  checkpoints=checkpoints,
                                                  logs_initial_positions=self.__logs_initial_positions)

            # The copying params that tell us how much we are allowed to send and how long we have to wait between
            # attempts.
            copying_params = CopyingParameters(self.__config)

            # Just initialize the last time we had a success to now.  Make the logic below easier.
            last_success = time.time()

            # We are about to start copying.  We can tell waiting threads.
            self.__copying_semaphore.release()

            while self._run_state.is_running():
                log.log(scalyr_logging.DEBUG_LEVEL_1, 'At top of copy log files loop.')
                current_time = time.time()
                # noinspection PyBroadException
                try:
                    # If we have a pending request and it's been too taken too long to send it, just drop it
                    # on the ground and advance.
                    if current_time - last_success > self.__config.max_retry_time:
                        if self.__pending_add_events_task is not None:
                            self.__pending_add_events_task.completion_callback(LogFileProcessor.FAIL_AND_DROP)
                            self.__pending_add_events_task = None
                        # Tell all of the processors to go to the end of the current log file.  We will start copying
                        # from there.
                        for processor in self.__log_processors:
                            processor.skip_to_end('Too long since last successful request to server.',
                                                  'skipNoServerSuccess', current_time=current_time)

                    # Check for new logs.  If we do detect some new log files, they must have been created since our
                    # last scan.  In this case, we start copying them from byte zero instead of the end of the file.
                    self.__scan_for_new_logs_if_necessary(current_time=current_time, copy_at_index_zero=True)

                    # Collect log lines to send if we don't have one already.
                    if self.__pending_add_events_task is None:
                        log.log(scalyr_logging.DEBUG_LEVEL_1, 'Getting next batch of events to send.')
                        self.__pending_add_events_task = self.__get_next_add_events_task(
                            copying_params.current_bytes_allowed_to_send)
                    else:
                        log.log(scalyr_logging.DEBUG_LEVEL_1, 'Have pending batch of events, retrying to send.')
                        # Take a look at the file system and see if there are any new bytes pending.  This updates the
                        # statistics for each pending file.  This is important to do for status purposes if we have
                        # not tried to invoke get_next_send_events_task in a while (since that already updates the
                        # statistics).
                        self.__scan_for_new_bytes(current_time=current_time)

                    # Try to send the request if we have one.
                    if self.__pending_add_events_task is not None:
                        (result, bytes_sent, full_response) = self.__send_events(self.__pending_add_events_task)

                        log.log(scalyr_logging.DEBUG_LEVEL_1, 'Sent %ld bytes and received response with status="%s".',
                                bytes_sent, result)

                        if result == 'success' or 'discardBuffer' in result or 'requestTooLarge' in result:
                            if result == 'success':
                                self.__pending_add_events_task.completion_callback(LogFileProcessor.SUCCESS)
                            elif 'discardBuffer' in result:
                                self.__pending_add_events_task.completion_callback(LogFileProcessor.FAIL_AND_DROP)
                            else:
                                self.__pending_add_events_task.completion_callback(LogFileProcessor.FAIL_AND_RETRY)
                            self.__pending_add_events_task = None
                            self.__write_checkpoint_state()

                        if result == 'success':
                            last_success = current_time
                    else:
                        result = 'failedReadingLogs'
                        bytes_sent = 0
                        full_response = ''

                        log.error('Failed to read logs for copying.  Will re-try')

                    # Update the statistics and our copying parameters.
                    self.__lock.acquire()
                    copying_params.update_params(result, bytes_sent)
                    self.__last_attempt_time = current_time
                    self.__last_success_time = last_success
                    self.__last_attempt_size = bytes_sent
                    self.__last_response = full_response
                    self.__last_response_status = result
                    if result == 'success':
                        self.__total_bytes_uploaded += bytes_sent
                    self.__lock.release()

                except Exception:
                    # TODO: Do not catch Exception here.  That is too board.  Disabling warning for now.
                    log.exception('Failed while attempting to scan and transmit logs')
                    log.log(scalyr_logging.DEBUG_LEVEL_1, 'Failed while attempting to scan and transmit logs')
                    self.__lock.acquire()
                    self.__last_attempt_time = current_time
                    self.__total_errors += 1
                    self.__lock.release()

                self._run_state.sleep_but_awaken_if_stopped(copying_params.current_sleep_interval)
        except Exception:
            # If we got an exception here, it is caused by a bug in the program, so let's just terminate.
            log.exception('Log copying failed due to exception')
            sys.exit(1)

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

    def generate_status(self):
        """Generate the status for the copying manager to be reported.

        This is used in such features as 'scalyr-agent-2 status -v'.

        Note, this method is thread safe.  It needs to be since another thread will ask this object for its
        status.

        @return:  The status object containing the statistics for the copying manager.
        @rtype: CopyingManagerStatus
        """
        try:
            self.__lock.acquire()

            result = CopyingManagerStatus()
            result.total_bytes_uploaded = self.__total_bytes_uploaded
            result.last_success_time = self.__last_success_time
            result.last_attempt_time = self.__last_attempt_time
            result.last_attempt_size = self.__last_attempt_size
            result.last_response = self.__last_response
            result.last_response_status = self.__last_response_status
            result.total_errors = self.__total_errors

            for entry in self.__log_matchers:
                result.log_matchers.append(entry.generate_status())

        finally:
            self.__lock.release()

        return result

    def __read_checkpoint_state(self):
        """Reads the checkpoint state from disk and returns it.

        The checkpoint state maps each file path to the offset within that log file where we left off copying it.

        @return:  The checkpoint state
        @rtype: dict
        """
        file_path = os.path.join(self.__config.agent_data_path, 'checkpoints.json')

        if not os.path.isfile(file_path):
            log.info('The log copying checkpoint file "%s" does not exist, skipping.' % file_path)
            return None

        # noinspection PyBroadException
        try:
            return scalyr_util.read_file_as_json(file_path)
        except Exception:
            # TODO:  Fix read_file_as_json so that it will not return an exception.. or will return a specific one.
            log.exception('Could not read checkpoint file due to error.', error_code='failedCheckpointRead')
            return None

    def __write_checkpoint_state(self):
        """Writes the current checkpoint state to disk.

        This must be done periodically to ensure that if the agent process stops and starts up again, we pick up
        from where we left off copying each file.
        """
        # Create the format that is expected.  An overall JsonObject with the time when the file was written,
        # and then an entry for each file path.
        checkpoints = {}
        state = {
            'time': time.time(),
            'checkpoints': checkpoints,
        }

        for processor in self.__log_processors:
            checkpoints[processor.log_path] = processor.get_checkpoint()

        # We write to a temporary file and then rename it to the real file name to make the write more atomic.
        # We have had problems in the past with corrupted checkpoint files due to failures during the write.
        file_path = os.path.join(self.__config.agent_data_path, 'checkpoints.json')
        tmp_path = os.path.join(self.__config.agent_data_path, 'checkpoints.json~')
        fp = None
        try:
            fp = open(tmp_path, 'w')
            fp.write(json_lib.serialize(state))
            fp.close()
            fp = None
            os.rename(tmp_path, file_path)
        except (IOError, OSError):
            if fp is not None:
                fp.close()
            log.exception('Could not write checkpoint file due to error', error_code='failedCheckpointWrite')

    def __get_next_add_events_task(self, bytes_allowed_to_send):
        """Returns a new AddEventsTask getting all of the pending bytes from the log files that need to be copied.

        @param bytes_allowed_to_send: The maximum number of bytes that can be copied in this request.
        @type bytes_allowed_to_send: int
        @return: The new AddEventsTask
        @rtype: AddEventsTask
        """
        # We have to iterate over all of the LogFileProcessors, getting bytes from them.  We also have to
        # collect all of the callback that they give us and wrap it into one massive one.
        all_callbacks = {}
        logs_processed = 0

        # Initialize the looping variable to the processor we last left off at on a previous run through this method.
        # This is an index into the __log_processors list.
        current_processor = self.__current_processor

        # Track which processor we first look at in this method.
        first_processor = current_processor

        # Whether or not the max bytes allowed to send has been reached.
        buffer_filled = False

        add_events_request = self.__scalyr_client.add_events_request(session_info=self.__config.server_attributes,
                                                                     max_size=bytes_allowed_to_send)

        while not buffer_filled and logs_processed < len(self.__log_processors):
            # Iterate, getting bytes from each LogFileProcessor until we are full.
            (callback, buffer_filled) = self.__log_processors[current_processor].perform_processing(
                add_events_request)

            # A callback of None indicates there was some error reading the log.  Just retry again later.
            if callback is None:
                # We have to make sure we rollback any LogFileProcessors we touched by invoking their callbacks.
                for cb in all_callbacks.itervalues():
                    cb(LogFileProcessor.FAIL_AND_RETRY)
                return None

            all_callbacks[current_processor] = callback
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

        # Define the single callback we will return to wrap all of the callbacks we have collected.
        def handle_completed_callback(result):
            """Invokes the callback for all the LogFileProcessors that were touched, along with doing clean up work.

            @param result: The type of result of sending the AddEventRequest, one of LogFileProcessor.SUCCESS,
                LogFileProcessor.FAIL_AND_RETRY, LogFileProcessor.FAIL_AND_DROP.
            @type result: int
            """
            # Copy the processor list because we may need to remove some processors if they are done.
            processor_list = self.__log_processors[:]
            self.__log_processors = []
            # A dict that maps file paths to the processors assigned to them.  This is used to ensure multiple
            # processors do not try to process the same file.
            self.__log_paths_being_processed = {}
            add_events_request.close()

            for i in range(0, len(processor_list)):
                # Iterate over all the processors, seeing if we had a callback for that particular processor.
                processor = processor_list[i]
                if i in all_callbacks:
                    # noinspection PyCallingNonCallable
                    # If we did have a callback for that processor, report the status and see if we callback is done.
                    keep_it = not all_callbacks[i](result)
                else:
                    keep_it = True
                if keep_it:
                    self.__log_processors.append(processor)
                    self.__log_paths_being_processed[processor.log_path] = True

        return AddEventsTask(add_events_request, handle_completed_callback)

    def __send_events(self, add_events_task):
        """Sends the AddEventsRequest contained in the task.

        @param add_events_task: The task whose request should be sent.
        @type add_events_task: AddEventsTask

        @return: The result of sending the request.  It is a tuple of the status message, the number of
            bytes sent, and the actual response itself.
        @rtype: (str, int, str)
        """
        # TODO: Re-enable not actually sending an event if it is empty.  However, if we turn this on, it
        # currently causes too much error output and the client connection closes too frequently.  We need to
        # actually send some sort of application level keep alive.
        #if add_events_task.add_events_request.total_events > 0:
        return self.__scalyr_client.send(add_events_task.add_events_request)
        #else:
        #    return "success", 0, "{ status: \"success\", message: \"RPC not sent to server because it was empty\"}"

    def __scan_for_new_logs_if_necessary(self, current_time=None, checkpoints=None, logs_initial_positions=None,
                                         copy_at_index_zero=False):
        """If it has been sufficient time since we last checked, scan the file system for new files that match the
        logs that should be copied.

        @param checkpoints: A dict mapping file paths to the checkpoint to use for them to determine where copying
            should begin.
        @param logs_initial_positions: A dict mapping file paths to what file offset the copying should begin from
            if there is no checkpoint for them.
        @param copy_at_index_zero: If True, then any new file that doesn't have a checkpoint or an initial position,
            will begin being copied from the start of the file rather than the current end.
        @param current_time: If not None, the time to use as the current time.

        @type checkpoints: dict
        @type logs_initial_positions: dict
        @type copy_at_index_zero: bool
        @type current_time: float
        """
        if current_time is None:
            current_time = time.time()

        if (self.__last_new_file_scan_time is None or
                current_time - self.__last_new_file_scan_time < self.__config.max_new_log_detection_time):
            return

        self.__last_new_file_scan_time = current_time

        if checkpoints is None:
            checkpoints = {}

        if logs_initial_positions is not None:
            for log_path in logs_initial_positions:
                if not log_path in checkpoints:
                    checkpoints[log_path] = LogFileProcessor.create_checkpoint(logs_initial_positions[log_path])

        for matcher in self.__log_matchers:
            for new_processor in matcher.find_matches(self.__log_paths_being_processed, checkpoints,
                                                      copy_at_index_zero=copy_at_index_zero):
                self.__log_processors.append(new_processor)
                self.__log_paths_being_processed[new_processor.log_path] = True

    def __scan_for_new_bytes(self, current_time=None):
        """For any existing LogProcessors, have them scan the file system to see if their underlying files have
        grown.

        This does not perform any processing on the file nor advances the file's position.

        This is mainly used to just update the statistics about the files for reporting purposes (i.e., the number
        of pending bytes, etc).
        """
        if current_time is None:
            current_time = time.time()
        for processor in self.__log_processors:
            processor.scan_for_new_bytes(current_time)