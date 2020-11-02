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
from __future__ import unicode_literals
from __future__ import absolute_import

from abc import ABCMeta, abstractmethod
from distutils.log import Log

__author__ = "czerwin@scalyr.com"

import copy
import datetime
import os
import threading
import time
import sys
import itertools
import glob
import re
import operator
from operator import attrgetter
import collections
from multiprocessing.managers import BaseProxy, BaseManager
import multiprocessing.connection

if False:
    from typing import Dict
    from typing import List

import scalyr_agent.scalyr_logging as scalyr_logging
import scalyr_agent.util as scalyr_util

from scalyr_agent.util import StoppableThread, RateLimiter
from scalyr_agent.log_processing import (
    LogMatcher,
    LogFileProcessor,
    LogFileProcessorInterface,
)
from scalyr_agent.agent_status import CopyingManagerStatus
from scalyr_agent.agent_status import (
    CopyingManagerWorkerStatus,
    ShardedCopyingManagerStatus,
    ApiKeyWorkerPoolStatus,
)
from scalyr_agent.scalyr_client import create_client
from scalyr_agent.configuration import Configuration

import six


log = scalyr_logging.getLogger(__name__)
log.setLevel(scalyr_logging.DEBUG_LEVEL_0)

SCHEDULED_DELETION = "scheduled-deletion"


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


