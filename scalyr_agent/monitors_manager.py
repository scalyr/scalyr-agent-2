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
# author: Steven Czerwinski <czerwin@scalyr.com>
from __future__ import unicode_literals
from __future__ import absolute_import

if False:  # NOSONAR
    from typing import List

__author__ = "czerwin@scalyr.com"

import os
import time

from scalyr_agent.agent_status import MonitorManagerStatus
from scalyr_agent.agent_status import MonitorStatus
from scalyr_agent.scalyr_monitor import load_monitor_class, ScalyrMonitor
from scalyr_agent.util import StoppableThread
from scalyr_agent.configuration import Configuration
from scalyr_agent.platform_controller import PlatformController

from scalyr_agent.__scalyr__ import get_package_root

import scalyr_agent.scalyr_logging as scalyr_logging

import six

log = scalyr_logging.getLogger(__name__)


class MonitorsManager(StoppableThread):
    """Maintains the list of currently running ScalyrMonitor instances and allows control to start and stop them.

    Also periodically polls all monitors for user-agent fragments that are then immediately reflected in all requests
    sent to Scalyr.
    """

    def __init__(self, configuration, platform_controller):
        """Initializes the manager.
        @param configuration: The agent configuration that controls what monitors should be run.
        @param platform_controller:  The controller for this server.

        @type configuration: scalyr_agent.Configuration
        @type platform_controller: scalyr_agent.platform_controller.PlatformController
        """
        StoppableThread.__init__(self, name="monitor manager thread")
        if configuration.disable_monitors_creation:
            log.log(
                scalyr_logging.DEBUG_LEVEL_0,
                "Creation of Scalyr Monitors disabled.  No monitors created.",
            )
            self.__monitors = []
        else:
            self.__monitors = MonitorsManager.__create_monitors(
                configuration, platform_controller
            )

        self.__disable_monitor_threads = configuration.disable_monitor_threads

        self.__running_monitors = []
        self.__user_agent_callback = None
        self._user_agent_refresh_interval = configuration.user_agent_refresh_interval

    def find_monitor(self, module_name):
        """Finds a monitor with a specific name
           @param module_name: the module name of the monitor to find
           @return: a monitor object if a monitor matches `module_name`, or None
        """
        for monitor in self.__monitors:
            if monitor.module_name == module_name:
                return monitor

        return None

    def generate_status(self):
        """Creates and returns a status object that reports the monitor status.

        @return:  The status for all the monitors.
        @rtype: MonitorManagerStatus
        """
        result = MonitorManagerStatus()

        for monitor in self.__monitors:
            if monitor.isAlive():
                result.total_alive_monitors += 1

            status = MonitorStatus()
            status.monitor_name = monitor.monitor_name
            status.reported_lines = monitor.reported_lines()
            status.errors = monitor.errors()
            status.is_alive = monitor.isAlive()

            result.monitors_status.append(status)

        return result

    def start_manager(self):
        """Starts all of the required monitors running.

        Each monitor will run in its own thread.  This method will return after all of the monitor threads
        have been started.
        """

        # TODO:  Move this try statement out of here.  Let higher layers catch it.
        # noinspection PyBroadException
        try:
            for monitor in self.__monitors:
                # Debug Leaks
                if self.__disable_monitor_threads:
                    log.log(
                        scalyr_logging.DEBUG_LEVEL_0,
                        "Scalyr Monitors disabled.  Skipping %s" % monitor.monitor_name,
                    )
                    continue
                # Check to see if we can open the metric log.  Maybe we should not silently fail here but instead fail.
                if monitor.open_metric_log():
                    monitor.config_from_monitors(self)
                    log.info("Starting monitor %s", monitor.monitor_name)

                    # NOTE: Workaround for a not so great behavior with out code where we create
                    # thread instances before forking. This causes issues because "_is_stopped"
                    # instance attribute gets set to "True" and never gets reset to "False". This
                    # means isAlive() will correctly return that the threat is not alive is it was
                    # created before forking.
                    # See the following for details:
                    #
                    # - https://github.com/python/cpython/blob/3.7/Lib/threading.py#L800
                    # - https://github.com/python/cpython/blob/3.7/Lib/threading.py#L806
                    # - https://github.com/python/cpython/blob/3.7/Lib/threading.py#L817
                    #
                    # Long term and correct solution is making sure we don't create any threads
                    # before we fork
                    if six.PY3:
                        monitor._is_stopped = False

                    monitor.start()

                    self.__running_monitors.append(monitor)
                else:
                    log.warn(
                        "Could not start monitor %s because its log could not be opened",
                        monitor.monitor_name,
                    )
            # Start the monitor manager thread. Do not wait for all monitor threads to start as some may misbehave
            if not self.__disable_monitor_threads:
                log.log(
                    scalyr_logging.DEBUG_LEVEL_0,
                    "Starting Scalyr Monitors manager thread",
                )
                self.start()
            else:
                log.log(
                    scalyr_logging.DEBUG_LEVEL_0,
                    "Scalyr Monitors disabled.  Skipping monitor manager thread",
                )
        except Exception:
            log.exception("Failed to start the monitors due to an exception")

    def stop_manager(self, wait_on_join=True, join_timeout=5):
        """Stops all of the monitors.

        This will only return after all the threads for the monitors have been stopped and joined on.

        @param wait_on_join: If True, will block on a join of of the thread running the manager.
        @param join_timeout: The maximum number of seconds to block for the join.
        """
        # TODO:  Move these try statements out of here.  Let higher layers catch it.

        start_time = time.time()

        for monitor in self.__running_monitors:
            # noinspection PyBroadException
            try:
                log.info("Stopping monitor %s", monitor.monitor_name)
                monitor.stop(wait_on_join=False)
            except Exception:
                log.exception(
                    "Failed to stop the metric log without join due to an exception"
                )

        if wait_on_join:
            for monitor in self.__running_monitors:
                max_wait = start_time + join_timeout - time.time()
                if max_wait <= 0:
                    break
                # noinspection PyBroadException
                try:
                    monitor.stop(join_timeout=max_wait)
                except Exception:
                    log.exception("Failed to stop the metric log due to an exception")

        for monitor in self.__running_monitors:
            # noinspection PyBroadException
            try:
                monitor.close_metric_log()
            except Exception:
                log.exception("Failed to close the metric log due to an exception")

        self.stop(wait_on_join=wait_on_join, join_timeout=join_timeout)

    def set_user_agent_augment_callback(self, callback):
        """Registers a callback that, when invoked, will augment the User-Agent.

        The callback should be passed a single list of string fragments which will be appended in order.

        This method is not thread safe so it must be invoked before self.start_manager()
        """
        self.__user_agent_callback = callback

    def run(self):
        """Poll monitors for User-Agent fragment. Only modify user-agent on any changes."""

        prev_user_agent_frags = None

        # noinspection PyBroadException
        while self._run_state.is_running():
            # noinspection PyBroadException
            try:
                # noinspection PyBroadException
                try:
                    # Invoke user-agent callback only if the fragments have changed
                    user_agent_frags = set()
                    for monitor in self.__running_monitors:
                        frag = monitor.get_user_agent_fragment()
                        if frag:
                            user_agent_frags.add(frag)
                    if user_agent_frags != prev_user_agent_frags:
                        self.__user_agent_callback(sorted(user_agent_frags))
                    prev_user_agent_frags = user_agent_frags
                except Exception:
                    log.exception(
                        "Monitor manager failed to query monitor %s"
                        % monitor.monitor_name
                    )
                self._run_state.sleep_but_awaken_if_stopped(
                    self._user_agent_refresh_interval
                )
            except Exception:
                log.exception(
                    "Monitor manager failed due to exception", limit_once_per_x_secs=300
                )

    @property
    def monitors(self):
        """Returns the list of all monitors that should be run by this manager.

        @return: The monitors.  You should not modify this list.
        @rtype: list<ScalyrMonitor>
        """
        return self.__monitors

    @staticmethod
    def __create_monitors(configuration, platform_controller):
        """Creates instances of the monitors that should be run based on the contents of the configuration file
        and the platform controller.

        @param configuration: The agent configuration that controls what monitors should be run.
        @param platform_controller:  The controller for this server.  It may have default monitors that should be run.

        @type configuration: scalyr_agent.Configuration
        @type platform_controller: scalyr_agent.platform_controller.PlatformController
        """
        all_monitors = MonitorsManager._get_all_monitor_configs(
            configuration, platform_controller
        )

        # We need to go back and fill in the monitor id if it is not set.  We do this by keeping a count of
        # how many monitors we have with the same module name (just considering the last element of the module
        # path).  We use the shortened form of the module name because that is used when emitting lines for
        # this monitor in the logs -- see scalyr_logging.py.
        monitors_by_module_name = {}
        # Tracks which modules already had an id present in the module config.
        had_id = {}

        for entry in all_monitors:
            module_name = entry["module"].split(".")[-1]
            if module_name not in monitors_by_module_name:
                index = 1
            else:
                index = monitors_by_module_name[module_name] + 1
            if "id" not in entry:
                entry["id"] = index
            else:
                had_id[module_name] = True

            monitors_by_module_name[module_name] = index

        # Just as a simplification, if there is only one monitor with a given name, we remove the monitor_id
        # to clean up it's name in the logs.
        for entry in all_monitors:
            module_name = entry["module"].split(".")[-1]
            if monitors_by_module_name[module_name] == 1 and module_name not in had_id:
                entry["id"] = ""

        result = []

        for entry in all_monitors:
            # we pass the configuration separately even though additional paths and sample interval come
            # from there, because other places (e.g. run_standalone_monitor) may call build_monitor with
            # values for those that don't come from a configuration file
            result.append(
                MonitorsManager.build_monitor(
                    entry,
                    configuration.additional_monitor_module_paths,
                    configuration.global_monitor_sample_interval,
                    configuration,
                )
            )
        return result

    @staticmethod
    def load_monitor(monitor_module, additional_python_paths):
        """Loads the module for the specified monitor.

        @param monitor_module: The module for the monitor.
        @param additional_python_paths: A list of paths (separate by os.pathsep) to add to the PYTHONPATH when
            instantiating the module in case it needs to packages in other directories.

        @type monitor_module: six.text_type
        @type additional_python_paths: six.text_type

        @return:  The class for the ScalyrMonitor in the module.
        @rtype: class
        """
        # Augment the PYTHONPATH if requested to locate the module.
        paths_to_pass = []

        # Also add in scalyr_agent/../monitors/local and scalyr_agent/../monitors/contrib to the Python path to search
        # for monitors.  (They are always in the parent directory of the scalyr_agent package.
        path_to_package_parent = os.path.dirname(get_package_root())
        paths_to_pass.append(os.path.join(path_to_package_parent, "monitors", "local"))
        paths_to_pass.append(
            os.path.join(path_to_package_parent, "monitors", "contrib")
        )

        # Add in the additional paths.
        if additional_python_paths is not None and len(additional_python_paths) > 0:
            for x in additional_python_paths.split(os.pathsep):
                paths_to_pass.append(x)

        return load_monitor_class(monitor_module, os.pathsep.join(paths_to_pass))[0]

    @staticmethod
    def build_monitor(
        monitor_config,
        additional_python_paths,
        default_sample_interval_secs,
        global_config,
    ):
        """Builds an instance of a ScalyrMonitor for the specified monitor configuration.

        @param monitor_config: The monitor configuration object for the monitor that should be created.  It will
            have keys such as 'module' that specifies the module containing the monitor, as well as others.
        @param additional_python_paths: A list of paths (separate by os.pathsep) to add to the PYTHONPATH when
            instantiating the module in case it needs to packages in other directories.
        @param global_config: The global configuration object

        @type monitor_config: dict
        @type additional_python_paths: six.text_type

        @return:  The appropriate ScalyrMonitor instance as controlled by the configuration.
        @rtype: scalyr_monitor.ScalyrMonitor
        """
        # Set up the logs to do the right thing.
        module_name = monitor_config["module"]
        monitor_id = monitor_config["id"]

        # We have to update this variable before we create monitor instances so that it is used.
        ScalyrMonitor.DEFAULT_SAMPLE_INTERVAL_SECS = default_sample_interval_secs

        # Load monitor.
        monitor_class = MonitorsManager.load_monitor(
            module_name, additional_python_paths
        )

        # Instantiate and initialize it.
        return monitor_class(
            monitor_config,
            scalyr_logging.getLogger("%s(%s)" % (module_name, monitor_id)),
            global_config=global_config,
        )

    @staticmethod
    def _get_all_monitor_configs(configuration, platform_controller):
        # type: (Configuration, PlatformController) -> List[dict]
        """
        Return monitor config dictionaries for all the monitors, including the built it ones.
        """
        # Get all the monitors we will be running.  This is determined by the config file and the platform's default
        # monitors.  This is a just of json objects containing the configuration.  We get json objects because we
        # may need to modify them.
        all_monitors = []

        for monitor in configuration.monitor_configs:
            all_monitors.append(monitor.copy())

        for monitor in platform_controller.get_default_monitors(configuration):
            all_monitors.append(
                configuration.parse_monitor_config(
                    monitor,
                    'monitor with module name "%s" requested by platform'
                    % monitor["module"],
                ).copy()
            )

        return all_monitors
