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

__author__ = 'czerwin@scalyr.com'

import os
import threading

from scalyr_agent.agent_status import MonitorManagerStatus
from scalyr_agent.agent_status import MonitorStatus
from scalyr_agent.scalyr_monitor import load_monitor_class

from __scalyr__ import get_package_root

import scalyr_agent.scalyr_logging as scalyr_logging

log = scalyr_logging.getLogger(__name__)


class MonitorsManager(object):
    """Maintains the list of currently running ScalyrMonitor instances and allows control to start and stop them."""
    def __init__(self, configuration):
        """Initializes the manager.
        @param configuration: The agent configuration that controls what monitors should be run.
        @type configuration: scalyr_agent.Configuration
        """
        self.__config = configuration
        self.__monitors = configuration.monitors
        # This lock protects __running_monitors.
        self.__lock = threading.Lock()
        # The list of monitors.  Each element is a ScalyrMonitor instance.  __lock must be held to modify this var.
        self.__running_monitors = []

    def generate_status(self):
        """Creates and returns a status object that reports the monitor status.

        @return:  The status for all the monitors.
        @rtype: MonitorManagerStatus
        """
        try:
            self.__lock.acquire()
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
        finally:
            self.__lock.release()

    def start(self):
        """Starts all of the required monitors running.

        Each monitor will run in its own thread.  This method will return after all of the monitor threads
        have been started.
        """
        # TODO:  Move this try statement out of here.  Let higher layers catch it.
        # noinspection PyBroadException
        try:
            for monitor in self.__monitors:
                # Check to see if we can open the metric log.  Maybe we should not silently fail here but instead
                # fail.
                if monitor.open_metric_log():
                    log.info('Starting monitor %s', monitor.monitor_name)
                    monitor.start()
                    self.__running_monitors.append(monitor)
                else:
                    log.warn('Could not start monitor %s because its log cold not be opened', monitor.monitor_name)
        except:
            log.exception('Failed to start the monitors due to an exception')

    def stop(self):
        """Stops all of the monitors.

        This will only return after all the threads for the monitors have been stopped and joined on.
        """
        # TODO:  Move this try statement out of here.  Let higher layers catch it.
        # noinspection PyBroadException
        try:
            for monitor in self.__running_monitors:
                log.info('Stopping monitor %s', monitor.monitor_name)
                monitor.stop(wait_on_join=False)

            for monitor in self.__running_monitors:
                monitor.stop(join_timeout=1)
                monitor.close_metric_log()
        except:
            log.exception('Failed to stop the monitors due to an exception')

    @staticmethod
    def load_monitor(monitor_module, additional_python_paths):
        """Loads the module for the specified monitor.

        @param monitor_module: The module for the monitor.
        @param additional_python_paths: A list of paths (separate by os.pathsep) to add to the PYTHONPATH when
            instantiating the module in case it needs to packages in other directories.

        @type monitor_module: str
        @type additional_python_paths: str

        @return:  The class for the ScalyrMonitor in the module.
        @rtype: class
        """
        # Augment the PYTHONPATH if requested to locate the module.
        paths_to_pass = []

        # Also add in scalyr_agent/../monitors/local and scalyr_agent/../monitors/contrib to the Python path to search
        # for monitors.  (They are always in the parent directory of the scalyr_agent package.
        path_to_package_parent = os.path.dirname(get_package_root())
        paths_to_pass.append(os.path.join(path_to_package_parent, 'monitors', 'local'))
        paths_to_pass.append(os.path.join(path_to_package_parent, 'monitors', 'contrib'))

        # Add in the additional paths.
        if additional_python_paths is not None and len(additional_python_paths) > 0:
            for x in additional_python_paths.split(os.pathsep):
                paths_to_pass.append(x)

        return load_monitor_class(monitor_module, os.pathsep.join(paths_to_pass))[0]

    @staticmethod
    def build_monitor(monitor_config, additional_python_paths):
        """Builds an instance of a ScalyrMonitor for the specified monitor configuration.

        @param monitor_config: The monitor configuration object for the monitor that should be created.  It will
            have keys such as 'module' that specifies the module containing the monitor, as well as others.
        @param additional_python_paths: A list of paths (separate by os.pathsep) to add to the PYTHONPATH when
            instantiating the module in case it needs to packages in other directories.

        @type monitor_config: dict
        @type additional_python_paths: str

        @return:  The appropriate ScalyrMonitor instance as controlled by the configuration.
        @rtype: scalyr_monitor.ScalyrMonitor
        """
        # Set up the logs to do the right thing.
        module_name = monitor_config['module']
        monitor_id = monitor_config['id']

        # Load monitor.
        monitor_class = MonitorsManager.load_monitor(module_name, additional_python_paths)

        # Instantiate and initialize it.
        return monitor_class(monitor_config, scalyr_logging.getLogger("%s(%s)" % (module_name, monitor_id)))