class ShardedCopyingManager(StoppableThread):
    def __init__(self, configuration, monitors):
        # type: (Configuration, List) -> None
        StoppableThread.__init__(self, name="log copier thread")
        self.__config = configuration

        # Keep track of monitors
        self.__monitors = monitors

        # collect monitor-specific extra server-attributes.  seed with a copy of the attributes and converted to a dict.
        self.__expanded_server_attributes = self.__config.server_attributes.to_dict()

        for monitor in monitors:
            monitor_attribs = monitor.get_extra_server_attributes()
            if not monitor_attribs:
                continue
            for key, value in monitor_attribs.items():
                if key in self.__expanded_server_attributes:
                    log.log(
                        scalyr_logging.DEBUG_LEVEL_0,
                        "Extra server attribute already defined. Cannot add extra server attribute '%s' from monitor %s"
                        % (key, monitor.module_name),
                        limit_once_per_x_secs=300,
                        limit_key="extra-server-attrib-%s" % key,
                    )
                else:
                    self.__expanded_server_attributes[key] = value

        # a dict of paths -> log matchers for log matchers that have been dynamically added
        # this dict should only be touched by the main thread
        self.__dynamic_matchers = {}

        # a dict of paths -> monitor names that have been dynamically added to the copying manager
        # the copying manager ensures that operations on a dynamically added path can only be performed
        # by the same monitor (i.e. only the monitor that dynamically added a path can remove or update
        # that monitor).
        self.__dynamic_paths = {}

        # a dict of log paths pending removal once their bytes pending count reaches 0
        # keyed on the log path, with a value of True or False depending on whether the
        # log file has been processed yet
        self.__logs_pending_removal = {}

        # a dict of log_configs keyed by log_path for logs with configs that need to be reloaded.
        # Logs need to be reloaded if their configuration changes at runtime
        # e.g. with the k8s monitor if an annotation attribute changes such as the
        # sampling rules or the parser, and this is outside the usual configuration reload mechanism.
        # By keeping logs that need reloading in a separate 'pending' list
        # we can avoid locking around log_processors and log_paths_being_processed containers,
        # and simply process the contents of this list on the main loop
        self.__logs_pending_reload = {}

        # a list of dynamically added log_matchers that have not been processed yet
        self.__pending_log_matchers = []

        # The last time we scanned for new files that match the __log_matchers.
        self.__last_new_file_scan_time = 0

        # A dict from file path to the LogFileProcessor that is processing it.
        self.__log_paths_being_processed = {}

        # A lock that protects the status variables and the __log_matchers variable, the only variables that
        # are access in generate_status() which needs to be thread safe.
        self.__lock = threading.Lock()

        # Status variables that track statistics reported to the status page.
        self.__last_attempt_time = None
        self.__total_errors = 0

        # The positions to use for a given file if there is not already a checkpoint for that file.
        # Set in the start_manager call.
        self._logs_initial_positions = None

        # A semaphore that we increment when this object has begun copying files (after first scan).
        self.__copying_semaphore = threading.Semaphore(0)

        # set the log watcher variable of all monitors.  Do this last so everything is set up
        # and configured when the monitor receives this call
        for monitor in monitors:
            monitor.set_log_watcher(self)

        # debug leaks
        self.__disable_new_file_matches = configuration.disable_new_file_matches
        self.__disable_scan_for_new_bytes = configuration.disable_scan_for_new_bytes
        self.__disable_copying_thread = configuration.disable_copying_thread

        # Statistics for copying_manager_status messages
        self.total_scan_iterations = 0
        self.total_read_time = 0
        self.total_blocking_response_time = 0
        self.total_request_time = 0
        self.total_pipelined_requests = 0

        # mapping of the api keys to worker pools.
        self.__api_keys_worker_pools = dict()  # type: Dict[six.text_type, ApiKeyWorkerPool]
        self.__log_matchers_to_api_keys = dict()
        self.__all_workers_pool = None  # type: Optional[ApiKeyWorkerPool]
        self._processors_to_workers = dict()

        # if some workers are in multiprocessing mode, we need to create memory manager for each of them.
        self._shared_memory_managers = dict()

        self._current_worker = 0

        # self.__log_processor_factory = log_file_processor_factory()

        # create copying workers according to settings in the configuration.
        self._create_worker_pools()

        # The list of LogMatcher objects that are watching for new files to appear.
        self.__log_matchers = self.__create_log_matches(configuration, monitors)

    @property
    def _all_workers_pool(self):
        # type: () -> ApiKeyWorkerPool
        """
        Return all worker pool. Exposed only for testing purposes.
        :return:
        """
        return self.__all_workers_pool

    def run(self):
        """Processes the log files as requested by the configuration, looking for matching log files, reading their
        bytes, applying redaction and sampling rules, and then sending them to the server.

        This method will not terminate until the thread has been stopped.
        """
        # Debug leak
        if self.__disable_copying_thread:
            log.log(
                scalyr_logging.DEBUG_LEVEL_0,
                "Copying thread disabled.  No log copying will occur",
            )
            self.__copying_semaphore.release()
            # sit here and do nothing
            while self._run_state.is_running():
                self._sleep_but_awaken_if_stopped(1)
            # early return
            return

        # So the scanning.. every scan:
        #   - See if any of the loggers have new files that are being matched
        #   - sleep

        # Make sure start_manager was invoked to start the thread and we have a scalyr client instance.

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

                log.info("Starting copying manager workers.")

                # gather and merge all checkpoints from all active workers( or workers from previous launch)
                # into single checkpoints object.
                checkpoints = self.__get_checkpoints(current_time)

                # start all workers.
                self.__all_workers_pool.start_workers()

                # Do the initial scan for any log files that match the configured logs we should be copying.  If there
                # are checkpoints for them, make sure we start copying from the position we left off at.
                self._scan_for_new_logs_if_necessary(
                    current_time=current_time,
                    checkpoints=checkpoints,
                    logs_initial_positions=self._logs_initial_positions,
                )

                # We are about to start copying.  We can tell waiting threads.
                self.__copying_semaphore.release()

                log.info("Copying manager started.")

                while self._run_state.is_running():
                    log.log(
                        scalyr_logging.DEBUG_LEVEL_1, "At top of copy log files loop."
                    )
                    current_time = time.time()
                    # noinspection PyBroadException
                    try:

                        # Check for new logs.  If we do detect some new log files, they must have been created since our
                        # last scan.  In this case, we start copying them from byte zero instead of the end of the file.
                        self._scan_for_new_logs_if_necessary(
                            current_time=current_time, copy_at_index_zero=True
                        )

                        self.__scan_for_pending_log_files()

                        log.log(
                            scalyr_logging.DEBUG_LEVEL_2,
                            "Start removing finished log matchers",
                        )
                        self.__remove_logs_scheduled_for_deletion()
                        self.__purge_finished_log_matchers()
                        log.log(
                            scalyr_logging.DEBUG_LEVEL_2,
                            "Done removing finished log matchers",
                        )
                        self.__last_attempt_time = current_time

                        if profiler is not None:
                            seconds_past_epoch = int(time.time())
                            if seconds_past_epoch % profile_dump_interval == 0:
                                profiler.disable()
                                profiler.dump_stats(
                                    "%s%s%s"
                                    % (
                                        self.__config.copying_thread_profile_output_path,
                                        "copying_manager_",
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

                    self._sleep_but_awaken_if_stopped(
                        self.__config.max_request_spacing_interval
                    )

                    # End of the copy loop
                    self.total_scan_iterations += 1
            except Exception as e:
                # If we got an exception here, it is caused by a bug in the program, so let's just terminate.
                log.exception("Log copying failed due to exception")
                raise
                sys.exit(1)
        finally:
            # stopping all workers.
            self._all_workers_pool.stop_workers()

            log.info("Copying manager is finished.")

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

    def _create_worker_pools(self):
        all_workers = []
        for api_key_config in self.__config.api_key_configs:
            pool_id = api_key_config["id"]
            workers = dict()
            for i in range(api_key_config["workers"]):
                # combine workers positional number in pool and poll id.
                worker_id = "%s_%s" % (pool_id, i)

                worker = CopyingManagerWorkerWrapper(
                    self.__config, api_key_config, worker_id
                )
                workers[worker_id] = worker
                log.log(
                    scalyr_logging.DEBUG_LEVEL_1,
                    "CopyingManagerWorker #%s is created." % worker.worker_id,
                )

                all_workers.append(worker)

            pool = ApiKeyWorkerPool(list(workers.values()))
            self.__api_keys_worker_pools[api_key_config["id"]] = pool
        # create global workers pool with all workers.
        self.__all_workers_pool = ApiKeyWorkerPool(all_workers)

    def _scan_for_new_logs_if_necessary(
        self,
        current_time=None,
        checkpoints=None,
        logs_initial_positions=None,
        copy_at_index_zero=False,
    ):
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
            log.log(
                scalyr_logging.DEBUG_LEVEL_0, "Scanning for new file matches disabled"
            )
            return

        if current_time is None:
            current_time = time.time()

        if (
            self.__last_new_file_scan_time is None
            or current_time - self.__last_new_file_scan_time
            < self.__config.max_new_log_detection_time
        ):
            return

        self.__last_new_file_scan_time = current_time

        if checkpoints is None:
            checkpoints = {}

        if logs_initial_positions is not None:
            for log_path in logs_initial_positions:
                if log_path not in checkpoints:
                    checkpoints[log_path] = LogFileProcessor.create_checkpoint(
                        logs_initial_positions[log_path]
                    )

        # make a shallow copy of log_matchers
        log_matchers = []
        self.__lock.acquire()
        try:
            log_matchers = self.__log_matchers[:]
        finally:
            self.__lock.release()

        self.__create_log_processors_for_log_matchers(
            log_matchers, checkpoints=checkpoints, copy_at_index_zero=copy_at_index_zero
        )

    def __add_log_processor_to_workers(self, log_processor, log_config_entry):
        # type: (LogFileProcessor) -> None
        """
        Find the best worker for the new log processor and add it into.
        :param log_processor:
        :return:
        """
        if type(log_processor) is not LogFileProcessor:
            worker = self.__all_workers_pool.workers[log_processor.worker_id]
            worker.schedule_new_log_processor(log_processor)
        else:
            pool = self.__api_keys_worker_pools[log_config_entry["api_key_id"]]
            pool.add_log_processor(log_processor)


    def __create_log_processors_for_log_matchers(
        self, log_matchers, checkpoints=None, copy_at_index_zero=False
    ):
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
            for new_processor in matcher.find_matches(
                self.__log_paths_being_processed,
                checkpoints,
                copy_at_index_zero=copy_at_index_zero,
            ):

                self.__add_log_processor_to_workers(
                    new_processor, matcher.log_entry_config
                )
                self.__log_paths_being_processed[new_processor.log_path] = new_processor

                # if the log file pending removal, mark that it has now been processed
                if new_processor.log_path in pending_removal:
                    pending_removal[new_processor.log_path] = True

            # check to see if no matches were found for pending removal
            # if none were found, this is indicative that the log file has already been
            # removed
            if (
                matcher.config["path"] in pending_removal
                and not pending_removal[matcher.config["path"]]
            ):
                log.warn(
                    "No log matches were found for %s.  This is likely indicative that the log file no longer exists.\n",
                    matcher.config["path"],
                )

                # remove it anyway, otherwise the logs_`pending_removal list will just
                # grow and grow
                pending_removal[matcher.config["path"]] = True

        # require the lock to update the pending removal dict to
        # mark which logs have been matched.
        # This is so we can catch short lived log files that are added but then removed
        # before any log matching takes place
        self.__lock.acquire()
        try:
            # go over all items in pending_removal, and update the master
            # logs_pending_removal list
            for path, processed in six.iteritems(pending_removal):
                if path in self.__logs_pending_removal:
                    self.__logs_pending_removal[path] = processed
        finally:
            self.__lock.release()

    def __get_checkpoints(self, current_time):
        """Find and read worker checkpoints that were previously written."""

        checkpoints = self.__find_and_read_workers_checkpoints(current_time)

        if not checkpoints:
            log.info("No checkpoints were found. All logs will be copied starting at their current end")

        result = {}

        # merge checkpoints from  all workers to one checkpoint.

        # checkpoints from different workers may contain checkpoint for the same file,
        # so we sort checkpoints by time and update resulting collection with the same order.
        checkpoints.sort(key=operator.itemgetter("time"))

        for wc in checkpoints:
            result.update(wc["checkpoints"])

        return result

    def __find_and_read_workers_checkpoints(self, current_time):
        """
        Read for all checkpoint files that
        :return:
        """
        checkpoints_dir_path = os.path.join(
            self.__config.agent_data_path, "checkpoints"
        )

        if not os.path.isdir(checkpoints_dir_path):
            return []

        glob_path = os.path.join(checkpoints_dir_path, "checkpoints-*.json")

        workers_checkpoints = list()

        for full_checkpoints_path in glob.glob(glob_path):
            m = re.search(
                r".*/checkpoints-(?P<id>\d+_\d+)\.json", full_checkpoints_path
            )
            if m:
                worker_id = m.group("id")
                active_checkpoints_path = os.path.join(
                    checkpoints_dir_path, "active-checkpoints-%s.json" % worker_id
                )
            else:
                active_checkpoints_path = None

            checkpoints = self.__read_worker_checkpoint_state(
                full_checkpoints_path, active_checkpoints_path, current_time
            )

            if checkpoints:
                workers_checkpoints.append(checkpoints)

        return workers_checkpoints

    def __read_worker_checkpoint_state(
        self, full_checkpoint_file_path, active_checkpoint_file_path, current_time
    ):
        """Reads the checkpoint state from disk and returns it.

        The checkpoint state maps each file path to the offset within that log file where we left off copying it.

        @return:  The checkpoint state
        @rtype: dict
        """

        if not os.path.isfile(full_checkpoint_file_path):
            log.info(
                'The log copying checkpoint file "%s" does not exist, skipping.'
                % full_checkpoint_file_path
            )
            return None

        # noinspection PyBroadException
        try:
            full_checkpoints = scalyr_util.read_file_as_json(
                full_checkpoint_file_path, strict_utf8=True
            )

            if active_checkpoint_file_path is not None and os.path.isfile(
                active_checkpoint_file_path
            ):

                # if the active checkpoint file is newer, overwrite any checkpoint values with the
                # updated full checkpoint
                active_checkpoints = scalyr_util.read_file_as_json(
                    active_checkpoint_file_path, strict_utf8=True
                )

                if active_checkpoints["time"] > full_checkpoints["time"]:
                    full_checkpoints["time"] = active_checkpoints["time"]
                    for path, checkpoint in six.iteritems(
                        active_checkpoints["checkpoints"]
                    ):
                        full_checkpoints[path] = checkpoint

            if current_time - full_checkpoints["time"] > self.__config.max_allowed_checkpoint_age:
                log.warn(
                    "The worker checkpoint file '%s' is too stale (written at '%s').  Ignoring it.  All log files will "
                    "be copied starting at their current end.",
                    full_checkpoint_file_path,
                    scalyr_util.format_time(full_checkpoints["time"]),
                    error_code="staleCheckpointFile",
                )

                # checkpoint files are stale, so remove them.
                os.unlink(full_checkpoint_file_path)
                try:
                    # ignore if active checkpoints do not exist
                    os.unlink(active_checkpoint_file_path)
                except OSError as e:
                    if e.errno != 2:
                        raise
                return None

            return full_checkpoints

        except scalyr_util.JsonParseException:
            log.exception(
                "Could not read checkpoint file due to error. Ignoring checkpoint file.",
                error_code="failedCheckpointRead",
            )
            return None

    def __create_log_matches(self, configuration, monitors):
        """Creates the log matchers that should be used based on the configuration and the list of monitors.

        @param configuration: The Configuration object.
        @param monitors: A list of ScalyrMonitor instances whose logs should be copied.

        @type configuration: Configuration
        @type monitors: list<ScalyrMonitor>

        @return: The list of log matchers.
        @rtype: list<LogMatcher>
        """
        configs = []

        # We keep track of which paths we have configs for so that when we add in the configuration for the monitor
        # log files we don't re-add in the same path.  This can easily happen if a monitor is used multiple times
        # but they are all just writing to the same monitor file.
        all_paths = {}
        for entry in configuration.log_configs:
            if "path" in entry:
                configs.append(entry.copy())
                all_paths[entry["path"]] = 1

        for monitor in monitors:
            log_config = configuration.parse_log_config(
                monitor.log_config,
                default_parser="agent-metrics",
                context_description='log entry requested by module "%s"'
                % monitor.module_name,
            ).copy()

            if log_config["path"] not in all_paths:
                configs.append(log_config)
                all_paths[log_config["path"]] = 1

            monitor.log_config = log_config

        result = []

        for log_config in configs:
            worker = self.find_best_worker_for_log_config(log_config)
            result.append(
                LogMatcher(
                    configuration,
                    log_config,
                    log_processor_cls=worker.spawn_new_log_processor,
                )
            )

        return result

    def __scan_for_pending_log_files(self):
        """
        Creates log processors for any recent, dynamically added log matchers
        """

        # make a shallow copy of pending log_matchers, and pending reloads
        log_matchers = []
        pending_reload = {}
        self.__lock.acquire()
        try:
            log_matchers = self.__pending_log_matchers[:]

            # get any logs that need reloading and reset the pending reload list
            pending_reload = self.__logs_pending_reload.copy()
            self.__logs_pending_reload = {}
        finally:
            self.__lock.release()

        # add new matchers
        for matcher in log_matchers:
            self.__dynamic_matchers[matcher.log_path] = matcher

        checkpoints = self.__get_checkpoints(time.time())

        # reload the config of any matchers/processors that need reloading
        reloaded = []
        for path, log_config in six.iteritems(pending_reload):
            log.log(scalyr_logging.DEBUG_LEVEL_1, "Pending reload for %s" % path)

            # only reload matchers that have been dynamically added
            matcher = self.__dynamic_matchers.get(path, None)
            if matcher is None:
                log.log(
                    scalyr_logging.DEBUG_LEVEL_0, "Log matcher not found for %s" % path
                )
                continue

            # update the log config of the matcher, which closes any open processors, and returns
            # their checkpoints
            closed_processors = matcher.update_log_entry_config(log_config)
            for processor_path, checkpoint in six.iteritems(closed_processors):
                checkpoints[processor_path] = checkpoint

            reloaded.append(matcher)

        self.__remove_closed_processors()

        self.__create_log_processors_for_log_matchers(
            log_matchers, checkpoints=checkpoints, copy_at_index_zero=True
        )
        self.__create_log_processors_for_log_matchers(
            reloaded, checkpoints=checkpoints, copy_at_index_zero=True
        )

        self.__lock.acquire()
        try:
            self.__log_matchers.extend(log_matchers)
            self.__pending_log_matchers = [
                lm for lm in self.__pending_log_matchers if lm not in log_matchers
            ]
        finally:
            self.__lock.release()

    def __remove_logs_scheduled_for_deletion(self):
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

        # if we have a log matcher for the path, then set it to finished
        for path in six.iterkeys(pending_removal):
            matcher = self.__dynamic_matchers.get(path, None)
            if matcher is None:
                log.warn("Log scheduled for removal is not being monitored: %s" % path)
                continue

            matcher.finish()

        # remove from list of logs pending removal
        self.__lock.acquire()
        try:
            self.__logs_pending_removal = {}
        finally:
            self.__lock.release()

    def __purge_finished_log_matchers(self):
        """
        Removes from the list of log matchers any log matchers that are finished
        """
        # make a shallow copy for iteration
        matchers = self.__dynamic_matchers.copy()

        for path, m in six.iteritems(matchers):
            if m.is_finished():
                self.remove_log_path(SCHEDULED_DELETION, path)
                self.__dynamic_matchers.pop(path, None)

    def __remove_closed_processors(self):
        pass

    def generate_status(self, warn_on_rate_limit=False):
        """Generate the status for the copying manager to be reported.

        This is used in such features as 'scalyr-agent-2 status -v'.

        Note, this method is thread safe.  It needs to be since another thread will ask this object for its
        status.

        @return:  The status object containing the statistics for the copying manager.
        @rtype: CopyingManagerStatus
        """
        try:
            self.__lock.acquire()

            result = ShardedCopyingManagerStatus()

            result.total_scan_iterations = self.total_scan_iterations

            for api_key_id in sorted(self.__api_keys_worker_pools):
                worker_pool = self.__api_keys_worker_pools[api_key_id]
                worker_pool_status = worker_pool.generate_status()
                result.api_key_statuses[api_key_id] = worker_pool_status

                result.total_errors += worker_pool_status.total_errors

            # # get the most recent time fields from workers.
            # result.last_success_time = max(
            #     [status.last_success_time for status in worker_statuses]
            # )
            # result.last_attempt_time = max(
            #     [status.last_attempt_time for status in worker_statuses]
            # )
            #
            # # the next fields are a sum of the same fields from all workers.
            # result.total_bytes_uploaded = sum(
            #     status.total_bytes_uploaded for status in worker_statuses
            # )
            #
            # result.last_response_statuses = [
            #     status.last_response_status for status in worker_statuses
            # ]

            for entry in self.__log_matchers:
                result.log_matchers.append(entry.generate_status())

            # TODO: for now we just get sum from all workers to get values below, but it may be wrong to just get sum for them.
            # result.total_rate_limited_time = sum(
            #     status.total_rate_limited_time for status in worker_statuses
            # )
            # result.rate_limited_time_since_last_status = sum(
            #     status.rate_limited_time_since_last_status for status in worker_statuses
            # )
            # result.total_read_time = sum(
            #     status.total_read_time for status in worker_statuses
            # )
            # result.total_blocking_response_time = sum(
            #     status.total_blocking_response_time for status in worker_statuses
            # )
            # result.total_request_time = sum(
            #     status.total_request_time for status in worker_statuses
            # )
            # result.total_pipelined_requests = sum(
            #     status.total_pipelined_requests for status in worker_statuses
            # )
            # result.total_copy_iterations = sum(
            #     status.total_copy_iterations for status in worker_statuses
            # )

        finally:
            self.__lock.release()

        return result

    @property
    def expanded_server_attributes(self):
        """Return deepcopy of expanded server attributes"""
        return copy.deepcopy(self.__expanded_server_attributes)

    def start_manager(self, scalyr_client, logs_initial_positions=None):
        self.__scalyr_client = scalyr_client
        self._logs_initial_positions = logs_initial_positions

        # self._initial_checkpoints = self.__get_checkpoints(time.time())
        #
        # # start all workers.
        # for worker in self._workers.values():
        #     worker.start_worker(scalyr_client=self.__scalyr_client)
        #
        # # wait for workers started copying.
        # for worker in self._workers.values():
        #     worker.wait_for_copying_to_begin()

        self.start()

    def stop_manager(self, wait_on_join=True, join_timeout=5):
        """Stops the manager.

        @param wait_on_join: If True, will block on a join of the thread running the manager.
        @param join_timeout: The maximum number of seconds to block for the join.
        """

        # for worker in self._workers.values():
        #     worker.stop_worker(wait_on_join=True, join_timeout=join_timeout)

        self.stop(wait_on_join=wait_on_join, join_timeout=join_timeout)

    def _sleep_but_awaken_if_stopped(self, seconds):
        """Makes the current thread (the copying manager thread) go to sleep for the specified number of seconds,
        or until the manager is stopped, whichever comes first.

        Note, this method is exposed for testing purposes.

        @param seconds: The number of seconds to sleep.
        @type seconds: float
        """
        self._run_state.sleep_but_awaken_if_stopped(seconds)

    def add_log_config(self, monitor_name, log_config):
        """Add the log_config item to the list of paths being watched
        param: monitor_name - the name of the monitor adding the log config
        param: log_config - a log_config object containing the path to be added
        returns: an updated log_config object
        """
        log_config = self.__config.parse_log_config(
            log_config,
            default_parser="agent-metrics",
            context_description='Additional log entry requested by module "%s"'
            % monitor_name,
        ).copy()

        self.__lock.acquire()
        try:
            # Make sure the path isn't already being dynamically monitored
            path = log_config["path"]
            if path in self.__dynamic_paths:
                log.log(
                    scalyr_logging.DEBUG_LEVEL_0,
                    "Tried to add new log file '%s' for monitor '%s', but it is already being monitored by '%s'"
                    % (path, monitor_name, self.__dynamic_paths[path]),
                )
                return log_config

            # add the path and matcher
            worker = self.find_best_worker_for_log_config(log_config)

            matcher = LogMatcher(
                self.__config,
                log_config,
                log_processor_cls=worker.spawn_new_log_processor,
            )
            self.__dynamic_paths[path] = monitor_name
            self.__pending_log_matchers.append(matcher)
            log.log(
                scalyr_logging.DEBUG_LEVEL_0,
                "Adding new log file '%s' for monitor '%s'" % (path, monitor_name),
            )

            # If the log was previously pending removal, cancel the pending removal
            self.__logs_pending_removal.pop(path, None)

        finally:
            self.__lock.release()

        return log_config

    def update_log_config(self, monitor_name, log_config):
        """ Updates the log config of the log matcher that has the same
        path as the one specified in the log_config param
        """
        log_config = self.__config.parse_log_config(
            log_config,
            default_parser="agent-metrics",
            context_description='Updating log entry requested by module "%s"'
            % monitor_name,
        ).copy()
        try:
            self.__lock.acquire()

            path = log_config["path"]
            # Make sure the log path is being dynamically monitored
            if path not in self.__dynamic_paths:
                log.log(
                    scalyr_logging.DEBUG_LEVEL_0,
                    "Tried to updating a log file '%s' for monitor '%s', but it is not being monitored"
                    % (path, monitor_name),
                )
                return

            # Make sure only the monitor that added this path can update it
            if (
                path in self.__dynamic_paths
                and self.__dynamic_paths[path] != monitor_name
            ):
                log.log(
                    scalyr_logging.DEBUG_LEVEL_0,
                    "Tried to updating a log file '%s' for monitor '%s', but it is currently being monitored by '%s'"
                    % (path, monitor_name, self.__dynamic_paths[path]),
                )
                return

            log.log(
                scalyr_logging.DEBUG_LEVEL_0,
                "Updating config for log file '%s' for monitor '%s'"
                % (path, monitor_name),
            )
            self.__logs_pending_reload[path] = log_config
        finally:
            self.__lock.release()

    def remove_log_path(self, monitor_name, log_path):
        """Remove the log_path from the list of paths being watched
        params: log_path - a string containing the path to the file no longer being watched
        """
        # get the list of paths with 0 reference counts
        self.__lock.acquire()
        try:
            # Make sure the log path is being dynamically monitored
            if log_path not in self.__dynamic_paths:
                log.log(
                    scalyr_logging.DEBUG_LEVEL_0,
                    "Tried removing a log file '%s' for monitor '%s', but it is not being monitored"
                    % (log_path, monitor_name),
                )
                return

            # If we are not a scheduled deletion, make sure only the monitor that added this path can remove it
            if (
                monitor_name != SCHEDULED_DELETION
                and log_path in self.__dynamic_paths
                and self.__dynamic_paths[log_path] != monitor_name
            ):
                log.log(
                    scalyr_logging.DEBUG_LEVEL_0,
                    "Tried removing a log file '%s' for monitor '%s', but it is currently being monitored by '%s'"
                    % (log_path, monitor_name, self.__dynamic_paths[log_path]),
                )
                return

            log.log(
                scalyr_logging.DEBUG_LEVEL_0,
                "Removing log file '%s' for '%s'" % (log_path, monitor_name),
            )
            # do the removals
            matchers = []
            for m in self.__log_matchers:
                if m.log_path == log_path:
                    # Make sure the matcher is always finished if called from a non scheduled deletion (e.g. on shutdown/config reload).
                    # This ensures that the __dynamic_matchers dict on the main thread will also clean
                    # itself up when it notices the matcher is finished.
                    # We set the matcher to finish immediately, because we want the matcher to finish now, not when it's finished
                    # any existing processing
                    m.finish(immediately=True)
                else:
                    matchers.append(m)

            self.__log_matchers[:] = matchers
            self.__logs_pending_removal.pop(log_path, None)
            self.__logs_pending_reload.pop(log_path, None)
            self.__dynamic_paths.pop(log_path, None)

        finally:
            self.__lock.release()

    def schedule_log_path_for_removal(self, monitor_name, log_path):
        """
            Schedules a log path for removal.  The logger will only
            be removed once the number of pending bytes reaches 0
        """
        self.__lock.acquire()
        try:
            # Make sure the log path is being dynamically monitored
            if log_path not in self.__dynamic_paths:
                log.log(
                    scalyr_logging.DEBUG_LEVEL_0,
                    "Tried scheduling the removal of log file '%s' for monitor '%s', but it is not being monitored"
                    % (log_path, monitor_name),
                )
                return

            # Make sure only the monitor that added this path can remove it
            if (
                log_path in self.__dynamic_paths
                and self.__dynamic_paths[log_path] != monitor_name
            ):
                log.log(
                    scalyr_logging.DEBUG_LEVEL_0,
                    "Tried scheduling the removal of log file '%s' for monitor '%s', but it is currently being monitored by '%s'"
                    % (log_path, monitor_name, self.__dynamic_paths[log_path]),
                )
                return

            if log_path not in self.__logs_pending_removal:
                self.__logs_pending_removal[log_path] = True
                log.log(
                    scalyr_logging.DEBUG_LEVEL_0,
                    "log path '%s' for monitor '%s' is pending removal"
                    % (log_path, monitor_name),
                )
        finally:
            self.__lock.release()

    def dynamic_matchers_count(self):
        """
            Used for testing - returns the number of dynamic matchers
        """
        return len(self.__dynamic_matchers)

    def logs_pending_removal_count(self):
        """
            Used for testing - returns the number of logs pending removal
        """

        self.__lock.acquire()
        try:
            return len(self.__logs_pending_removal)
        finally:
            self.__lock.release()

    @property
    def log_matchers(self):
        """Returns the list of log matchers that were created based on the configuration and passed in monitors.

        This is really only exposed for testing purposes.

        @return: The log matchers.
        @rtype: list<LogMatcher>
        """
        return self.__log_matchers

    def find_best_worker_for_log_config(self, log_config_entry):
        # type: (Dict) -> CopyingManagerWorkerWrapper
        """
        Find the best worker for the given log processor with given conditions.
        For example log file handled by processor may be configured to be sent only by particular scalyr account and etc.
        Now it is just a simple round-robin algorithm.
        TODO: implement processor->api_key binding.
        :return:
        """

        api_key_id = log_config_entry.get("api_key_id", none_if_missing=True)
        if api_key_id is not None:
            worker_pool = self.__api_keys_worker_pools[api_key_id]
        else:
            worker_pool = self.__all_workers_pool

        return worker_pool.find_next_worker()

    def augment_user_agent_for_workers_sessions(self, fragments):
        # type: (List[six.text_type]) -> None
        """
        Modifies User-Agent header of the sessions to all worker.

        @param fragments String fragments to append (in order) to the standard user agent data
        @type fragments: List of six.text_type
        """
        for worker in self._all_workers_pool.workers.values():
            worker.augment_user_agent_for_client_session(fragments)

    def get_worker_session_statuses(self):
        # type: () -> Dict[six.text_type, ScalyrClientSessionStatus]
        """
        Get session statuses from all workers.
        :return: dict with worker_id -> ScalyrClientSessionStatus.
        """
        session_stats = {}
        for worker in self._all_workers_pool.workers.values():
            session_stats[worker.worker_id] = worker.generate_scalyr_client_status()

        return session_stats


def _max(v1, v2):
    values = [v for v in [v1, v2] if v is not None]
    return max(values)


class ApiKeyWorkerPool(object):
    def __init__(self, workers):
        # type: (List[CopyingManagerWorker]) -> None

        self.__workers_list = workers

        # mapping worker_ids to workers
        self.__workers = {w.worker_id: w for w in workers}  # type: Dict[six.text_type, CopyingManagerWorker]

        self.__current_worker = 0

    @property
    def workers(self):
        return self.__workers

    def find_next_worker(self):
        # type: () -> CopyingManagerWorker
        """Get the next worker in the pool."""
        current_worker = self.__workers_list[self.__current_worker]
        if self.__current_worker == len(self.__workers_list) - 1:
            self.__current_worker = 0
        else:
            self.__current_worker += 1

        return current_worker

    def add_log_processor(self, log_processor):
        # type: (LogFileProcessor) -> None
        worker = self.find_next_worker()
        worker.schedule_new_log_processor(log_processor)

    def start_workers(self):
        for worker in self.__workers_list:
            worker.start_worker()

        for worker in self.__workers_list:
            worker.wait_for_copying_to_begin()

    def stop_workers(self, wait_on_join=True, join_timeout=5):
        for worker in self.__workers_list:
            worker.stop_worker(wait_on_join=wait_on_join, join_timeout=join_timeout)

    def generate_status(self):
        # type: () -> ApiKeyWorkerPoolStatus
        """Generate status of the worker"""
        result = ApiKeyWorkerPoolStatus()

        failed_worker_health_checks = []
        health_checks = set()
        last_responses = set()
        result.workers_statuses = statuses = list()
        last_failed_response_statuses = collections.OrderedDict()
        failed_health_check_results = collections.OrderedDict()
        last_responses_size = 0
        last_attempt_time = 0

        for worker in sorted(self.__workers_list, key=lambda w:w.worker_id):
            status = worker.generate_status()
            result.workers[worker.worker_id] = status

            # get the most recent time fields from workers.
            if status.last_success_time:
                result.last_success_time = _max(
                    result.last_success_time, status.last_success_time
                )
            if status.last_attempt_time:
                result.last_attempt_time = _max(
                    result.last_attempt_time, status.last_attempt_time
                )

            if status.last_attempt_size:
                result.last_attempt_size = _max(
                    result.last_attempt_size, status.last_attempt_size
                )

            if status.last_response is not None:
                last_responses_size += len(status.last_response)

            if status.last_response_status is not None and status.last_response_status != "success":
                result.last_failed_response_statuses[worker.worker_id] = status.last_response_status

            if status.health_check_result is not None and status.health_check_result != "Good":
                failed_health_check_results[worker.worker_id] = status.health_check_result

            # the next fields are a sum of the same fields from all workers.
            result.total_bytes_uploaded += status.total_bytes_uploaded

            result.total_errors += status.total_errors

        if last_responses_size:
            result.last_responses_size = last_responses_size

        if failed_health_check_results:
            result.failed_health_check_results = failed_health_check_results


        return result


class CopyingManagerWorkerInterface:
    __metaclass__ = ABCMeta

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
        """Block the current thread until this instance has finished its first scan and has begun copying.

        It is good to wait for the first scan to finish before possibly creating new files to copy because
        if the first scan has not completed, the copier will just begin copying at the end of the file when
        it is first noticed.  However, if the first scan has completed, then the copier will know that the
        new file was just newly created and should therefore have all of its bytes copied to Scalyr.

        TODO:  Make it so that this thread does not block indefinitely if the copying never starts.  However,
        we do not do this now because the CopyManager's run method will sys.exit if the copying fails to start.
        """
        pass

    @abstractmethod
    def schedule_new_log_processor(self, log_processor):
        """Schedules new log processor. It will be added to the main collection only on the next iteration,
        so we don;t have to guard the main collection with lock."""
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
    def is_alive(self):
        pass


class CopyingManagerWorker(StoppableThread, CopyingManagerWorkerInterface):
    def __init__(self, configuration, api_key_config_entry, worker_id):
        StoppableThread.__init__(
            self, name="copying manager worker thread #%s" % worker_id
        )

        self._id = six.text_type(worker_id)
        self.__config = configuration
        self.__api_key_config_entry = api_key_config_entry

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

        # Temporary collection of recently added log processors.
        # Every log processor which is added during the iteration of the worker is placed in here.
        # All those log processors will be added to the main collection
        # on the beginning of the next iteration.
        # It stores all new log processors before they are added to the main log processors list.
        self.__new_log_processors = []

        self.__log_processors_scheduled_for_removal = dict()

        # The next LogFileProcessor that should have log lines read from it for transmission.
        self.__current_processor = 0

        self.__worker_id = None

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

    def _get_log_processors(self):  # type: () -> Dict[six.text_type, LogFileProcessor]
        """
        List of log processors. Exposed only for test purposes.
        """
        return self.__log_processors.copy()

    @property
    def log_processors(self):
        # type: () -> Dict[six.text_type, LogFileProcessor]
        """
        List of log processors. Exposed only for test purposes.
        """
        return self._get_log_processors()

    @property
    def worker_config_entry(self):
        return self.__api_key_config_entry

    def start_worker(self):
        self.start()

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
        # assert self.__scalyr_client is not None
        self.__scalyr_client = self.__create_client()

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

                log.info("Copying manager worker #%s started." % self.worker_id)

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
                            for processor in self.__log_processors.values():
                                processor.skip_to_end(
                                    "Too long since last successful request to server.",
                                    "skipNoServerSuccess",
                                    current_time=current_time,
                                )

                        self.__close_log_processors_marked_to_be_closed()
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
                                self.__pending_add_events_task.next_pipelined_task = self.__get_next_add_events_task(
                                    copying_params.current_bytes_allowed_to_send,
                                    for_pipelining=True,
                                )
                            else:
                                pipeline_time = 0.0

                            # Now block for the response.
                            blocking_response_time_start = time.time()
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
            except Exception as e:
                # If we got an exception here, it is caused by a bug in the program, so let's just terminate.
                log.exception("Log copying failed due to exception")
                sys.exit(1)
        finally:

            self.__write_full_checkpoint_state(current_time)
            for processor in self.__log_processors.values():
                processor.close()

            self.__scalyr_client.close()
            if profiler is not None:
                profiler.disable()

            log.log(
                scalyr_logging.DEBUG_LEVEL_0,
                "Worker '%s' is finished." % self.worker_id,
            )

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
            result.worker_id = self._id
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
                log_processor_status = processor.generate_status()
                log_processor_status.worker_id = self._id
                result.log_processors[path] = log_processor_status

            if self.__last_attempt_time:
                result.health_check_result = "Good"
                if (
                    time.time()
                    > self.__last_attempt_time
                    + self.__config.healthy_max_time_since_last_copy_attempt
                ):
                    result.health_check_result = (
                        "Worker '%s' failed, max time since last copy attempt (%s seconds) exceeded"
                        % (self.worker_id, self.__config.healthy_max_time_since_last_copy_attempt)
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

    def schedule_new_log_processor(self, log_processor):
        # type: (LogFileProcessor) -> None
        """Schedules new log processor. It will be added to the main collection only on the next iteration,
        so we don;t have to guard the main collection with lock."""

        with self.__lock:
            self.__new_log_processors.append(log_processor)

        log.log(
            scalyr_logging.DEBUG_LEVEL_1,
            "Log processor for file '%s' is scheduled to be added"
            % log_processor.log_path,
        )

    def __close_log_processors_marked_to_be_closed(self):
        """
        Close all log processors which have been marked to closed.
        :return:
        """

        for path, log_processor in list(self.__log_processors.items()):
            if log_processor.is_closed():
                log_processor.close()
                self.__log_processors.pop(path)
                log.log(
                    scalyr_logging.DEBUG_LEVEL_1,
                    "Log processor for file '%s' is closed." % path,
                )

    def __add_new_log_processors(self):
        """
        Add all previously scheduled log processors to the main collection.
        :return:
        """
        with self.__lock:
            new_log_processors = self.__new_log_processors[:]
            self.__new_log_processors = []

        for new_log_processor in new_log_processors:
            self.__log_processors[new_log_processor.log_path] = new_log_processor
            log.log(
                scalyr_logging.DEBUG_LEVEL_1,
                "Log processor for file '%s' is added." % new_log_processor.log_path,
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

    @property
    def scalyr_client(self):
        return self.__scalyr_client

    def __create_client(self, quiet=False):
        """Creates and returns a new client to the Scalyr servers.

        @param quiet: If true, only errors should be written to stdout.
        @type quiet: bool

        @return: The client to use for sending requests to Scalyr, using the server address and API write logs
            key in the configuration file.
        @rtype: ScalyrClientSession
        """
        return create_client(
            self.__config, quiet=quiet, api_key=self.worker_config_entry["api_key"]
        )


class LogFileProcessorWrapperProxy(BaseProxy):
    _exposed_ = (
        six.ensure_str("__getattribute__"),
        "log_path",
        "initialize",
        "is_closed",
        "close_at_eof",
        "close",
        "generate_status",
        "add_missing_attributes",
        "get_checkpoint"
    )

    @property
    def log_path(self, *args, **kwargs):
        return self._callmethod("__getattribute__", args=("log_path",))

    def initialize(self, *args, **kwargs):
        return self._callmethod("initialize", args=args, kwds=kwargs)

    def generate_status(self, *args, **kwargs):
        return self._callmethod("generate_status", args=args, kwds=kwargs)

    # def perform_processing(self, *args, **kwargs):
    #     return self._callmethod("perform_processing" ,args=args, kwds=kwargs)

    def is_closed(self):
        return self._callmethod("is_closed")

    def close(self):
        self._callmethod("close")

    def close_at_eof(self, *args, **kwargs):
        return self._callmethod("close_at_eof", args=args, kwds=kwargs)

    def get_checkpoint(self, *args, **kwargs):
        self._callmethod("get_checkpoint", args=args, kwds=kwargs)

    def add_missing_attributes(self, *args, **kwargs):
        self._callmethod("add_missing_attributes", args=args, kwds=kwargs)


class LogFileProcessorWrapper(LogFileProcessorInterface):
    def __init__(self, *args, **kwargs):
        self._real_processor = None  # type: Optional[LogFileProcessor]
        self.__args = args
        self.__kwargs = kwargs

        self._marked_for_close = False

        self.worker_id = None

    def initialize(self):
        self._real_processor = LogFileProcessor(*self.__args, **self.__kwargs)
        return self.__args, self.__kwargs

    def __getstate__(self):
        state = self.__dict__.copy()
        del state["_real_processor"]
        return state

    def get_checkpoint(self):
        return self._real_processor.get_checkpoint()

    def add_redacter(self, *args, **kwargs):
        return self._real_processor.add_redacter(*args, **kwargs)

    def set_inactive(self):
        return self._real_processor.set_inactive()

    @property
    def is_active(self):
        if self._real_processor is not None:
            return self._real_processor.is_active

    def perform_processing(self, add_events_request, current_time=None):
        return self._real_processor.perform_processing(add_events_request, current_time)

    @property
    def unique_id(self):
        if self._real_processor is not None:
            return self._real_processor.unique_id

    def close(self):
        self._marked_for_close = True

    def close_at_eof(self):
        self._real_processor.close_at_eof()

    def is_closed(self):
        if self._real_processor is not None:
            if self._real_processor.is_closed():
                return True
            if self._marked_for_close:
                self._real_processor.close()
                return True
            return False

    @property
    def is_marked_for_close(self):
        return self._marked_for_close

    def add_sampler(self, match_expression, sampling_rate):
        return self._real_processor.add_sampler(match_expression, sampling_rate)

    def generate_status(self):
        if self._real_processor is not None:
            return self._real_processor.generate_status()

    def scan_for_new_bytes(self, current_time):
        return self._real_processor.scan_for_new_bytes(current_time)

    def add_missing_attributes(self, attributes):
        return self._real_processor.add_missing_attributes(attributes)

    def set_max_log_offset_size(self, max_log_offset_size):
        return self._real_processor.set_max_log_offset_size(max_log_offset_size)

    def skip_to_end(self, message, error_code, current_time):
        return self._real_processor.skip_to_end(message, error_code, current_time)

    @property
    def log_path(self):
        if self._real_processor is not None:
            return self._real_processor.log_path


class CopyingManagerWorkerProxy(BaseProxy, CopyingManagerWorkerInterface):
    _exposed_ = (
        six.ensure_str("__getattribute__"),
        six.ensure_str("schedule_new_log_processor"),
        six.ensure_str("start_worker"),
        six.ensure_str("stop_worker"),
        six.ensure_str("wait_for_copying_to_begin"),
        six.ensure_str("is_alive"),
        six.ensure_str("augment_user_agent_for_client_session"),
        six.ensure_str("generate_status"),
        six.ensure_str("generate_scalyr_client_status"),
    )

    def start_worker(self, *args, **kwargs):
        return self._callmethod("start_worker", args=args, kwds=kwargs)

    def stop_worker(self, *args, **kwargs):
        return self._callmethod("stop_worker", args=args, kwds=kwargs)

    def wait_for_copying_to_begin(self):
        return self._callmethod("wait_for_copying_to_begin")

    def augment_user_agent_for_client_session(self, fragments):
        return self._callmethod(
            "augment_user_agent_for_client_session", args=(fragments,)
        )

    def generate_scalyr_client_status(self):
        return self._callmethod("generate_scalyr_client_status")

    def generate_status(self, *args, **kwargs):
        return self._callmethod("generate_status", args=args, kwds=kwargs)

    def schedule_new_log_processor(self, log_processor):
        return self._callmethod("schedule_new_log_processor", args=(log_processor,))

    @property
    def log_processors(self):
        return self._callmethod("__getattribute__", args=("log_processors",))

    @property
    def worker_id(self):
        return self._callmethod("__getattribute__", args=("worker_id",))

    def is_alive(self):
        return self._callmethod("is_alive")


class CopyingManagerWorkerWrapperInterface(object):
    __metaclass__ = ABCMeta

    @property
    @abstractmethod
    def worker_type(self):
        return self.__worker_type

    @property
    @abstractmethod
    def memory_manager(self):
        pass

    @abstractmethod
    def spawn_new_log_processor(self, *args, **kwargs):
        pass


class CopyingManagerWorkerWrapper(
    CopyingManagerWorkerWrapperInterface, CopyingManagerWorkerInterface
):
    def __init__(
        self,
        configuration,
        api_key_config_entry,
        worker_id,
        real_worker_class=CopyingManagerWorker,
        worker_proxy_class=CopyingManagerWorkerProxy,
    ):
        self._memory_manager = None
        self.__worker_type = api_key_config_entry.get("type")

        if self.__worker_type == "process":

            class CopyingManagerMemoryManager(BaseManager):
                pass

            CopyingManagerMemoryManager.register(
                six.ensure_str("CopyingManagerWorker"),
                real_worker_class,
                worker_proxy_class,
            )
            CopyingManagerMemoryManager.register(
                six.ensure_str("LogFileProcessorWrapper"),
                LogFileProcessorWrapper,
                LogFileProcessorWrapperProxy,
            )

            self._memory_manager = CopyingManagerMemoryManager()

            self._memory_manager.start()

            self.real_worker = self.memory_manager.CopyingManagerWorker(
                configuration, api_key_config_entry, worker_id
            )  # type: CopyingManagerWorkerInterface
        else:
            self.real_worker = real_worker_class(
                configuration, api_key_config_entry, worker_id
            )

    @property
    def worker_type(self):
        return self.__worker_type

    def full_stop(self):
        self.real_worker.stop_worker()
        if self._memory_manager is not None:
            self._memory_manager.shutdown()

    @property
    def memory_manager(self):
        return self._memory_manager

    def spawn_new_log_processor(self, *args, **kwargs):
        if self.__worker_type == "process":
            processor = self.memory_manager.LogFileProcessorWrapper(*args, **kwargs)
            processor.initialize()
            processor.worker_id = self.worker_id
            return processor
        else:
            return LogFileProcessor(*args, **kwargs)

    def stop_worker(self, wait_on_join=True, join_timeout=5):
        self.real_worker.stop_worker(
            wait_on_join=wait_on_join, join_timeout=join_timeout
        )

        self._memory_manager.shutdown()

    def start_worker(self):
        return self.real_worker.start_worker()

    def wait_for_copying_to_begin(self):
        return self.real_worker.wait_for_copying_to_begin()

    def generate_status(self, warn_on_rate_limit=False):
        return self.real_worker.generate_status(warn_on_rate_limit=warn_on_rate_limit)

    def generate_scalyr_client_status(self):
        return self.real_worker.generate_scalyr_client_status()

    def augment_user_agent_for_client_session(self, fragments):
        return self.real_worker.augment_user_agent_for_client_session(fragments)

    def schedule_new_log_processor(self, log_processor):
        return self.real_worker.schedule_new_log_processor(log_processor)

    @property
    def worker_id(self):
        return self.real_worker.worker_id

    def is_alive(self):
        return self.real_worker.is_alive()
