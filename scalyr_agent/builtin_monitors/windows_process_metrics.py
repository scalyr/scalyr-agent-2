#!/usr/bin/env python
"""Scalyr Agent Plugin Module - Windows Process Metrics

This module extends the ScalyrMonitor base class to implement it's functionality, a process
metrics collector for the Windows (Server 2003 and newer) platforms, as a monitor plugin into
the Scalyr plugin framework.

The two most important object in this monitor are:

 1. The METRICS list; which defines the metrics that this module will collect
 2. The ProcessMonitor class which drives the collection of each defined metric and emits 
    its associated value at a specified sampling rate.


>>> import re, operator, collections
>>> metric_template = "{metric.metric_name} - {metric.description} {metric.units}".format
>>> criteria = dict(
...     category = 'cpu',
...     metric_name = 'winproc.disk.*',
...     match = any
... )
>>> predicates = [(operator.itemgetter(k), re.compile(v))
...                 for k,v in criteria.items() 
...                 if k is not 'match']
>>> Telemetry = collections.namedtuple('Telemetry', 'match metric attribute fetcher matcher')
>>> for metric in METRICS:
...     matches = []
...     for fetcher, matcher in predicates:
...         attribute = fetcher(metric)
...         match = matcher.search(attribute)
...         matches.append(Telemetry(match, metric, attribute, fetcher, matcher))
...     else:
...         if any(itertools.ifilter(operator.attrgetter('match'), matches)):
...             print metric_template(metric)


>>> from scalyr_agent import run_monitor
>>> monitors_path = path.join(path.dirname(scalyr_agent.__file__), 'builtin_monitors')
>>> cmdline = ['-p', monitors_path, -c, '{commandline:cmd}', 'windows_process_metrics' ]
>>> parser = run_monitor.create_parser()
>>> options, args = parser.parse_args(cmdline)
>>> run_monitor.run_standalone_monitor(args[0], options.monitor_module, options.monitors_path, 
...     options.monitor_config options.monitor_sample_interval)
0
>>> 

Author: Scott Sullivan <guy.hoozdis+scalyr@gmail.com>
License: Apache 2.0
------------------------------------------------------------------------
Copyright 2014 Scalyr Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
------------------------------------------------------------------------
"""

__author__ = 'Scott Sullivan <guy.hoozdis@gmail.com>'
__version__ = "0.0.1"



__monitor__ = __name__


import os
import sys
import re
import datetime

import itertools
from operator import methodcaller, attrgetter
from collections import namedtuple




try:
    import psutil
except ImportError:
    msg = "This monitor requires the psutil module.\n\tpip install psutil\n"
    sys.stderr.write(msg)
    sys.exit(1)
else:
    from psutil import Error, AccessDenied, NoSuchProcess, TimeoutExpired
    from psutil import process_iter, Process



try:
    import scalyr_agent
except ImportError:
    msg = "This monitor requires the scalyr_agent module.\n\t"
    sys.stderr.write(msg)
    sys.exit(1)
else:
    from scalyr_agent import ScalyrMonitor, BadMonitorConfiguration
    from scalyr_agent import define_config_option, define_metric, define_log_field
    from scalyr_agent import scalyr_logging


applog = scalyr_logging.getLogger("{}.{}".format(__name__, 'main')) # pylint: disable=invalid-name
scalyr_logging.set_log_destination(use_stdout=True)
scalyr_logging.set_log_level(scalyr_logging.logging.DEBUG)



MSG = "** Log Level Active **"
applog.critical(MSG)
applog.warn(MSG)
applog.info(MSG)
applog.debug(MSG)
applog.info('Module loading...')



#
# Monitor Configuration - defines the runtime environment and resources available
#
CONFIG_OPTIONS = [
    dict(
        option_name='module',
        option_description='Always ``scalyr_agent.builtin_monitors.windows_process_metrics``',
        convert_to=str,
        required_option=True
    ),
    dict(
        option_name='commandline',
        option_description='A regular expression which will match the command line of the process you\'re interested '
        'in, as shown in the output of ``ps aux``. (If multiple processes match the same command line pattern, '
        'only one will be monitored.)',
        default=None,
        convert_to=str
    ),
    dict(
        option_name='pid',
        option_description='The pid of the process from which the monitor instance will collect metrics.  This is '
        'ignored if the ``commandline`` is specified.',
        default=None,
        convert_to=str
    ),
    dict(
        option_name='id',
        option_description='Included in each log message generated by this monitor, as a field named ``instance``. '
        'Allows you to distinguish between values recorded by different monitors.',
        required_option=True,
        convert_to=str
    )
]

