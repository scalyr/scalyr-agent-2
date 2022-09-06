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
from __future__ import unicode_literals
from __future__ import absolute_import

__author__ = "Scott Sullivan <guy.hoozdis@gmail.com>"
__version__ = "0.0.1"

__monitor__ = __name__


import os
import re
import datetime
import time

from operator import methodcaller, attrgetter
from collections import namedtuple

try:
    import psutil
except ImportError:
    psutil = None

import six

from scalyr_agent import ScalyrMonitor, UnsupportedSystem, BadMonitorConfiguration
from scalyr_agent import define_config_option, define_metric, define_log_field
from scalyr_agent import scalyr_logging

global_log = scalyr_logging.getLogger(__name__)


#
# Monitor Configuration - defines the runtime environment and resources available
#
CONFIG_OPTIONS = [
    dict(
        option_name="module",
        option_description="Always `scalyr_agent.builtin_monitors.windows_process_metrics`",
        convert_to=six.text_type,
        required_option=True,
    ),
    dict(
        option_name="id",
        option_description="An id, included with each event. Shows in the UI as a value "
        "for the `instance` field. This is especially useful if you are running multiple "
        "instances of this plugin to import metrics from multiple processes. Each instance "
        "has a separate `{...}` stanza in the configuration file "
        r"(`C:\Program Files (x86)\Scalyr\config\agent.json`).",
        required_option=True,
        convert_to=six.text_type,
    ),
    dict(
        option_name="commandline",
        option_description="A regular expression, matching on the command line output "
        "of `tasklist`, or `wmic process list`. Selects the process of interest. "
        "If multiple processes match, only metrics from the first match are imported.",
        default=None,
        convert_to=six.text_type,
    ),
    dict(
        option_name="pid",
        option_description="Process identifier (PID). An alternative to `commandline` "
        "to select a process. If `commandline` is set, this property is ignored.",
        default=None,
        convert_to=six.text_type,
    ),
]

_ = [
    define_config_option(__monitor__, **option) for option in CONFIG_OPTIONS  # type: ignore
]
# End Monitor Configuration
# #########################################################################################


# #########################################################################################
# #########################################################################################
# ## Process's Metrics / Dimensions -
# ##
# ##    Metrics define the capibilities of this monitor.  These some utility functions
# ##    along with the list(s) of metrics themselves.
# ##
def _gather_metric(method, attribute=None, transform=None):
    """Curry arbitrary process metric extraction

    @param method: a callable member of the process object interface
    @param attribute: an optional data member, of the data structure returned by ``method``
    @param transform: an optional function that can be used to transform the value returned by ``method``.
        The function should take a single argument and return the value to report as the metric value.

    @type method callable
    @type attribute str
    @type transform: func()
    """

    doc = "Extract the {} attribute from the given process object".format
    if attribute:
        doc = (  # NOQA
            "Extract the {}().{} attribute from the given process object".format
        )

    def gather_metric(process):
        """Dynamically Generated"""
        errmsg = (
            "Only the 'psutil.Process' interface is supported currently; not {}".format
        )
        proc_type = type(process)
        assert proc_type is psutil.Process, errmsg(proc_type)
        metric = methodcaller(method)  # pylint: disable=redefined-outer-name
        if attribute is not None:
            value = attrgetter(attribute)(metric(process))
        else:
            value = metric(process)

        if transform is not None:
            value = transform(value)

        return value

    # XXX: For some reason this was causing trouble for the documentation build process
    # gather_metric.__doc__ = doc(method, attribute)
    return gather_metric


# TODO:  I believe this function can be deleted.
def uptime(start_time):
    """Calculate the difference between now() and the given create_time.

    @param start_time: milliseconds passed since 'event' (not since epoc)
    @type float
    """
    return datetime.datetime.utcnow() - datetime.datetime.utcfromtimestamp(start_time)


def uptime_from_start_time(start_time):
    """Returns the uptime for the process given its ``start_time``.

    @param start_time: The time the process started in seconds past epoch.
    @type start_time: float

    @return: The seconds since the process started.
    @rtype: float
    """
    return time.time() - start_time


METRIC = namedtuple("METRIC", "config dispatch")
METRIC_CONFIG = dict  # pylint: disable=invalid-name
GATHER_METRIC = _gather_metric


