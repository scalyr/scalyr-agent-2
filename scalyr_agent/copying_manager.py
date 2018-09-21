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

import datetime
import os
import threading
import time
import sys

import scalyr_agent.scalyr_logging as scalyr_logging
import scalyr_agent.util as scalyr_util
from scalyr_agent.log_watcher import LogWatcher

from scalyr_agent.util import StoppableThread
from scalyr_agent.log_processing import LogMatcher, LogFileProcessor
from scalyr_agent.agent_status import CopyingManagerStatus
from scalyr_agent.scalyr_client import AddEventsRequest

log = scalyr_logging.getLogger(__name__)


class CopyingParameters( object ):
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
        # If there is a AddEventsTask object already created for the next request due to pipelining, this is set to it.
        # This must be the next request if this request is successful, otherwise, we will lose bytes.
        self.next_pipelined_task = None


class CopyingManager(StoppableThread, LogWatcher):
    """Manages the process of copying all configured log files to the Scalyr server.

    This is run as its own thread.
    """
    def __init__(self, configuration, monitors):
        """Initializes the manager.

        Note, the log_config variable on the monitors will be updated as a side effect of this call to reflect
        the filling in of defaults and making paths absolute.  TODO:  This is kind of odd, it would be cleaner
        to do this elsewhere more tied to the monitors themselves.

        @param configuration: The configuration file containing which log files need to be copied listed in the
            configuration file.
        @param monitors:  The list of ScalyrMonitor instances that will be run.  This is needed so the manager
            can be sure to copy the logs files generated by the monitors. Note, the log_config for the monitors
            will be updated (on the monitor) to reflect the filling in of defaults and making paths absolute.

        @type configuration: configuration.Configuration
        @type monitors: list<ScalyrMonitor>
        """
        StoppableThread.__init__(self, name='log copier thread')
        self.__config = configuration
        # Keep track of monitors
        self.__monitors = monitors

        # We keep track of which paths we have configs for so that when we add in the configuration for the monitor
        # log files we don't re-add in the same path.  This can easily happen if a monitor is used multiple times
        # but they are all just writing to the same monitor file.
        self.__all_paths = {}

        # a dict of log paths pending removal once their bytes pending count reaches 0
        # keyed on the log path, with a value of True or False depending on whether the
        # log file has been processed yet
        self.__logs_pending_removal = {}

        # a list of log_matches for logs with configs that need to be reloaded.
        # Logs need to be reloaded if their configuration changes at runtime
        # e.g. with the k8s monitor if an annotation attribute changes such as the
        # sampling rules or the parser, and this is outside the usual configuration reload mechanism.
        # By keeping logs that need reloading in a separate 'pending' list
        # we can avoid locking around log_processors and log_paths_being_processed containers,
        # and simply process the contents of this list on the main loop
        self.__logs_pending_reload = []

        # a list of dynamically added log_matchers that have not been processed yet
        self.__pending_log_matchers = []

        # The list of LogMatcher objects that are watching for new files to appear.
        self.__log_matchers = self.__create_log_matches(configuration, monitors )

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

        # The client to use for sending the data.  Set in the start_manager call.
        self.__scalyr_client = None
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
        # Set in the start_manager call.
        self.__logs_initial_positions = None

        # A semaphore that we increment when this object has begun copying files (after first scan).
        self.__copying_semaphore = threading.Semaphore()

        #set the log watcher variable of all monitors.  Do this last so everything is set up
        #and configured when the monitor receives this call
        for monitor in monitors:
            monitor.set_log_watcher( self )

        # debug leaks
        self.__disable_new_file_matches = configuration.disable_new_file_matches
        self.__disable_scan_for_new_bytes = configuration.disable_scan_for_new_bytes
        self.__disable_copying_thread = configuration.disable_copying_thread

    @property
    def log_matchers(self):
        """Returns the list of log matchers that were created based on the configuration and passed in monitors.

        This is really only exposed for testing purposes.

        @return: The log matchers.
        @rtype: list<LogMatcher>
        """
        return self.__log_matchers

    def add_log_config( self, monitor, log_config ):
        """Add the log_config item to the list of paths being watched
        params: log_config - a log_config object containing the path to be added
        returns: an updated log_config object
        """
        log_config = self.__config.parse_log_config( log_config, default_parser='agent-metrics', context_description='Additional log entry requested by module "%s"' % monitor.module_name).copy()

        self.__lock.acquire()
        try:
            if log_config['path'] not in self.__all_paths:
                log.log(scalyr_logging.DEBUG_LEVEL_0, 'Adding new log file \'%s\' for monitor \'%s\'' % (log_config['path'], monitor.module_name ) )
                self.__pending_log_matchers.append( LogMatcher( self.__config, log_config ) )
                self.__all_paths[log_config['path']] = 1
            else:
                self.__all_paths[log_config['path']] += 1

            # if the log was previously pending removal, cancel the pending removal
            self.__logs_pending_removal.pop( log_config['path'], None )

        finally:
            self.__lock.release()

        return log_config

    def update_log_config( self, monitor_name, log_config ):
        """ Updates the log config of the log matcher that has the same
        path as the one specified in the log_config param
        """
        log_config = self.__config.parse_log_config( log_config, default_parser='agent-metrics', context_description='Updating log entry requested by module "%s"' % monitor_name).copy()
        try:
            self.__lock.acquire()

            log_path = log_config['path']
            if log_path in self.__all_paths:
                log.log(scalyr_logging.DEBUG_LEVEL_0, 'Updating config for log file \'%s\' for monitor \'%s\'' % (log_path, monitor_name ) )
                # update by removing the old entry and adding a new one
                self.__log_matchers[:] = [m for m in self.__log_matchers if m.log_path != log_path]

                # add to the pending matches rather than adding directly, so processors will be updated
                # correctly in the main loop
                matcher = LogMatcher( self.__config, log_config )
                self.__pending_log_matchers.append( matcher )

                # also add to the pending reload list so any old processors for this file will be removed
                # next time through the main loop
                # We keep track of these separately to distinguish between pending new additions (from add_log_config)
                # and pending reloads (from this method)
                self.__logs_pending_reload.append(matcher)
            else:
                log.warn( "Trying to update log config for nonexistent log: %s" % log_path,
                           limit_once_per_x_secs=600, limit_key='update-log-config-%s' % log_path )
        finally:
            self.__lock.release()

    def remove_log_path( self, monitor_name, log_path ):
        """Remove the log_path from the list of paths being watched
        params: log_path - a string containing the path to the file no longer being watched
        """
        #get the list of paths with 0 reference counts
        self.__lock.acquire()
        try:
            if log_path in self.__all_paths:
                self.__all_paths[log_path] -= 1

                #paths with 0 reference counts need removing
                if self.__all_paths[log_path] <= 0:
                    log.log(scalyr_logging.DEBUG_LEVEL_0, 'Removing log file \'%s\' for \'%s\'' % (log_path, monitor_name ) )
                    #do the removals
                    self.__log_matchers[:] = [m for m in self.__log_matchers if not m.log_path == log_path]
                    self.__logs_pending_removal.pop( log_path, None )

            else:
                log.log(scalyr_logging.DEBUG_LEVEL_0, "'%s' - trying to remove non-existent path from copy manager: '%s'" % ( monitor.module_name, log_path) )
        finally:
            self.__lock.release()

    def schedule_log_path_for_removal( self, monitor_name, log_path ):
        """
            Schedules a log path for removal.  The logger will only
            be removed once the number of pending bytes reaches 0
        """
        self.__lock.acquire()
        try:
            if log_path not in self.__logs_pending_removal:
                # set to False to signify that we don't know if these log has been processed at least once
                self.__logs_pending_removal[log_path] = False
                log.log(scalyr_logging.DEBUG_LEVEL_0, 'log path \'%s\' for monitor \'%s\' is pending removal' % (log_path, monitor_name ) )
        finally:
            self.__lock.release()

    def __create_log_matches(self, configuration, monitors ):
        """Creates the log matchers that should be used based on the configuration and the list of monitors.

        @param configuration: The Configuration object.
        @param monitors: A list of ScalyrMonitor instances whose logs should be copied.

        @type configuration: Configuration
        @type monitors: list<ScalyrMonitor>

        @return: The list of log matchers.
        @rtype: list<LogMatcher>
        """
        configs = []

        for entry in configuration.log_configs:
            configs.append(entry.copy())
            self.__all_paths[entry['path']] = 1

        for monitor in monitors:
            log_config = configuration.parse_log_config(
                monitor.log_config, default_parser='agent-metrics',
                context_description='log entry requested by module "%s"' % monitor.module_name).copy()

            if log_config['path'] not in self.__all_paths:
                configs.append(log_config)
                self.__all_paths[log_config['path']] = 1

            monitor.log_config = log_config

        result = []

        for log_config in configs:
            result.append(LogMatcher(configuration, log_config))

        return result

    def start_manager(self, scalyr_client, logs_initial_positions=None):
        """Starts the manager running and will not return until it has been stopped.

        This will start a new thread to run the manager.

        @param scalyr_client: The client to use to send requests to Scalyr.
        @param logs_initial_positions: A dict mapping file paths to the offset with the file to begin copying
            if none can be found from the checkpoint files.  This can be used to override the default behavior of
            just reading from the current end of the file if there is no checkpoint for the file
        @type scalyr_client: scalyr_client.ScalyrClientSession
        @type logs_initial_positions: dict
        @param scalyr_client:
        """
        self.__scalyr_client = scalyr_client
        self.__logs_initial_positions = logs_initial_positions
        self.start()

    def stop_manager(self, wait_on_join=True, join_timeout=5):
        """Stops the manager.

        @param wait_on_join: If True, will block on a join of of the thread running the manager.
        @param join_timeout: The maximum number of seconds to block for the join.
        """
        self.stop(wait_on_join=wait_on_join, join_timeout=join_timeout)

    def run(self):
        """Processes the log files as requested by the configuration, looking for matching log files, reading their
        bytes, applying redaction and sampling rules, and then sending them to the server.

        This method will not terminate until the thread has been stopped.
        """
        # Debug leak
        if self.__disable_copying_thread:
            log.log( scalyr_logging.DEBUG_LEVEL_0, "Copying thread disabled.  No log copying will occur" )
            self.__copying_semaphore.release()
            # sit here and do nothing
            while self._run_state.is_running():
                self._sleep_but_awaken_if_stopped( 1 )
            # early return
            return

        # So the scanning.. every scan:
        #   - See if any of the loggers have new files that are being matched
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
                # Try to read the checkpoint state from disk.
                checkpoints_state = self.__read_checkpoint_state()
                if checkpoints_state is None:
                    log.info(
                        'The checkpoints were not read.  All logs will be copied starting at their current end')
                elif (current_time - checkpoints_state['time']) > self.__config.max_allowed_checkpoint_age:
                    log.warn('The current checkpoint is too stale (written at "%s").  Ignoring it.  All log files will '
                             'be copied starting at their current end.', scalyr_util.format_time(
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

                current_time = time.time()

                # Just initialize the last time we had a success to now.  Make the logic below easier.
                last_success = current_time

                last_full_checkpoint_write = current_time

                pipeline_byte_threshold = self.__config.pipeline_threshold * float(self.__config.max_allowed_request_size)

                # We are about to start copying.  We can tell waiting threads.
                self.__copying_semaphore.release()

                while self._run_state.is_running():
                    log.log(scalyr_logging.DEBUG_LEVEL_1, 'At top of copy log files loop.')
                    current_time = time.time()
                    pipeline_time = 0.0
                    # noinspection PyBroadException
                    try:
                        # If we have a pending request and it's been too taken too long to send it, just drop it
                        # on the ground and advance.
                        if current_time - last_success > self.__config.max_retry_time:
                            if self.__pending_add_events_task is not None:
                                self.__pending_add_events_task.completion_callback(LogFileProcessor.FAIL_AND_DROP)
                                self.__pending_add_events_task = None
                            # Tell all of the processors to go to the end of the current log file.  We will start
                            # copying
                            # from there.
                            for processor in self.__log_processors:
                                processor.skip_to_end('Too long since last successful request to server.',
                                                      'skipNoServerSuccess', current_time=current_time)

                        # Check for new logs.  If we do detect some new log files, they must have been created since our
                        # last scan.  In this case, we start copying them from byte zero instead of the end of the file.
                        self.__scan_for_new_logs_if_necessary(current_time=current_time, copy_at_index_zero=True)

                        # Collect log lines to send if we don't have one already.
                        if self.__pending_add_events_task is None:
                            self.__pending_add_events_task = self.__get_next_add_events_task(
                                copying_params.current_bytes_allowed_to_send)
                        else:
                            log.log(scalyr_logging.DEBUG_LEVEL_1, 'Have pending batch of events, retrying to send.')
                            # Take a look at the file system and see if there are any new bytes pending.  This updates
                            # the statistics for each pending file.  This is important to do for status purposes if we
                            # have not tried to invoke get_next_send_events_task in a while (since that already updates
                            # the statistics).
                            self.__scan_for_new_bytes(current_time=current_time)

                        # Try to send the request if we have one.
                        if self.__pending_add_events_task is not None:
                            log.log(scalyr_logging.DEBUG_LEVEL_1, 'Sending an add event request')
                            # Send the request, but don't block for the response yet.
                            get_response = self._send_events(self.__pending_add_events_task)
                            # If we are sending very large requests, we will try to optimize for future requests
                            # by overlapping building the request with waiting for the response on the current request
                            # (pipelining).
                            if (self.__pending_add_events_task.add_events_request.current_size
                                    >= pipeline_byte_threshold and self.__pending_add_events_task.next_pipelined_task is None):
                                # Time how long it takes us to build it because we will subtract it from how long we
                                # have to wait before we send the next request.
                                pipeline_time = time.time()
                                self.__pending_add_events_task.next_pipelined_task = self.__get_next_add_events_task(
                                    copying_params.current_bytes_allowed_to_send, for_pipelining=True)
                            else:
                                pipeline_time = 0.0

                            # Now block for the response.
                            (result, bytes_sent, full_response) = get_response()

                            if pipeline_time > 0:
                                pipeline_time = time.time() - pipeline_time
                            else:
                                pipeline_time = 0.0

                            log.log(scalyr_logging.DEBUG_LEVEL_1,
                                    'Sent %ld bytes and received response with status="%s".',
                                    bytes_sent, result)

                            if result == 'success' or 'discardBuffer' in result or 'requestTooLarge' in result:
                                next_add_events_task = None
                                try:
                                    if result == 'success':
                                        self.__pending_add_events_task.completion_callback(LogFileProcessor.SUCCESS)
                                        next_add_events_task = self.__pending_add_events_task.next_pipelined_task
                                    elif 'discardBuffer' in result:
                                        self.__pending_add_events_task.completion_callback(
                                            LogFileProcessor.FAIL_AND_DROP)
                                    else:
                                        self.__pending_add_events_task.completion_callback(
                                            LogFileProcessor.FAIL_AND_RETRY)
                                finally:
                                    # No matter what, we want to throw away the current event since the server said we
                                    # could.  We have seen some bugs where we did not throw away the request because
                                    # an exception was thrown during the callback.
                                    self.__pending_add_events_task = next_add_events_task
                                    self.__write_active_checkpoint_state( current_time )

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

                        self.__scan_for_pending_log_files()
                        self.__remove_logs_scheduled_for_deletion()

                        if profiler is not None:
                            seconds_past_epoch = int(time.time())
                            if seconds_past_epoch % profile_dump_interval == 0:
                                profiler.disable()
                                profiler.dump_stats('%s%s' % (self.__config.copying_thread_profile_output_path,
                                                              datetime.datetime.now().strftime("%H_%M_%S.out")))
                                profiler.enable()
                    except Exception:
                        # TODO: Do not catch Exception here.  That is too broad.  Disabling warning for now.
                        log.exception('Failed while attempting to scan and transmit logs')
                        log.log(scalyr_logging.DEBUG_LEVEL_1, 'Failed while attempting to scan and transmit logs')
                        self.__lock.acquire()
                        self.__last_attempt_time = current_time
                        self.__total_errors += 1
                        self.__lock.release()

                    if current_time - last_full_checkpoint_write > self.__config.full_checkpoint_interval:
                        self.__write_full_checkpoint_state( current_time )
                        last_full_checkpoint_write = current_time

                    if pipeline_time < copying_params.current_sleep_interval:
                        self._sleep_but_awaken_if_stopped(copying_params.current_sleep_interval - pipeline_time)
            except Exception:
                # If we got an exception here, it is caused by a bug in the program, so let's just terminate.
                log.exception('Log copying failed due to exception')
                sys.exit(1)
        finally:
            self.__write_full_checkpoint_state( current_time )
            for processor in self.__log_processors:
                processor.close()
            if profiler is not None:
                profiler.disable()

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
        return self.__scalyr_client.add_events_request(session_info=session_info, max_size=max_size)

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
        #if add_events_task.add_events_request.total_events > 0:
        return self.__scalyr_client.send(add_events_task.add_events_request, block_on_response=False)
        #else:
        #    return "success", 0, "{ status: \"success\", message: \"RPC not sent to server because it was empty\"}"

    def __read_checkpoint_state(self):
        """Reads the checkpoint state from disk and returns it.

        The checkpoint state maps each file path to the offset within that log file where we left off copying it.

        @return:  The checkpoint state
        @rtype: dict
        """
        full_checkpoint_file_path = os.path.join(self.__config.agent_data_path, 'checkpoints.json')

        if not os.path.isfile(full_checkpoint_file_path):
            log.info('The log copying checkpoint file "%s" does not exist, skipping.' % full_checkpoint_file_path)
            return None

        # noinspection PyBroadException
        try:
            full_checkpoints = scalyr_util.read_file_as_json(full_checkpoint_file_path)
            active_checkpoint_file_path = os.path.join(self.__config.agent_data_path, 'active-checkpoints.json')

            if not os.path.isfile(active_checkpoint_file_path):
                return full_checkpoints

            # if the active checkpoint file is newer, overwrite any checkpoint values with the
            # updated full checkpoint
            active_checkpoints = scalyr_util.read_file_as_json(active_checkpoint_file_path)

            if active_checkpoints['time'] > full_checkpoints['time']:
                full_checkpoints['time'] = active_checkpoints['time']
                for path, checkpoint in active_checkpoints['checkpoints'].iteritems():
                    full_checkpoints[path] = checkpoint

            return full_checkpoints

        except Exception:
            # TODO:  Fix read_file_as_json so that it will not return an exception.. or will return a specific one.
            log.exception('Could not read checkpoint file due to error.', error_code='failedCheckpointRead')
            return None

    def __write_checkpoint_state(self, log_processors, base_file, current_time, full_checkpoint ):
        """Writes the current checkpoint state to disk.

        This must be done periodically to ensure that if the agent process stops and starts up again, we pick up
        from where we left off copying each file.
        """
        # Create the format that is expected.  An overall JsonObject with the time when the file was written,
        # and then an entry for each file path.
        checkpoints = {}
        state = {
            'time': current_time,
            'checkpoints': checkpoints,
        }

        for processor in log_processors:
            if full_checkpoint or processor.is_active:
                checkpoints[processor.log_path] = processor.get_checkpoint()

            if full_checkpoint:
                processor.set_inactive()

        # We write to a temporary file and then rename it to the real file name to make the write more atomic.
        # We have had problems in the past with corrupted checkpoint files due to failures during the write.
        file_path = os.path.join(self.__config.agent_data_path, base_file)
        tmp_path = os.path.join(self.__config.agent_data_path, base_file + '~')
        scalyr_util.atomic_write_dict_as_json_file( file_path, tmp_path, state )

    def __write_full_checkpoint_state( self, current_time ):
        """Writes the full checkpont state to disk.

        This must be done periodically to ensure that if the agent process stops and starts up again, we pick up
        from where we left off copying each file.

        """
        self.__write_checkpoint_state( self.__log_processors, 'checkpoints.json', current_time, full_checkpoint=True )
        self.__active_log_processors = {}
        self.__write_active_checkpoint_state( current_time )

    def __write_active_checkpoint_state( self, current_time ):
        """Writes checkpoints only for logs that have been active since the last full checkpoint write
        """
        self.__write_checkpoint_state( self.__log_processors, 'active-checkpoints.json', current_time, full_checkpoint=False )

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
        log.log(scalyr_logging.DEBUG_LEVEL_1,
                'Getting batch of events to send. (pipelining=%s)' % str(for_pipelining))

        # We have to iterate over all of the LogFileProcessors, getting bytes from them.  We also have to
        # collect all of the callback that they give us and wrap it into one massive one.
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

        add_events_request = self._create_add_events_request(session_info=self.__config.server_attributes,
                                                             max_size=bytes_allowed_to_send)

        if for_pipelining:
            add_events_request.increment_timing_data(pipelined=1.0)

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
            # TODO:  This might not be bullet proof here.  We copy __log_processors and then update it at the end
            # We could be susceptible to exceptions thrown in the middle of this method, though now should.

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
                    self.__log_paths_being_processed[processor.log_path] = processor
                else:
                    processor.close()

        if for_pipelining and add_events_request.num_events == 0:
            handle_completed_callback(LogFileProcessor.SUCCESS)
            return None

        log.log(scalyr_logging.DEBUG_LEVEL_1,
                'Information for batch of events. (pipelining=%s): %s' % (str(for_pipelining),
                                                                          add_events_request.get_timing_data()))
        return AddEventsTask(add_events_request, handle_completed_callback)

    def __remove_logs_scheduled_for_deletion( self ):
        """
            Removes any logs scheduled for deletion, if there are 0 bytes left to copy and
            the log file has been matched/processed at least once
        """

        # make a shallow copy of logs_pending_removal
        # so we can iterate without a lock (remove_log_path also acquires the lock so best
        # not to do that while the lock is already aquired
        self.__lock.acquire()
        try:
            pending_removal = self.__logs_pending_removal.copy()
        finally:
            self.__lock.release()

        # check to see if any of the pending logs have 0 bytes remaining
        # and remove the ones that do
        for path, processed in pending_removal.iteritems():
            log.log( scalyr_logging.DEBUG_LEVEL_1, "Checking for removal of log_path %s" % path )
            if processed:
                log.log( scalyr_logging.DEBUG_LEVEL_1, "%s has been processed at least once" % path )

                if path in self.__log_paths_being_processed:
                    log.log( scalyr_logging.DEBUG_LEVEL_1, "found %s in processed paths, %d bytes pending" % (path, self.__log_paths_being_processed[path].total_bytes_pending) )

                    if self.__log_paths_being_processed[path].total_bytes_pending == 0:
                        self.remove_log_path( "scheduled-deletion", path )
                else:

                    # the log file is schedule for removal and the pending list indicates that it
                    # has been processed, but we can not find it in the list of processors
                    # so remove it from the pending list and log a warning.
                    self.__lock.acquire()
                    try:
                        self.__logs_pending_removal.pop( path, None )
                    finally:
                        self.__lock.release()
                    log.warn( "Log scheduled for removal is not being monitored: %s" % path )

    def __scan_for_pending_log_files( self ):
        """
        Creates log processors for any recent, dynamically added log matchers
        """

        # make a shallow copy of pending log_matchers, and pending reloads
        log_matchers = []
        pending_reload = []
        self.__lock.acquire()
        try:
            log_matchers = self.__pending_log_matchers[:]

            # get any logs that need reloading and reset the pending reload list
            pending_reload = self.__logs_pending_reload
            self.__logs_pending_reload = []
        finally:
            self.__lock.release()

        checkpoints={}

        # remove any log processors from the pending_reload list, so they get recreated
        for matcher in pending_reload:
            log.log( scalyr_logging.DEBUG_LEVEL_1, "Pending reload for %s" % matcher.log_path )
            self.__log_paths_being_processed.pop( matcher.log_path, None )
            # iterate over full list of processors to see if we need to remove any.
            # We manually iterate so that we can close the processors if necessary
            # and also so we can get checkpoints so files aren't copied from the beginning
            # note:  manually calculate the len each loop iteration as it changes if items
            # are removed
            i = 0
            while i < len( self.__log_processors ):
                p = self.__log_processors[i]
                if p.log_path == matcher.log_path:
                    checkpoints[p.log_path] = p.get_checkpoint()
                    p.close()
                    del self.__log_processors[i]
                else:
                    i += 1

        self.__create_log_processors_for_log_matchers( log_matchers, checkpoints=checkpoints, copy_at_index_zero=True )

        self.__lock.acquire()
        try:
            self.__log_matchers.extend( log_matchers )
            self.__pending_log_matchers = [lm for lm in self.__pending_log_matchers if lm not in log_matchers]
        finally:
            self.__lock.release()

    def __create_log_processors_for_log_matchers( self, log_matchers, checkpoints=None, copy_at_index_zero=False ):
        """
        Creates log processors for any files on disk that match any file matching the
        passed in log_matchers

        @param log_matchers: A list of log_matchers to check against.  Note:  No locking is done on the log_matchers
          passed in, so the caller needs to ensure that the list is thread-safe and only accessed from the main
          loop.
        @param checkpoints: A dict mapping file paths to the checkpoint to use for them to determine where copying
            should begin.
        @param copy_at_index_zero: If True, then any new file that doesn't have a checkpoint or an initial position,
            will begin being copied from the start of the file rather than the current end.
        """

        # make a shallow copy of logs pending removal so we don't need to hold the lock
        # while iterating
        pending_removal = {}
        self.__lock.acquire()
        try:
            pending_removal = self.__logs_pending_removal.copy()
        finally:
            self.__lock.release()

        # check if any pending removal have already been processed
        # and update the processed status
        for path in pending_removal.keys():
            if path in self.__log_paths_being_processed:
                pending_removal[path] = True

        # iterate over the log_matchers while we create the LogFileProcessors
        for matcher in log_matchers:
            for new_processor in matcher.find_matches(self.__log_paths_being_processed, checkpoints,
                                                      copy_at_index_zero=copy_at_index_zero):
                self.__log_processors.append(new_processor)
                self.__log_paths_being_processed[new_processor.log_path] = new_processor

                # if the log file pending removal, mark that it has now been processed
                if new_processor.log_path in pending_removal:
                    pending_removal[new_processor.log_path] = True

            # check to see if no matches were found for pending removal
            # if none were found, this is indicative that the log file has already been
            # removed
            if matcher.config['path'] in pending_removal and not pending_removal[matcher.config['path']]:
                log.warn( "No log matches were found for %s.  This is likely indicative that the log file no longer exists.\n", matcher.config['path'] )

                # remove it anyway, otherwise the logs_`pending_removal list will just
                # grow and grow
                pending_removal[matcher.config['path']] = True


        # require the lock to update the pending removal dict to
        # mark which logs have been matched.
        # This is so we can catch short lived log files that are added but then removed
        # before any log matching takes place
        self.__lock.acquire()
        try:
            # go over all items in pending_removal, and update the master
            # logs_pending_removal list
            for path, processed in pending_removal.iteritems():
                if path in self.__logs_pending_removal:
                    self.__logs_pending_removal[path] = processed
        finally:
            self.__lock.release()


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

        # Debug leak, if not the initial request, and disable_leak flag is true, then don't scan
        # for new logs
        if logs_initial_positions is None and self.__disable_new_file_matches:
            log.log(scalyr_logging.DEBUG_LEVEL_0, "Scanning for new file matches disabled" )
            return

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


        # make a shallow copy of log_matchers
        log_matchers = []
        self.__lock.acquire()
        try:
            log_matchers = self.__log_matchers[:]
        finally:
            self.__lock.release()

        self.__create_log_processors_for_log_matchers( log_matchers, checkpoints=checkpoints, copy_at_index_zero=copy_at_index_zero )


    def __scan_for_new_bytes(self, current_time=None):
        """For any existing LogProcessors, have them scan the file system to see if their underlying files have
        grown.

        This does not perform any processing on the file nor advances the file's position.

        This is mainly used to just update the statistics about the files for reporting purposes (i.e., the number
        of pending bytes, etc).
        """
        if self.__disable_scan_for_new_bytes:
            log.log( scalyr_logging.DEBUG_LEVEL_0, "Scanning for new bytes disabled." )
            return

        if current_time is None:
            current_time = time.time()
        for processor in self.__log_processors:
            processor.scan_for_new_bytes(current_time)