_ = [define_config_option(__monitor__, **option) for option in CONFIG_OPTIONS] # pylint: disable=star-args
## End Monitor Configuration
# #########################################################################################




# #########################################################################################
# #########################################################################################
# ## Process's Metrics / Dimensions -
# ##
# ##    Metrics define the capibilities of this monitor.  These some utility functions
# ##    along with the list(s) of metrics themselves.
# ##
def _gather_metric(method, attribute=None):
    """Curry arbitrary process metric extraction

    @param method: a callable member of the process object interface
    @param attribute: an optional data member, of the data structure returned by ``method``

    @type method callable
    @type attribute str
    """

    doc = "Extract the {} attribute from the given process object".format
    if attribute:
        doc = "Extract the {}().{} attribute from the given process object".format

    def gather_metric(process):
        """Dynamically Generated """
        assert type(process) is psutil.Process, "Only the 'psutil.Process' interface is supported currently"
        metric = methodcaller(method)   # pylint: disable=redefined-outer-name
        return attribute and attrgetter(attribute)(metric(process)) or metric(process)

    gather_metric.__doc__ = doc(method, attribute)
    return gather_metric


def uptime(start_time):
    """Calculate the difference between now() and the given create_time.

    @param start_time: milliseconds passed since 'event' (not since epoc)
    @type float
    """
    return datetime.datetime.now() - datetime.datetime.fromtimestamp(start_time)


METRIC = namedtuple('METRIC', 'config dispatch')
METRIC_CONFIG = dict    # pylint: disable=invalid-name
GATHER_METRIC = _gather_metric


# pylint: disable=bad-whitespace
# =================================================================================
# ============================    Process CPU    ==================================
# =================================================================================
_PROCESS_CPU_METRICS = [
    METRIC( ## ------------------ User-mode CPU ----------------------------
        METRIC_CONFIG(
            metric_name     = 'winproc.cpu',
            description     = 'User-mode CPU usage, in 1/100ths of a second.',
            category        = 'cpu',
            unit            = 'secs:0.01',
            cumulative      = True,
            extra_fields    = {
                'type': 'user'
            },
        ),
        GATHER_METRIC('cpu_times', 'user')
    ),
    METRIC( ## ------------------ Kernel-mode CPU ----------------------------
        METRIC_CONFIG(
            metric_name     = 'winproc.cpu',
            description     = 'System-mode CPU usage, in 1/100ths of a second.',
            category        = 'cpu',
            unit            = 'secs:0.01',
            cumulative      =   True,
            extra_fields    = {
                'type': 'system'
            },
        ),
        GATHER_METRIC('cpu_times', 'system')
    ),

    # TODO: Additional attributes for this section
    #  * context switches
    #  * ...
]


# =================================================================================
# ========================    Process Attributes    ===============================
# =================================================================================
_PROCESS_ATTRIBUTE_METRICS = [
    METRIC( ## ------------------  Process Uptime   ----------------------------
        METRIC_CONFIG(
            metric_name     = 'winproc.uptime',
            description     = 'Process uptime, in milliseconds.',
            category        = 'attributes',
            unit            = 'milliseconds',
            cumulative      = True,
        ),
        GATHER_METRIC('create_time')
    ),
    METRIC( ## ------------------  Process Threads   ----------------------------
        METRIC_CONFIG(
            metric_name     = 'winproc.threads',
            description     = 'The number of threads being used by the process.',
            category        = 'attributes'
        ),
        GATHER_METRIC('num_threads')
    ),

    # TODO: Additional attributes for this section
    #  * number of handles
    #  * number of child processes
    #  * process priority
    #  * process cmdline
    #  * procress working directory
    #  * process env vars
    #  * parent PID
    #  * cpu affinity
]