# =================================================================================
# ============================    Process CPU    ==================================
# =================================================================================
_PROCESS_CPU_METRICS = [
    METRIC(  # ------------------ User-mode CPU ----------------------------
        METRIC_CONFIG(
            metric_name="winproc.cpu",
            description="Seconds of user space CPU execution. The value is cumulative since process "
            "start; see `winproc.uptime`.",
            category="CPU",
            unit="secs",
            cumulative=True,
            extra_fields={"type": "user"},
        ),
        GATHER_METRIC("cpu_times", "user"),
    ),
    METRIC(  # ------------------ Kernel-mode CPU ----------------------------
        METRIC_CONFIG(
            metric_name="winproc.cpu",
            description="Seconds of kernel space CPU execution. The value is cumulative since "
            "process start; see `winproc.uptime`.",
            category="CPU",
            unit="secs",
            cumulative=True,
            extra_fields={"type": "system"},
        ),
        GATHER_METRIC("cpu_times", "system"),
    ),
    # TODO: Additional attributes for this section
    #  * context switches
    #  * ...
]


# =================================================================================
# ========================    Process Attributes    ===============================
# =================================================================================
_PROCESS_ATTRIBUTE_METRICS = [
    METRIC(  # ------------------  Process Uptime   ----------------------------
        METRIC_CONFIG(
            metric_name="winproc.uptime",
            description="Process uptime, in seconds.",
            category="General",
            unit="seconds",
            cumulative=True,
            extra_fields={},
        ),
        GATHER_METRIC("create_time", transform=uptime_from_start_time),
    ),
    METRIC(  # ------------------  Process Threads   ----------------------------
        METRIC_CONFIG(
            metric_name="winproc.threads",
            description="Number of threads used by the process.",
            category="General",
            extra_fields={},
        ),
        GATHER_METRIC("num_threads"),
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
    METRIC(  # ------------------ Working Set ----------------------------
        METRIC_CONFIG(
            metric_name="winproc.mem.bytes",
            description="Bytes of physical memory used by the process's working set. "
            "Memory that must be paged in for the process to execute.",
            category="Memory",
            unit="bytes",
            extra_fields={"type": "working_set"},
        ),
        GATHER_METRIC("memory_info_ex", "wset"),
    ),
    METRIC(  # ------------------ Peak Working Set ----------------------------
        METRIC_CONFIG(
            metric_name="winproc.mem.bytes",
            description="Peak working set size, in bytes, for the process since creation.",
            category="Memory",
            unit="bytes",
            extra_fields={"type": "peak_working_set"},
        ),
        GATHER_METRIC("memory_info_ex", "peak_wset"),
    ),
    METRIC(  # ------------------ Paged Pool ----------------------------
        METRIC_CONFIG(
            metric_name="winproc.mem.bytes",
            description="Paged-pool usage, in bytes. Swappable memory in use.",
            category="Memory",
            unit="bytes",
            extra_fields={"type": "paged_pool"},
        ),
        GATHER_METRIC("memory_info_ex", "paged_pool"),
    ),
    METRIC(  # ------------------ Peak Paged Pool ----------------------------
        METRIC_CONFIG(
            metric_name="winproc.mem.bytes",
            description="Peak paged-pool usage, in bytes.",
            category="Memory",
            unit="bytes",
            extra_fields={"type": "peak_paged_pool"},
        ),
        GATHER_METRIC("memory_info_ex", "peak_paged_pool"),
    ),
    METRIC(  # ------------------ NonPaged Pool ----------------------------
        METRIC_CONFIG(
            metric_name="winproc.mem.bytes",
            description="Nonpaged pool usage, in bytes. "
            "Memory in use that cannot be swapped out to disk.",
            category="Memory",
            unit="bytes",
            extra_fields={"type": "nonpaged_pool"},
        ),
        GATHER_METRIC("memory_info_ex", "nonpaged_pool"),
    ),
    METRIC(  # ------------------ Peak NonPaged Pool ----------------------------
        METRIC_CONFIG(
            metric_name="winproc.mem.bytes",
            description="Peak nonpaged pool usage, in bytes.",
            category="Memory",
            unit="bytes",
            extra_fields={"type": "peak_nonpaged_pool"},
        ),
        GATHER_METRIC("memory_info_ex", "peak_nonpaged_pool"),
    ),
    METRIC(  # ------------------ Pagefile ----------------------------
        METRIC_CONFIG(
            metric_name="winproc.mem.bytes",
            description="Pagefile usage, in bytes. Bytes the system has "
            "committed for this running process.",
            category="Memory",
            unit="bytes",
            extra_fields={"type": "pagefile"},
        ),
        GATHER_METRIC("memory_info_ex", "pagefile"),
    ),
    METRIC(  # ------------------ Peak Pagefile ----------------------------
        METRIC_CONFIG(
            metric_name="winproc.mem.bytes",
            description="Peak pagefile usage, in bytes.",
            category="Memory",
            unit="bytes",
            extra_fields={"type": "peak_pagefile"},
        ),
        GATHER_METRIC("memory_info_ex", "peak_pagefile"),
    ),
    METRIC(  # ------------------ Resident size ----------------------------
        METRIC_CONFIG(
            metric_name="winproc.mem.bytes",
            description="Current resident memory size, in bytes. This should be the same as the working set.",
            category="Memory",
            unit="bytes",
            extra_fields={"type": "rss"},
        ),
        GATHER_METRIC("memory_info", "rss"),
    ),
    METRIC(  # ------------------ Virtual memory size ----------------------------
        METRIC_CONFIG(
            metric_name="winproc.mem.bytes",
            description="Virtual memory size, in bytes. Does not include shared pages.",
            category="Memory",
            unit="bytes",
            extra_fields={"type": "vms"},
        ),
        GATHER_METRIC("memory_info", "vms"),
    ),
    # TODO: Additional attributes for this section
    #  * ...
]


# =================================================================================
# =============================    DISK IO    =====================================
# =================================================================================
_PROCESS_DISK_IO_METRICS = [
    METRIC(  # ------------------ Disk Read Operations ----------------------------
        METRIC_CONFIG(
            metric_name="winproc.disk.ops",
            description="Number of disk read requests. The value is cumulative since "
            "process start; see `winproc.uptime`.",
            category="Disk",
            unit="requests",
            cumulative=True,
            extra_fields={"type": "read"},
        ),
        GATHER_METRIC("io_counters", "read_count"),
    ),
    METRIC(  # ------------------ Disk Write Operations ----------------------------
        METRIC_CONFIG(
            metric_name="winproc.disk.ops",
            description="Number of disk write requests. The value is cumulative since "
            "process start; see `winproc.uptime`.",
            category="Disk",
            unit="requests",
            cumulative=True,
            extra_fields={"type": "write"},
        ),
        GATHER_METRIC("io_counters", "write_count"),
    ),
    METRIC(  # ------------------ Disk Read Bytes ----------------------------
        METRIC_CONFIG(
            metric_name="winproc.disk.bytes",
            description="Bytes read from disk. The value is cumulative since process "
            "start; see `winproc.uptime`.",
            category="Disk",
            unit="bytes",
            cumulative=True,
            extra_fields={"type": "read"},
        ),
        GATHER_METRIC("io_counters", "read_bytes"),
    ),
    METRIC(  # ------------------ Disk Read Bytes ----------------------------
        METRIC_CONFIG(
            metric_name="winproc.disk.bytes",
            description="Bytes written to disk. The value is cumulative since process "
            "start; see `winproc.uptime`.",
            category="Disk",
            unit="bytes",
            cumulative=True,
            extra_fields={"type": "write"},
        ),
        GATHER_METRIC("io_counters", "write_bytes"),
    )
    # TODO: Additional attributes for this section
    #  * ...
]

METRICS = (
    _PROCESS_CPU_METRICS
    + _PROCESS_ATTRIBUTE_METRICS
    + _PROCESS_MEMORY_METRICS
    + _PROCESS_DISK_IO_METRICS
)
_ = [define_metric(__monitor__, **metric.config) for metric in METRICS]


#
# Logging / Reporting - defines the method and content in which the metrics are reported.
#
define_log_field(__monitor__, "monitor", "Always `windows_process_metrics`.")
define_log_field(
    __monitor__,
    "instance",
    "The `id` value, for example `tomcat`.",
)
define_log_field(
    __monitor__,
    "app",
    "Same as `instance`; created for compatibility with the original Scalyr Agent.",
)
define_log_field(
    __monitor__,
    "metric",
    'Name of the metric, for example "winproc.cpu". Some metrics have additional '
    "fields; see the [Metrics Reference](#metrics).",
)
define_log_field(__monitor__, "value", "Value of the metric.")


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
        return " ".join(process.cmdline())

    def _match_generator(processes):
        """
        @param processes: an iterable list of process object interfaces
        @type interface
        """
        for process in processes:
            try:
                if pattern.search(process.name()) or pattern.search(_cmdline(process)):
                    return process
            except psutil.AccessDenied:
                # Just skip this process if we don't have access to it.
                continue
        return None

    return _match_generator


class ProcessMonitor(ScalyrMonitor):
    # fmt: off
    r"""
    # Windows Process Metrics

    Import CPU consumption, memory usage, and other metrics for a process, or group of processes, on a Windows server.

    An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).

    You can use this plugin to monitor resource usage for a web server, database, or other application. 32-bit Windows systems are not supported.

    This plugin requires installation of the python module `psutil`, typically with the command `pip install psutil`.

    You can disable collection of these metrics by setting `implicit_agent_process_metrics_monitor: false` at the top level of the Agent [configuration file](/help/scalyr-agent#plugins).


    ## Installation

    1\. Install the Scalyr Agent

    If you haven't already, install the [Scalyr Agent](https://app.scalyr.com/help/welcome) on the Windows server.


    2\. Configure the Scalyr Agent to import process metrics

    Open the Scalyr Agent configuration file, located at `C:\Program Files (x86)\Scalyr\config\agent.json`.

    Find the `monitors: [ ... ]` section and add a `{...}` stanza with the `module` property set for windows process metrics:

        monitors: [
          {
             module:      "scalyr_agent.builtin_monitors.windows_process_metrics",
             id:          "tomcat",
             commandline: "java.*tomcat6",
          }
        ]

    The `id` property lets you identify the command whose output you are importing. It shows in the UI as a value for the `instance` field. This is especially useful if you are running multiple instances of this plugin, to import metrics from multiple processes. Add a separate `{...}` stanza for each instance, and set unique `id`s.

    The `commandline` property is a [regular expression](https://app.scalyr.com/help/regex), matching on the command line output of `tasklist`, or `wmic process list`. If multiple processes match, only the first is used. The above example imports metrics for the first process whose command line output matches the regular expression `java.*tomcat6`.

    You can also select a process by process identifier (PID). See [Configuration Options](#options) below.


    3\. Save and confirm

    Save the `agent.json` file. The Agent will detect changes within 30 seconds. Wait a few minutes for data to send.

    You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.


    4\. Configure the process metrics dashboard for each `id`

    Log into Scalyr and click Dashboards > Windows Process Metrics. At the top of the dashboard you can select the `serverHost` and `process` of interest. (We map the `instance` field, explained above, to `process`).

    Click `...` in upper right of the page and select "Edit JSON". Find these lines near the top of the JSON file:

        // On the next line, list each "id" that you've used in a windows_process_metrics
        // clause in the Scalyr Agent configuration file (agent.json).
        values: [ "agent" ]

    The "agent" id is used to report metrics for the Scalyr Agent. Add each `id` you created to the `values` list. For example, to add "tomcat":

        values: [ "agent", "tomcat" ]

    Save the file. To view all data collected by this plugin, across all servers, go to Search view and query [monitor = 'windows_process_metrics'](https://app.scalyr.com/events?filter=monitor+%3D+%27windows_process_metrics%27).

    For help, contact Support.

    """
    # fmt: on

    def __init__(
        self, monitor_config, logger, sample_interval_secs=None, global_config=None
    ):
        """TODO: Function documentation"""
        if psutil is None:
            raise UnsupportedSystem(
                "windows_process_metrics",
                'You must install the python module "psutil" to use this module.  Typically, this'
                "can be done with the following command:"
                "  pip install psutil",
            )

        super(ProcessMonitor, self).__init__(
            monitor_config=monitor_config,
            logger=logger,
            sample_interval_secs=sample_interval_secs,
            global_config=global_config,
        )
        self.__process = None

    def _initialize(self):
        self.__id = self._config.get(
            "id", required_field=True, convert_to=six.text_type
        )

        if not self._config.get("commandline") and not self._config.get("pid"):
            raise BadMonitorConfiguration(
                'Either "pid" or "commandline" monitor config option needs to be specified (but not both)',
                "commandline",
            )

        if self._config.get("commandline") and self._config.get("pid"):
            raise BadMonitorConfiguration(
                'Either "pid" or "commandline" monitor config option needs to be specified (but not both)',
                "commandline",
            )

    def _select_target_process(self):
        """TODO: Function documentation"""
        process = None
        if "commandline" in self._config:
            matcher = commandline_matcher(self._config["commandline"])
            process = matcher(psutil.process_iter())
        elif "pid" in self._config:
            if "$$" == self._config.get("pid"):
                pid = os.getpid()
            else:
                pid = self._config.get("pid")
            process = psutil.Process(int(pid))

        self.__process = process

    def gather_sample(self):
        try:
            self._select_target_process()
            for idx, metric in enumerate(METRICS):

                if not self.__process:
                    break

                metric_name = metric.config["metric_name"]
                metric_value = metric.dispatch(self.__process)
                extra_fields = metric.config["extra_fields"]
                if extra_fields is None:
                    extra_fields = {}
                extra_fields["app"] = self.__id

                self._logger.emit_value(
                    metric_name, metric_value, extra_fields=extra_fields
                )
        except psutil.NoSuchProcess:
            self.__process = None

            commandline = self._config.get("commandline", None)
            pid = self._config.get("pid", None)

            # commandline has precedence over pid
            if commandline:
                global_log.warn(
                    'Unable to find process with commandline "%s"' % (commandline)
                )
            elif pid:
                global_log.warn('Unable to find process with pid "%s"' % (pid))
