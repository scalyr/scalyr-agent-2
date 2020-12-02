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
import operator
from six.moves import range

if False:
    from typing import Dict
    from typing import List
    from typing import Optional
    from typing import Tuple
    from typing import Set
    from typing import Any

from scalyr_agent import (
    scalyr_logging as scalyr_logging,
    StoppableThread,
    util as scalyr_util,
)
from scalyr_agent.agent_status import (
    ShardedCopyingManagerStatus,
    ApiKeyWorkerPoolStatus,
)
from scalyr_agent.sharded_copying_manager.worker import (
    CopyingManagerThreadedWorker,
    SharedObjectManager,
)
from scalyr_agent.log_processing import LogMatcher, LogFileProcessor
from scalyr_agent.log_watcher import LogWatcher
from scalyr_agent.util import max_ignore_none
from scalyr_agent.configuration import Configuration
from scalyr_agent.scalyr_client import ScalyrClientSessionStatus
from scalyr_agent.sharded_copying_manager.common import write_checkpoint_state_to_file

import six

log = scalyr_logging.getLogger(__name__)

SCHEDULED_DELETION = "scheduled-deletion"
CHECKPOINTS_MASTER_FILE_NAME = "checkpoints-master.json"


def _accumulate_worker_stats(
    stats, result_on_at_least_one_fail=False, result_on_all_succeed=True
):
    # type: (Set, Optional[Any], Optional[Any]) -> Optional[bool]
    """
    Gets a set of elements, where each element may be True, False or None and verifies them following the next logic:
        - If there is at least one 'False' then the whole result is 'result_on_at_least_one_fail'.
        - If there is at least one 'None' and no any 'False' then the whole result is 'None'.
        - If all elements are 'True' then the result is 'result_on_all_succeed'
    """
    if False in stats:
        # First of all we check for failed stats. If there is at least one, the whole result in failed too.
        return result_on_at_least_one_fail
    elif None in stats:
        # Only if there are no failed stats...
        # If there is at least one unknown response. the whole result in unknown too.
        return None
    else:
        # all successful, the result is successful too.
        return result_on_all_succeed