# =================================================================================
# ========================    Process Memory    ===================================
# =================================================================================
_PROCESS_MEMORY_METRICS = [
    METRIC( ## ------------------ Working Set ----------------------------
        METRIC_CONFIG(
            metric_name     = 'winproc.mem.bytes',
            description     = 'The current working set size, in bytes.',
            category        = 'memory',
            unit            = 'bytes',
            extra_fields    = {
                'type': 'working_set'
            },
        ),
        GATHER_METRIC('memory_info_ex', 'wset')
    ),
    METRIC( ## ------------------ Peak Working Set ----------------------------
        METRIC_CONFIG(
            metric_name     = 'winproc.mem.bytes',
            description     = 'The peak working set size, in bytes.',
            category        = 'memory',
            unit            = 'bytes',
            extra_fields    = {
                'type': 'peak_working_set'
            },
        ),
        GATHER_METRIC('memory_info_ex', 'peak_wset')
    ),
    METRIC( ## ------------------ Paged Pool ----------------------------
        METRIC_CONFIG(
            metric_name     = 'winproc.mem.bytes',
            description     = 'The paged pool usage, in bytes.',
            category        = 'memory',
            unit            = 'bytes',
            extra_fields    = {
                'type': 'paged_pool'
            },
        ),
        GATHER_METRIC('memory_info_ex', 'paged_pool')
    ),
    METRIC( ## ------------------ Peak Paged Pool ----------------------------
        METRIC_CONFIG(
            metric_name     = 'winproc.mem.bytes',
            description     = 'The peak paged-pool usage, in bytes.',
            category        = 'memory',
            unit            = 'bytes',
            extra_fields    = {
                'type': 'peak_paged_pool'
            },
        ),
        GATHER_METRIC('memory_info_ex', 'peak_paged_pool')
    ),

    METRIC( ## ------------------ NonPaged Pool ----------------------------
        METRIC_CONFIG(
            metric_name     = 'winproc.mem.bytes',
            description     = 'The nonpaged pool usage, in bytes.',
            category        = 'memory',
            unit            = 'bytes',
            extra_fields    = {
                'type': 'nonpaged_pool'
            },
        ),
        GATHER_METRIC('memory_info_ex', 'nonpaged_pool')
    ),
    METRIC( ## ------------------ Peak NonPaged Pool ----------------------------
        METRIC_CONFIG(
            metric_name     = 'winproc.mem.bytes',
            description     = 'The peak nonpaged pool usage, in bytes.',
            category        = 'memory',
            unit            = 'bytes',
            extra_fields    = {
                'type': 'peak_nonpaged_pool'
            },
        ),
        GATHER_METRIC('memory_info_ex', 'peak_nonpaged_pool')
    ),
    METRIC( ## ------------------ Pagefile ----------------------------
        METRIC_CONFIG(
            metric_name     = 'winproc.mem.bytes',
            description     = 'The current pagefile usage, in bytes.',
            category        = 'memory',
            unit            = 'bytes',
            extra_fields    = {
                'type': 'pagefile'
            },
        ),
        GATHER_METRIC('memory_info_ex', 'pagefile')
    ),
    METRIC( ## ------------------ Peak Pagefile ----------------------------
        METRIC_CONFIG(
            metric_name     = 'winproc.mem.bytes',
            description     = 'The peak pagefile usage, in bytes.',
            category        = 'memory',
            unit            = 'bytes',
            extra_fields    = {
                'type': 'peak_pagefile'
            },
        ),
        GATHER_METRIC('memory_info_ex', 'peak_pagefile')
    ),


    # TODO: Additional attributes for this section
    #  * ...
]



# =================================================================================
# =============================    DISK IO    =====================================
# =================================================================================
_PROCESS_DISK_IO_METRICS = [
    METRIC( ## ------------------ Disk Read Operations ----------------------------
        METRIC_CONFIG(
            metric_name     = 'winproc.disk.operations',
            description     = 'Total disk read requests.',
            category        = "disk",
            unit            = 'bytes',
            cumulative      = True,
            extra_fields    = {
                'type': 'read'
            },
        ),
        GATHER_METRIC('io_counters', 'read_count')
    ),
    METRIC( ## ------------------ Disk Write Operations ----------------------------
        METRIC_CONFIG(
            metric_name     = 'winproc.disk.operations',
            description     = 'Total disk read requests.',
            category        = "disk",
            unit            = 'bytes',
            cumulative      = True,
            extra_fields    = {
                'type': 'read'
            },
        ),
        GATHER_METRIC('io_counters', 'read_count')
    ),
    METRIC( ## ------------------ Disk Read Bytes ----------------------------
        METRIC_CONFIG(
            metric_name     = 'winproc.disk.operations',
            description     = 'Total bytes processed during disk read operations.',
            category        = "disk",
            unit            = 'bytes',
            cumulative      = True,
            extra_fields    = {
                'type': 'read'
            },
        ),
        GATHER_METRIC('io_counters', 'read_bytes')
    ),
    METRIC( ## ------------------ Disk Read Bytes ----------------------------
        METRIC_CONFIG(
            metric_name     = 'winproc.disk.operations',
            description     = 'Total disk read requests.',
            category        = "disk",
            unit            = 'bytes',
            cumulative      = True,
            extra_fields    = {
                'type': 'read'
            },
        ),
        GATHER_METRIC('io_counters', 'read_count')
    )
    # TODO: Additional attributes for this section
    #  * ...
]
# pylint: enable=bad-whitespace

