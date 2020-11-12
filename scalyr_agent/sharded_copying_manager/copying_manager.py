from __future__ import unicode_literals
from __future__ import absolute_import

import copy
import datetime
import fnmatch
import os
import sys
import threading
import time
import collections
import operator
import glob
import re

if False:
    from typing import Dict
    from typing import List

from scalyr_agent import scalyr_logging as scalyr_logging, StoppableThread, util as scalyr_util
from scalyr_agent.agent_status import ShardedCopyingManagerStatus, ApiKeyWorkerPoolStatus
from scalyr_agent.sharded_copying_manager.worker import CopyingManagerWorkerContainer
from scalyr_agent.log_processing import LogMatcher, LogFileProcessor
from scalyr_agent.log_watcher import LogWatcher
from scalyr_agent.util import RateLimiter
from scalyr_agent.configuration import Configuration
from scalyr_agent.scalyr_client import ScalyrClientSessionStatus

import six

log = scalyr_logging.getLogger(__name__)
SCHEDULED_DELETION = "scheduled-deletion"


def _max(v1, v2):
    """max function which ignores None values"""
    values = [v for v in [v1, v2] if v is not None]
    return max(values)


class ApiKeyWorkerPool(object):
    """
    This abstraction is responsible for maintaining the workers
    for a particular entry in the 'api_keys' list in the configuration.
    It also creates worker instances according to the number in the "workers" field in each entry.
    """
    def __init__(self, config, api_key_config):
        # type: (Configuration, Dict) -> None

        self.__api_key_id = api_key_config["id"]
        self.__config = config
        self.__workers = []

        for i in range(api_key_config["workers"]):
            # combine workers positional number in pool and poll id.
            worker_id = "%s_%s" % (self.__api_key_id, i)

            worker = CopyingManagerWorkerContainer(
                self.__config, api_key_config, worker_id
            )
            self.__workers.append(worker)
            log.log(
                scalyr_logging.DEBUG_LEVEL_1,
                "CopyingManagerWorker #%s is created." % worker.get_id(),
            )

        self.__current_worker = 0

    @property
    def api_key_id(self):
        return self.__api_key_id

    @property
    def workers(self):
        return self.__workers


    def find_next_worker(self):
        # type: () -> CopyingManagerWorkerContainer
        """Get the next worker in the pool. For now it is just a round robin."""
        current_worker = self.__workers[self.__current_worker]
        if self.__current_worker == len(self.__workers) - 1:
            self.__current_worker = 0
        else:
            self.__current_worker += 1

        return current_worker


    def start_workers(self):
        # type: () -> None
        """
        Start all workers in the pool.
        """
        for worker in self.__workers:
            worker.start_worker()

        for worker in self.__workers:
            worker.wait_for_copying_to_begin()

    def stop_workers(self, wait_on_join=True, join_timeout=5):
        # type: (bool, int) -> None
        for worker in self.__workers:
            worker.stop_worker(wait_on_join=wait_on_join, join_timeout=join_timeout)

    def generate_status(self):
        # type: () -> ApiKeyWorkerPoolStatus
        """Generate status of the worker pool."""
        result = ApiKeyWorkerPoolStatus()

        result.api_key_id = self.__api_key_id

        last_response_statuses = set()
        health_checks = set()

        for worker in sorted(self.__workers, key=lambda w: w.get_id()):
            status = worker.generate_status()
            result.workers.append(status)

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

            if status.last_response_status is not None:
                last_response_statuses.add(status.last_response_status)

            if (
                status.health_check_result is not None
            ):
                health_checks.add(status.health_check_result)

            # the next fields are a sum of the same fields from all workers.
            result.total_bytes_uploaded += status.total_bytes_uploaded

            result.total_errors += status.total_errors

        if last_response_statuses:
            if len(last_response_statuses) == 1 and "success" in last_response_statuses:
                result.has_successful_last_response = True
            else:
                result.has_successful_last_response = False

        if health_checks:
            if len(health_checks) == 1 and "Good" in health_checks:
                result.has_good_health_checks = True
            else:
                result.has_good_health_checks = False

        return result


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
        StoppableThread.__init__(self, name="copying manager thread")
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

        # A dict from file path to the LogFileProcessor that is processing it.
        self.__log_paths_being_processed = {}
        # A lock that protects the status variables and the __log_matchers variable, the only variables that
        # are access in generate_status() which needs to be thread safe.
        self.__lock = threading.Lock()

        # The last time we scanned for new files that match the __log_matchers.
        self.__last_new_file_scan_time = 0

        # Status variables that track statistics reported to the status page.
        self.__last_scan_attempt_time = None
        self.__total_errors = 0

        # The positions to use for a given file if there is not already a checkpoint for that file.
        # Set in the start_manager call.
        self.__logs_initial_positions = None

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

        # A worker pools for each api key in the 'api_keys' list in the configuration.
        self._api_keys_worker_pools = dict()  # type: Dict[six.text_type, ApiKeyWorkerPool]

        # create copying workers according to settings in the configuration.
        self._create_worker_pools()

        # The list of LogMatcher objects that are watching for new files to appear.
        # NOTE: log matchers must be created only after worker pools.
        self.__log_matchers = self.__create_log_matches(self.__config, self.__monitors)

    @property
    def expanded_server_attributes(self):
        """Return deepcopy of expanded server attributes"""
        return copy.deepcopy(self.__expanded_server_attributes)

    @property
    def log_matchers(self):
        """Returns the list of log matchers that were created based on the configuration and passed in monitors.

        This is really only exposed for testing purposes.

        @return: The log matchers.
        @rtype: list<LogMatcher>
        """
        return self.__log_matchers

    def add_log_config(self, monitor_name, log_config, force_add=False):
        """Add the log_config item to the list of paths being watched
        param: monitor_name - the name of the monitor adding the log config
        param: log_config - a log_config object containing the path to be added
        param force_add: True or force add this file and cancel any removal which
        may have been scheduled before hand.
        We really just want to use this with Docker monitor where there is a small windows between
        the container restart where the log file is not immediately removed.
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
            path = log_config["path"]

            # Make sure path is not already scheduled for removal. If it is and force_add is true,
            # we cancel scheduled removal and continue to monitor it
            if force_add and path in self.__logs_pending_removal:
                log.log(
                    scalyr_logging.DEBUG_LEVEL_0,
                    "Tried to add new log file '%s' for monitor '%s', but it is already being monitored by '%s' "
                    "and scheduled for removal. Canceling scheduled removal and ensuring log file is continue "
                    "to be monitored."
                    % (path, monitor_name, self.__dynamic_paths[path]),
                )
                del self.__logs_pending_removal[path]
                return log_config

            # Make sure the path isn't already being dynamically monitored
            if path in self.__dynamic_paths:
                log.log(
                    scalyr_logging.DEBUG_LEVEL_0,
                    "Tried to add new log file '%s' for monitor '%s', but it is already being monitored by '%s'"
                    % (path, monitor_name, self.__dynamic_paths[path]),
                )
                return log_config

            # add the path and matcher
            matcher = LogMatcher(self.__config, log_config)
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
            result.append(
                LogMatcher(configuration, log_config)
            )

        return result

    def start_manager(
        self, logs_initial_positions=None
    ):
        """Starts the manager running and will not return until it has been stopped.

        This will start a new thread to run the manager.

        @param logs_initial_positions: A dict mapping file paths to the offset with the file to begin copying
            if none can be found from the checkpoint files.  This can be used to override the default behavior of
            just reading from the current end of the file if there is no checkpoint for the file
        @type logs_initial_positions: dict
        """
        self.__logs_initial_positions = logs_initial_positions
        self.start()

    def stop_manager(self, wait_on_join=True, join_timeout=5):
        """Stops the manager.

        @param wait_on_join: If True, will block on a join of the thread running the manager.
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
                for worker_pool in self._api_keys_worker_pools.values():
                    worker_pool.start_workers()

                # Do the initial scan for any log files that match the configured logs we should be copying.  If there
                # are checkpoints for them, make sure we start copying from the position we left off at.
                self._scan_for_new_logs_if_necessary(
                    current_time=current_time,
                    checkpoints=checkpoints,
                    logs_initial_positions=self.__logs_initial_positions,
                )

                # We are about to start copying.  We can tell waiting threads.
                self.__copying_semaphore.release()

                workers_count = 0
                for worker_pool in self._api_keys_worker_pools.values():
                    workers_count += len(worker_pool.workers)

                log.info("Copying manager started. Total workers: %s, Pid: %s" % (workers_count,  os.getpid()))

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
                        self.__last_scan_attempt_time = current_time

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
                        self.__last_scan_attempt_time = current_time
                        self.__total_errors += 1
                        self.__lock.release()

                    self._sleep_but_awaken_if_stopped(
                        self.__config.max_request_spacing_interval
                    )

                    # End of the copy loop
                    self.total_scan_iterations += 1
            except Exception:
                # If we got an exception here, it is caused by a bug in the program, so let's just terminate.
                log.exception("Log copying failed due to exception")
                sys.exit(1)
        finally:
            # stopping all workers.
            for worker_pool in self._api_keys_worker_pools.values():
                worker_pool.stop_workers()

            if profiler is not None:
                profiler.disable()

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

            last_response_statuses = set()
            health_checks = set()

            for api_key_id in sorted(self._api_keys_worker_pools):
                worker_pool = self._api_keys_worker_pools[api_key_id]
                worker_pool_status = worker_pool.generate_status()
                result.api_key_statuses[api_key_id] = worker_pool_status

                result.total_errors += worker_pool_status.total_errors

                if worker_pool_status.has_successful_last_response is not None:
                    last_response_statuses.add(worker_pool_status.has_successful_last_response)

                if worker_pool_status.has_good_health_checks is not None:
                    health_checks.add(worker_pool_status.has_good_health_checks)

                result.total_bytes_uploaded += worker_pool_status.total_bytes_uploaded

            if last_response_statuses:
                if len(last_response_statuses) == 1 and True in last_response_statuses:
                    result.has_successful_last_response = True
                else:
                    result.has_successful_last_response = False

            for entry in self.__log_matchers:
                result.log_matchers.append(entry.generate_status())

            all_health_check_error_messages = list()

            if self.__last_scan_attempt_time:
                if (
                        time.time()
                        > self.__last_scan_attempt_time
                        #TODO: create new config value for that.
                        + self.__config.healthy_max_time_since_last_copy_attempt
                ):
                    all_health_check_error_messages.append((
                            "Failed, max time since last scan attempt (%s seconds) exceeded"
                            % self.__config.healthy_max_time_since_last_copy_attempt
                    ))

            if False in health_checks:
                all_health_check_error_messages.append("Some workers has failed, see below for more info.")

            if len(all_health_check_error_messages) > 0:
                result.health_check_result = "\n".join(all_health_check_error_messages)
            elif len(health_checks) > 0:
                result.health_check_result = "Good"

            if len(last_response_statuses) > 0:
                if False in last_response_statuses:
                    result.workers_last_responses_status = "Last requests on some workers is not successful, see below for more info."
                else:
                    result.workers_last_responses_status = "All successful"

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

    def __read_checkpoint_state(self):
        """Reads the checkpoint state from disk and returns it.

        The checkpoint state maps each file path to the offset within that log file where we left off copying it.

        @return:  The checkpoint state
        @rtype: dict
        """
        full_checkpoint_file_path = os.path.join(
            self.__config.agent_data_path, "checkpoints.json"
        )

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
            active_checkpoint_file_path = os.path.join(
                self.__config.agent_data_path, "active-checkpoints.json"
            )

            if not os.path.isfile(active_checkpoint_file_path):
                return full_checkpoints

            # if the active checkpoint file is newer, overwrite any checkpoint values with the
            # updated full checkpoint
            active_checkpoints = scalyr_util.read_file_as_json(
                active_checkpoint_file_path, strict_utf8=True
            )

            if active_checkpoints["time"] > full_checkpoints["time"]:
                full_checkpoints["time"] = active_checkpoints["time"]
                full_checkpoints["checkpoints"].update(
                    active_checkpoints["checkpoints"],
                )

            return full_checkpoints

        except Exception:
            # TODO:  Fix read_file_as_json so that it will not return an exception.. or will return a specific one.
            log.exception(
                "Could not read checkpoint file due to error. Ignoring checkpoint file.",
                error_code="failedCheckpointRead",
            )
            return None

    def __has_pending_log_changes(self):
        """
        Returns true if there are any pending changes to set of logs being monitored
        """
        self.__lock.acquire()
        try:
            pending_count = (
                len(self.__pending_log_matchers)
                + len(self.__logs_pending_reload)
                + len(self.__logs_pending_removal)
            )
            return pending_count > 0
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
                get_log_processor_factory=self.__get_log_processor_factory,
            ):

                log_path = new_processor.get_log_path()
                self.__log_paths_being_processed[log_path] = new_processor

                # if the log file pending removal, mark that it has now been processed
                if log_path in pending_removal:
                    pending_removal[log_path] = True

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


    def __get_checkpoints(self, current_time):
        """Find and read worker checkpoints that were previously written."""

        checkpoints = self.__find_and_read_workers_checkpoints(current_time)

        if not checkpoints:
            log.info(
                "No checkpoints were found. All logs will be copied starting at their current end"
            )

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

        except Exception:
            log.exception(
                "Could not read checkpoint file due to error. Ignoring checkpoint file.",
                error_code="failedCheckpointRead",
            )
            return None

    def _create_worker_pools(self):
        """
        Create a new worker pools for each entry in the 'api_keys' list in the configuration.
        :return:
        """
        for api_key_config in self.__config.api_key_configs:
            pool = ApiKeyWorkerPool(self.__config, api_key_config)
            self._api_keys_worker_pools[api_key_config["id"]] = pool

    def __get_log_processor_factory(self, log_config_entry):
        """
        This method creates a new instance of the LogFileProcessor.
        :return:
        """
        worker = self.__find_best_worker_for_the_log_path(log_config_entry)

        return worker.create_and_add_log_processor

    def __find_best_worker_for_the_log_path(self, log_config_entry):
        # type: (Dict) -> CopyingManagerWorkerContainer
        """
        Find the worker which is appororiate to the given log_config entry. For example if there is a 'api_key_id' field
        in the log entry, we will only pick worker pools with the same api key id.
        """

        # get the workers pool which is responsible for the api key which is specified in the log config
        pool = self._api_keys_worker_pools[log_config_entry["api_key_id"]]
        return pool.find_next_worker()

    def augment_user_agent_for_workers_sessions(self, fragments):
        # type: (List[six.text_type]) -> None
        """
        Modifies User-Agent header of the sessions to all worker.

        @param fragments String fragments to append (in order) to the standard user agent data
        @type fragments: List of six.text_type
        """
        for worker_pool in self._api_keys_worker_pools.values():
            for worker in worker_pool.workers:
                worker.augment_user_agent_for_client_session(fragments)

    def get_worker_session_statuses(self):
        # type: () -> List[ScalyrClientSessionStatus]
        """
        Get session statuses from all workers.
        :return: dict with worker_id -> ScalyrClientSessionStatus.
        """
        session_stats = []
        for worker_pool in self._api_keys_worker_pools.values():
            for worker in worker_pool.workers:
                session_stats.append(worker.generate_scalyr_client_status())

        return session_stats