class ApiKeyWorkerPool(object):
    """
    This abstraction is responsible for maintaining the workers
    for a particular entry in the 'api_keys' list in the configuration.
    It also creates worker instances according to the number in the "workers" field in each entry.
    Depending on workers type (multiprocess or not), it will operate with
    instances of the CopyingManagerWorker or their proxy objects.

    The instances if this class itself live only in the original process,
    controlled by the copying manager and do not have any proxy versions.
    """

    def __init__(self, config, api_key_config):
        # type: (Configuration, Dict) -> None

        self.__api_key_id = api_key_config["id"]
        self.__config = config

        self.__workers = []  # type: List[CopyingManagerThreadedWorker]

        # collection of shared object managers. (Subclasses of the multiprocessing.BaseManager)
        # Those managers allow to communicate with workers if they are in the multiprocessing mode.
        self.__shared_object_managers = (
            dict()
        )  # type: Dict[six.text_type, SharedObjectManager]

        for i in range(api_key_config["workers"]):
            # combine the id of the api key and worker's position in the list to get a workers id.
            worker_id = "%s_%s" % (self.__api_key_id, i)

            if not self.__config.use_multiprocess_copying_workers:
                worker = CopyingManagerThreadedWorker(
                    self.__config, api_key_config, worker_id
                )
            else:
                shared_object_manager = SharedObjectManager()

                # Important for the understanding. When the shared_object_manager is started, it creates a new process.
                # We use this process as a process for the worker.

                worker_agent_log_path = os.path.join(
                    self.__config.agent_log_path, "agent-%s.log" % worker_id
                )

                # change agent log path for the new worker.
                # this initializer function will be invoked in the worker's process.
                def initializer():
                    self._change_worker_process_agent_log_path(worker_agent_log_path)

                shared_object_manager.start(initializer=initializer)

                # create proxy object of the worker. The real worker instance is created in the new process
                # which was created when shared_object_manager started.
                # pylint: disable=E1101
                worker = shared_object_manager.CopyingManagerWorkerProxy(
                    self.__config, api_key_config, worker_id
                )
                # pylint: enable=E1101

                # also save new shared object manager.
                self.__shared_object_managers[worker.get_id()] = shared_object_manager

            self.__workers.append(worker)
            log.log(
                scalyr_logging.DEBUG_LEVEL_1,
                "CopyingManagerWorker #%s is created." % worker.get_id(),
            )

        # The index of the next worker which will be used to handle the log processor.
        self.__current_worker = 0

    def _change_worker_process_agent_log_path(self, path):
        """
        Reconfigure the agent logger, mainly, to change to path of the agent.log file
        for the worker when it is running in the separate thread.
        Multiple concurrent processes that write to the same 'agent.log' file may cause an incorrect results, so,
        to be on a safe side, we just create separate agent-<worker_id>.log files for each worker.
        """
        scalyr_logging.set_log_destination(agent_log_file_path=path, use_disk=True)

    @property
    def api_key_id(self):
        return self.__api_key_id

    @property
    def workers(self):
        return self.__workers

    def __find_next_worker(self):
        # type: () -> CopyingManagerThreadedWorker
        """Get the next worker in the pool. For now it is just a round robin."""
        current_worker = self.__workers[self.__current_worker]
        if self.__current_worker == len(self.__workers) - 1:
            self.__current_worker = 0
        else:
            self.__current_worker += 1

        return current_worker

    def create_and_add_new_log_processor(self, *args, **kwargs):
        # type: (Tuple, Dict) -> LogFileProcessor
        """
        Find the next worker in the pool and make it to create and schedule a log processor.
        The the arguments will be eventually passed to the LogFileProcessor's constructor.
        :return: New log processor
        """
        worker = self.__find_next_worker()
        log_processor = worker.create_and_schedule_new_log_processor(*args, **kwargs)

        return log_processor

    def start_workers_and_block_until_copying(self):
        # type: () -> None
        """
        Start all workers in the pool and wait until they started copying.
        """
        for worker in self.__workers:
            worker.start_worker()

        for worker in self.__workers:
            worker.wait_for_copying_to_begin()

    def stop_workers(self, wait_on_join=True, join_timeout=5):
        # type: (bool, int) -> None
        for worker in self.__workers:
            try:
                worker.stop_worker(wait_on_join=wait_on_join, join_timeout=join_timeout)
            except:
                log.exception("Can not stop the worker '%s'." % worker.get_id())

        self._stop_shared_object_managers()

    def _stop_shared_object_managers(self):
        """
        Stop all shared object managers.
        This is moved to the separate function to be able to override it for the testing purposes
        because we may need to get data from workers even if copying manager and worker pools are stopped.
        :return:
        """
        # also stop all shared object managers.
        for worker_id, memory_manager in self.__shared_object_managers.items():
            try:
                memory_manager.shutdown()
            except:
                log.exception(
                    "Can not stop shared object manager for the worker '%s'."
                    % worker_id
                )

    def generate_status(self, warn_on_rate_limit=False):
        # type: (bool) -> ApiKeyWorkerPoolStatus
        """Generate status of the worker pool."""
        result = ApiKeyWorkerPoolStatus()

        result.api_key_id = self.__api_key_id

        worker_statuses = [
            ws.generate_status(warn_on_rate_limit=warn_on_rate_limit)
            for ws in sorted(self.__workers, key=lambda w: w.get_id())
        ]

        result.workers = worker_statuses

        for status in worker_statuses:
            # get the most recent time fields from workers.
            if status.last_success_time:
                result.last_success_time = max_ignore_none(
                    result.last_success_time, status.last_success_time
                )
            if status.last_attempt_time:
                result.last_attempt_time = max_ignore_none(
                    result.last_attempt_time, status.last_attempt_time
                )

            # the next fields are a sum of the same fields from all workers.
            if status.last_attempt_size:
                result.last_attempt_requests_overall_size += status.last_attempt_size

            result.total_bytes_uploaded += status.total_bytes_uploaded

            result.total_errors += status.total_errors

        # get overall information about last responses of all workers in the worker pool.
        # making this as a set should help in further decision making process.
        # we follow the next algorithm:
        #   - if all request are successful, then the result is successful too.
        #   - if at least one response status is still None, and other are successful, then the result is None too.
        # In other words, we wait until all workers has gotten their first responses.
        #   - if at least one response status is unsuccessful, then the result is unsuccessful too,
        # and it does not matter if there are any unknown (None) values.

        responses = set()
        for s in worker_statuses:
            if s.last_response_status is not None:
                # compare each response status for "success" and store the boolean result.
                responses.add(s.last_response_status == "success")
            else:
                #  we do not compare None values, they are stored as are.
                # The None value says that not all workers have worked enough to get their first responses,
                responses.add(None)

        result.all_responses_successful = _accumulate_worker_stats(responses)

        # do the same thing with health checks as we did with responses
        health_checks = set()
        for s in worker_statuses:
            if s.health_check_result is not None:
                health_checks.add(s.health_check_result == "Good")
            else:
                health_checks.add(None)

        result.all_health_checks_good = _accumulate_worker_stats(health_checks)

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
        self.__config = configuration  # type: Configuration

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
        self.__total_scan_iterations = 0

        # A worker pools for each api key in the 'api_keys' list in the configuration.
        self.__api_keys_worker_pools = (
            dict()
        )  # type: Dict[six.text_type, ApiKeyWorkerPool]

        # The list of LogMatcher objects that are watching for new files to appear.
        # NOTE: log matchers must be created only after worker pools.
        self.__log_matchers = self.__create_log_matches(
            self.__config, self.__monitors
        )  # type: List[LogMatcher]

    @property
    def expanded_server_attributes(self):
        """Return deepcopy of expanded server attributes"""
        return copy.deepcopy(self.__expanded_server_attributes)

    # region The following methods are only exposed for the test purposes.
    @property
    def log_matchers(self):
        """Returns the list of log matchers that were created based on the configuration and passed in monitors.

        This is really only exposed for testing purposes.

        @return: The log matchers.
        @rtype: list<LogMatcher>
        """
        return self.__log_matchers

    @property
    def api_keys_worker_pools(self):
        # type: () -> Dict
        """
        Get dict with api key worker pools. Only exposed for testing purposes.
        """
        return self.__api_keys_worker_pools

    @property
    def config(self):
        # type: () -> Configuration
        """
        Only exposed for testing purposes.
        """
        return self.__config

    # endregion

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
            result.append(LogMatcher(configuration, log_config))

        return result

    def start_manager(self, logs_initial_positions=None):
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
                # prepare and read checkpoints.
                self.__consolidate_checkpoints()
                checkpoints = self.__find_and_read_checkpoints()

                log.info("Starting copying manager workers.")

                # create copying workers according to settings in the configuration.
                self._create_worker_pools()

                # gather and merge all checkpoints from all active workers( or workers from previous launch)
                # into single checkpoints object.

                # start all workers.
                for worker_pool in self.__api_keys_worker_pools.values():
                    worker_pool.start_workers_and_block_until_copying()

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
                for worker_pool in self.__api_keys_worker_pools.values():
                    workers_count += len(worker_pool.workers)

                log.info(
                    "Copying manager started. Total workers: %s, Pid: %s"
                    % (workers_count, os.getpid())
                )

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
                        self.__last_scan_attempt_time = current_time
                        self.__total_errors += 1
                        self.__lock.release()

                    self._sleep_but_awaken_if_stopped(
                        self.__config.max_request_spacing_interval
                    )

                    # End of the copy loop
                    self.__total_scan_iterations += 1
            except Exception:
                # If we got an exception here, it is caused by a bug in the program, so let's just terminate.
                log.exception("Log copying failed due to exception")
                # there may a rare case where an unrecoverable error
                # is occurred before the  semaphore is released
                # and the original thread is still waiting for it.
                self.__copying_semaphore.release()
                sys.exit(1)
        finally:
            # stopping all workers.
            for worker_pool in self.__api_keys_worker_pools.values():
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

            result.total_scan_iterations = self.__total_scan_iterations

            # list with all possible health check error messages.
            all_health_check_error_messages = list()

            api_key_statuses = [
                self.__api_keys_worker_pools[api_key_id].generate_status(
                    warn_on_rate_limit=warn_on_rate_limit
                )
                for api_key_id in sorted(self.__api_keys_worker_pools)
            ]

            result.api_key_worker_pools = api_key_statuses

            for status in api_key_statuses:

                result.total_errors += status.total_errors
                result.total_bytes_uploaded += status.total_bytes_uploaded

            # get responses information from worker pools
            responses = set(s.all_responses_successful for s in api_key_statuses)

            result.last_responses_status_info = _accumulate_worker_stats(
                responses,
                result_on_at_least_one_fail="Last requests on some workers is not successful, see below for more info.",
                result_on_all_succeed="All successful",
            )

            # Get the workers health checks the same way as responses.
            worker_health_checks = {s.all_health_checks_good for s in api_key_statuses}

            workers_health_check_successful = _accumulate_worker_stats(
                worker_health_checks,
            )

            # if the workers health check is failed, then we add the error message about that.
            if workers_health_check_successful is False:
                all_health_check_error_messages.append(
                    "Some workers has failed, see below for more info.",
                )

            # do the health check of the copying manager itself.
            copying_manager_health_check_successful = None
            if self.__last_scan_attempt_time:
                if (
                    time.time()
                    > self.__last_scan_attempt_time
                    # TODO: create new config value for that.
                    + self.__config.healthy_max_time_since_last_copy_attempt
                ):
                    copying_manager_health_check_successful = False
                    # if there is a bad health check if the copying manager itself, add the error message about that.
                    # Note: the information about the copying manager itself should be shown first.
                    all_health_check_error_messages.insert(
                        0,
                        "Failed, max time since last scan attempt (%s seconds) exceeded"
                        % self.__config.healthy_max_time_since_last_copy_attempt,
                    )
                else:
                    copying_manager_health_check_successful = True

            # get the final health check result from the workers health check and copying manager health check.
            result.health_check_result = _accumulate_worker_stats(
                {
                    copying_manager_health_check_successful,
                    workers_health_check_successful,
                },
                result_on_at_least_one_fail="\n".join(all_health_check_error_messages),
                result_on_all_succeed="Good",
            )

            # get statuses for the log matchers.
            for entry in self.__log_matchers:
                result.log_matchers.append(entry.generate_status())

            # sum up some worker stats to overall stats.
            for api_key_status in api_key_statuses:
                for worker_status in api_key_status.workers:
                    result.total_rate_limited_time = (
                        worker_status.total_rate_limited_time
                    )
                    result.total_read_time = worker_status.total_read_time
                    result.total_waiting_time = worker_status.total_waiting_time
                    result.total_blocking_response_time = (
                        worker_status.total_blocking_response_time
                    )
                    result.total_request_time = worker_status.total_request_time
                    result.total_pipelined_requests = (
                        worker_status.total_pipelined_requests
                    )
                    result.rate_limited_time_since_last_status = (
                        worker_status.rate_limited_time_since_last_status
                    )

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

        checkpoints = self.__find_and_read_checkpoints()

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
        # type: (List[LogMatcher], Optional[Dict], bool) -> None
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
            # get the worker pool which is responsible for this log matcher.
            worker_pool = self.__api_keys_worker_pools[
                matcher.log_entry_config.get("api_key_id")
            ]
            for new_processor in matcher.find_matches(
                self.__log_paths_being_processed,
                checkpoints,
                copy_at_index_zero=copy_at_index_zero,
                # this method of the worker pool will be called on every new match,
                # to create and add new log processors to workers.
                create_log_processor=worker_pool.create_and_add_new_log_processor,
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

    def __consolidate_checkpoints(self):
        """
        Combines all worker checkpoints that were left from the previous agent run.
        It combines checkpoint files into one single file in order to
        allow workers to rewrite the content of this files without losing any data.
        """

        # read all checkpoints from the manager's previous run and combine them into one mater file.
        checkpoints = self.__find_and_read_checkpoints()

        master_checkpoints_path = os.path.join(
            self.__config.agent_data_path, CHECKPOINTS_MASTER_FILE_NAME,
        )
        write_checkpoint_state_to_file(
            checkpoints, master_checkpoints_path, time.time()
        )

        # clear the checkpoints folder by removing all worker checkpoint files.
        # NOTE: we also look at the parent directory
        # in case if there are checkpoint files from an older version of the agent.
        checkpoints_glob = os.path.join(
            self.__config.agent_data_path, "*checkpoints*.json"
        )

        for path in scalyr_util.match_glob(checkpoints_glob):
            # do not delete master checkpoint file
            if path == master_checkpoints_path:
                continue
            os.unlink(path)

    def __find_and_read_checkpoints(self):
        # type: () -> Dict
        """
        Find and read checkpoints that were previously written.
        During its work, the worker writes its own checkpoint files,
        the copying manager reads them and combines into one checkpoints dict.
        :return: Checkpoint state stored in dict.
        """

        found_checkpoints = []

        current_time = time.time()

        # also search in the parent directory in case if there are checkpoint files from older versions.
        glob_path = os.path.join(self.__config.agent_data_path, "checkpoints*.json")

        for checkpoints_path in scalyr_util.match_glob(glob_path):

            checkpoints = self.__read_checkpoint_state(checkpoints_path, current_time)

            if checkpoints:
                found_checkpoints.append(checkpoints)

        if len(found_checkpoints) == 0:
            log.info(
                "No checkpoints were found. All logs will be copied starting at their current end"
            )

            return {}

        result = {}
        # merge checkpoints from  all workers to one checkpoint.

        # checkpoints from different workers may contain checkpoint for the same file,
        # so we sort checkpoints by time and update resulting collection with the same order.
        found_checkpoints.sort(key=operator.itemgetter("time"))

        for wc in found_checkpoints:
            result.update(wc["checkpoints"])

        return result

    def __read_checkpoint_state(self, full_checkpoints_path, current_time):
        # type: (six.text_type, float) -> Optional[Dict]
        """Reads a single checkpoint state from the file on the disk and returns it.

        The checkpoint state maps each file path to the offset within that log file where we left off copying it.

        @return:  The checkpoint state
        @rtype: dict
        """

        if not os.path.isfile(full_checkpoints_path):
            return None

        # noinspection PyBroadException
        try:
            full_checkpoints = scalyr_util.read_file_as_json(
                full_checkpoints_path, strict_utf8=True
            )

            # get the path for the active checkpoints file
            parent_dir, filename = os.path.split(full_checkpoints_path)
            active_checkpoints_filename = "active-%s" % os.path.basename(filename)
            active_checkpoints_path = os.path.join(
                parent_dir, active_checkpoints_filename
            )

            if os.path.isfile(active_checkpoints_path):
                # if the active checkpoint file is newer, overwrite any checkpoint values with the
                # updated full checkpoint
                active_checkpoints = scalyr_util.read_file_as_json(
                    active_checkpoints_path, strict_utf8=True
                )

                if active_checkpoints["time"] > full_checkpoints["time"]:
                    full_checkpoints["time"] = active_checkpoints["time"]
                    full_checkpoints["checkpoints"].update(
                        active_checkpoints["checkpoints"]
                    )

            if (
                current_time - full_checkpoints["time"]
                > self.__config.max_allowed_checkpoint_age
            ):
                log.warn(
                    "The worker checkpoint file '%s' is too stale (written at '%s').  Ignoring it.  The log files will "
                    "be copied starting at their current end.",
                    full_checkpoints_path,
                    scalyr_util.format_time(full_checkpoints["time"]),
                    error_code="staleCheckpointFile",
                )

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
            self.__api_keys_worker_pools[api_key_config["id"]] = pool

    def augment_user_agent_for_workers_sessions(self, fragments):
        # type: (List[six.text_type]) -> None
        """
        Modifies User-Agent header of the sessions to all worker.

        @param fragments String fragments to append (in order) to the standard user agent data
        @type fragments: List of six.text_type
        """
        for worker_pool in self.__api_keys_worker_pools.values():
            for worker in worker_pool.workers:
                worker.augment_user_agent_for_client_session(fragments)

    def get_worker_session_statuses(self):
        # type: () -> List[ScalyrClientSessionStatus]
        """
        Get session statuses from all workers.
        :return: dict with worker_id -> ScalyrClientSessionStatus.
        """
        session_stats = []
        for worker_pool in self.__api_keys_worker_pools.values():
            for worker in worker_pool.workers:
                session_stats.append(worker.generate_scalyr_client_status())

        return session_stats