METRICS = _PROCESS_CPU_METRICS + _PROCESS_ATTRIBUTE_METRICS + _PROCESS_MEMORY_METRICS + _PROCESS_DISK_IO_METRICS
_ = [define_metric(__monitor__, **metric.config) for metric in METRICS]     # pylint: disable=star-args




#
# Logging / Reporting - defines the method and content in which the metrics are reported.
#
define_log_field(__monitor__, 'monitor', 'Always ``linux_process_metrics``.')
define_log_field(__monitor__, 'instance', 'The ``id`` value from the monitor configuration, e.g. ``tomcat``.')
define_log_field(__monitor__, 'app', 'Same as ``instance``; provided for compatibility with the original Scalyr Agent.')
define_log_field(__monitor__, 'metric', 'The name of a metric being measured, e.g. "app.cpu".')
define_log_field(__monitor__, 'value', 'The metric value.')







#
#
#
def commandline_matcher(regex, flags=re.IGNORECASE):
    """
    @param regex: a regular expression to compile and use to search process commandlines for matches
    @param flags: modify the regular expression with standard flags (see ``re`` module)

    @type regex str
    @type flags int
    """
    pattern = re.compile(regex, flags)

    def _cmdline(process):
        """Compose the process's commandline parameters as a string"""
        return ' '.join(process.cmdline())

    def _match_generator(processes):
        """
        @param processes: an iterable list of process object interfaces
        @type interface
        """
        return (process for process in processes if pattern.search(_cmdline(process)))

    return _match_generator





class ProcessMonitor(ScalyrMonitor):
    """Windows Process Metrics"""

    def __init__(self, monitor_config, logger, **kw):
        sample_interval_secs = kw.get('sample_interval_secs', 30)
        super(ProcessMonitor, self).__init__(monitor_config, logger, sample_interval_secs)
        self.__process = None

        applog.info('%s instantiated', self.__class__)
        self.__debug = {
           'counter': itertools.count()
        }

    def _select_target_process(self):
        applog.debug('Selecting target process from config %s', str(self._config))

        process = None
        if 'commandline' in self._config:
            applog.info('Using commandlline string matching to select target process')
            matcher = commandline_matcher(self._config['commandline'])
            matching_process_iterator = matcher(process_iter())
            process = matching_process_iterator.next()
        elif 'pid' in self._config:
            applog.info('Using pid to select target process')
            if '$$' == self._config.get('pid'):
                pid = os.getpid()
            else:
                pid = self._config.get('pid')
            process = psutil.Process(int(pid))

        applog.info('Target process selected for monitoring: %s', process)
        self.__process = process

    def gather_sample(self):
        counter = self.__debug['counter']
        sample_id = counter.next()
        applog.debug('Sampling metrics (Iteration %03d)', sample_id)

        try:
            self._select_target_process()

            applog.info("Enumerating and emitting metrics")
            for idx, metric in enumerate(METRICS):
                metric_name = metric.config['metric_name']
                metric_value = metric.dispatch(self.__process)
                applog.debug('Sampled %s at %s', metric_name, metric_value)
                self._logger.emit_value(
                    metric_name,
                    metric_value,
                    **metric.config['extra_fields']
                )
            applog.debug('Sampling complete (Iteration %s)', sample_id)
        except NoSuchProcess:
            self.__process = None


def create_application_logger(name, level=scalyr_logging.DEBUG_LEVEL_0, parent=None, **config):
    logger = parent and parent.getChild(name) or scalyr_logging.getLogger(name)
    logger.set_log_level(level)

    slc = collections.defaultdict(lambda k: '<Uninitialized>', use_stdout=True, use_disk=False, )
    scalyr_agent.set_log_destination(use_stdout=True)



import argparse
def create_commandline_parser(**parser_config):
    parser = argparse.ArgumentParser(**parser_config)
    parser.add_argument('-c', '--config', 
        dest='monitor_config', default='{pid:$$}', type=str, 
        help='A json object, as a string, that defines the process to monitor and sample metrics',
    )
    # todo: Left-off here....
