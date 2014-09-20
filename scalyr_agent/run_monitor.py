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

__author__ = 'czerwin@scalyr.com'

import signal
import sys
import time

from optparse import OptionParser

from __scalyr__ import scalyr_init

scalyr_init()

import scalyr_agent.scalyr_logging as scalyr_logging
import scalyr_agent.json_lib as json_lib

from scalyr_agent.monitors_manager import MonitorsManager
from scalyr_agent.scalyr_monitor import BadMonitorConfiguration


def run_standalone_monitor(monitor_module, monitor_python_path, monitor_config, monitor_sample_interval):
    """Runs a single plugin monitor instance.

    @param monitor_module: The name of the python module implementing the monitor.
    @param monitor_python_path: The python path to search to find the module.
    @param monitor_config: The monitor configuration object.
    @param monitor_sample_interval: The default to use for the sample interval.
    """
    scalyr_logging.set_log_destination(use_stdout=True)

    try:
        parsed_config = json_lib.parse(monitor_config)
    except json_lib.JsonParseException, e:
        print >>sys.stderr, 'Failed to parse the monitor configuration as valid JSON: %s', str(e)
        return 1

    parsed_config['module'] = monitor_module
    if 'id' not in parsed_config:
        parsed_config['id'] = ''

    # noinspection PyUnusedLocal
    def handle_shutdown_signal(signum, frame):
        print >>sys.stdout, 'Signal received, stopping monitor...'
        monitor.stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, handle_shutdown_signal)

    try:
        monitor = MonitorsManager.build_monitor(parsed_config, monitor_python_path)
        monitor.set_sample_interval(float(monitor_sample_interval))
        monitor.open_metric_log()
        monitor.start()

        while monitor.is_alive():
            time.sleep(0.1)
    except BadMonitorConfiguration, e:
        print >>sys.stderr, 'Invalid monitor configuration: %s' % str(e)

    return 0

if __name__ == '__main__':
    parser = OptionParser(usage='Usage: python -m scalyr_agent.scalyr_monitor [options] monitor_module')
    parser.add_option("-p", "--monitor-python-path", dest="monitor_python_path",
                      help="Add PATH to the paths searched to find the python module for the monitor.", metavar="PATH",
                      default=".")
    parser.add_option("-c", "--monitor-config", dest="monitor_config",
                      help="The JSON object to use for the monitor configuration, excluding the 'module' field",
                      default="{}")
    parser.add_option("-s", "--monitor-sample-interval", dest="monitor_sample_interval",
                      help="The number of seconds between calls to the monitor's gather_sample method.",
                      metavar="INTERVAL", default=5)

    (options, args) = parser.parse_args()
    if len(args) != 1:
        print >> sys.stderr, 'You must provide the module that contains the Scalyr Monitor plugin you wish to run.'
        parser.print_help(sys.stderr)
        sys.exit(1)

    sys.exit(run_standalone_monitor(args[0], options.monitor_python_path, options.monitor_config,
                                    options.monitor_sample_interval))