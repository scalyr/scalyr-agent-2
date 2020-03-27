#!/usr/bin/env python
#
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
# Tool that can be used to run a single instance of ScalyrMonitor plugin for testing and
# debugging purposes.
#
# Usage:
#
# python -m scalyr_agent.run_monitor [options] monitor_module
#
#   where options are:
#
#    -h, --help            show this help message and exit
#    -p PATH, --monitor-python-path=PATH
#                          Add PATH to the paths searched to find the python
#                          module for the monitor.
#    -c MONITOR_CONFIG, --monitor-config=MONITOR_CONFIG
#                          The JSON object to use for the monitor configuration,
#                          excluding the 'module' field
#    -s INTERVAL, --monitor-sample-interval=INTERVAL
#                          The number of seconds between calls to the monitor's
#                          gather_sample method.
#
# author: Steven Czerwinski <czerwin@scalyr.com>
from __future__ import unicode_literals
from __future__ import absolute_import
from __future__ import print_function

__author__ = "czerwin@scalyr.com"

import signal
import sys
import time

from optparse import OptionParser

# [start of 2->TODO]
# Check for suitability.
# This file can be executed as script and imported as module.
if __name__ == "__main__":
    # run as script, can not import __scalyr__.py as part of the package.
    from __scalyr__ import scalyr_init
else:
    # run as package module.
    # Python3 does not allow to import __scalyr__.py file within the same package just by its name. (PEP 328)
    from scalyr_agent.__scalyr__ import scalyr_init
# [end of 2->TOD0]

scalyr_init()

import six

import scalyr_agent.scalyr_logging as scalyr_logging
import scalyr_agent.util as scalyr_util

from scalyr_agent.monitors_manager import MonitorsManager
from scalyr_agent.scalyr_monitor import BadMonitorConfiguration

from scalyr_agent.configuration import Configuration
from scalyr_agent.platform_controller import PlatformController
from scalyr_agent.json_lib import JsonParseException

log = scalyr_logging.getLogger("scalyr_agent.run_monitor")


def run_standalone_monitor(
    monitor_module,
    monitor_python_path,
    monitor_config,
    monitor_sample_interval,
    monitor_debug_level,
    global_config_path,
):
    """Runs a single plugin monitor instance.

    @param monitor_module: The name of the python module implementing the monitor.
    @param monitor_python_path: The python path to search to find the module.
    @param monitor_config: The monitor configuration object.
    @param monitor_sample_interval: The default to use for the sample interval.
    @param monitor_debug_level: The debug level to use for logging.
    @param global_config_path:  The path to the agent.json global configuration file to use, or None if none was
        supplied.
    """
    scalyr_logging.set_log_destination(use_stdout=True)
    scalyr_logging.set_log_level(monitor_debug_level)

    log.log(scalyr_logging.DEBUG_LEVEL_1, "Attempting to run module %s", monitor_module)

    try:
        # Needs to be json_lib.parse because it is parsing configuration
        parsed_config = scalyr_util.json_scalyr_config_decode(monitor_config)
        log.log(scalyr_logging.DEBUG_LEVEL_1, "Parsed configuration successfully")
    except JsonParseException as e:
        print(
            "Failed to parse the monitor configuration as valid JSON: %s",
            six.text_type(e),
            file=sys.stderr,
        )
        return 1

    parsed_config["module"] = monitor_module
    if "id" not in parsed_config:
        parsed_config["id"] = ""

    # noinspection PyUnusedLocal
    def handle_shutdown_signal(signum, frame):
        print("Signal received, stopping monitor...", file=sys.stdout)
        monitor.stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, handle_shutdown_signal)

    try:
        if global_config_path is not None:
            controller = PlatformController.new_platform()
            paths = controller.default_paths
            global_config = Configuration(global_config_path, paths, log)
            global_config.parse()
        else:
            global_config = None
        monitor = MonitorsManager.build_monitor(
            parsed_config,
            monitor_python_path,
            float(monitor_sample_interval),
            global_config,
        )
        log.log(scalyr_logging.DEBUG_LEVEL_1, "Constructed monitor")
        monitor.open_metric_log()
        log.log(scalyr_logging.DEBUG_LEVEL_1, "Starting monitor")
        monitor.start()

        while monitor.isAlive():
            time.sleep(0.1)
    except BadMonitorConfiguration as e:
        print("Invalid monitor configuration: %s" % six.text_type(e), file=sys.stderr)

    return 0


if __name__ == "__main__":
    parser = OptionParser(
        usage="Usage: python -m scalyr_agent.scalyr_monitor [options] monitor_module"
    )
    parser.add_option(
        "-p",
        "--monitor-python-path",
        dest="monitor_python_path",
        help="Add PATH to the paths searched to find the python module for the monitor.",
        metavar="PATH",
        default=".",
    )
    parser.add_option(
        "-c",
        "--monitor-config",
        dest="monitor_config",
        help="The JSON object to use for the monitor configuration, excluding the 'module' field",
        default="{}",
    )
    parser.add_option(
        "-a",
        "--agent-config",
        dest="agent_config",
        help="The file path to the agent.json configuration file to use.  This is optional.  However, if "
        "you do not specify one, then your monitor's `_global_config` instance variable will be set "
        "to None.",
        default=None,
    )
    parser.add_option(
        "-d",
        "--debug-level",
        dest="debug_level",
        help="The Scalyr debug level to use for emitting debug output.  This will be sent to stdout. "
        "This should be a number between 0 and 5, corresponding to DEBUG_LEVEL_0 .. DEBUG_LEVEL_5 "
        "defined in scalyr_logging",
        default=0,
    )
    parser.add_option(
        "-s",
        "--monitor-sample-interval",
        dest="monitor_sample_interval",
        help="The number of seconds between calls to the monitor's gather_sample method.",
        metavar="INTERVAL",
        default=5,
    )

    (options, args) = parser.parse_args()
    if len(args) != 1:
        print(
            "You must provide the module that contains the Scalyr Monitor plugin you wish to run.",
            file=sys.stderr,
        )
        parser.print_help(sys.stderr)
        sys.exit(1)

    try:
        my_debug_level = int(options.debug_level)
        if my_debug_level < 0 or my_debug_level > 5:
            raise ValueError("Out of range")
    except ValueError:
        print(
            "Invalid value for the --debug-level option: %s.  Must be a number between 0 and 5 "
            % six.text_type(options.debug_level),
            file=sys.stderr,
        )
        sys.exit(1)

    debug_levels = [
        scalyr_logging.DEBUG_LEVEL_0,
        scalyr_logging.DEBUG_LEVEL_1,
        scalyr_logging.DEBUG_LEVEL_2,
        scalyr_logging.DEBUG_LEVEL_3,
        scalyr_logging.DEBUG_LEVEL_4,
        scalyr_logging.DEBUG_LEVEL_5,
    ]

    sys.exit(
        run_standalone_monitor(
            args[0],
            options.monitor_python_path,
            options.monitor_config,
            options.monitor_sample_interval,
            debug_levels[my_debug_level],
            options.agent_config,
        )
    )
