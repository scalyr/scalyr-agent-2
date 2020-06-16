#!/usr/bin/env python
"""{ShortDescription}

{ExtendedDescription}


# QuickStart

Use the ``run_monitor`` test harness to drive this basic modules and begin your
plugin development cycle.

    $ python -m scalyr_agent.run_monitor -p /path/to/scalyr_agent/builtin_monitors

# Credits & License
Author: Scott Sullivan '<guy.hoozdis@gmail.com>'
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

from __future__ import print_function

__author__ = "Scott Sullivan '<guy.hoozdis@gmail.com>'"
__version__ = "0.0.1"
__monitor__ = __name__


import time

try:
    import psutil
except ImportError:
    psutil = None

import six

from scalyr_agent import ScalyrMonitor, UnsupportedSystem
from scalyr_agent import define_config_option, define_metric, define_log_field


#
# Monitor Configuration - defines the runtime environment and resources available
#
CONFIG_OPTIONS = [
    dict(
        option_name="module",
        option_description="A ScalyrAgent plugin monitor module",
        convert_to=six.text_type,
        required_option=True,
        default="windows_system_metrics",
    )
]

_ = [define_config_option(__monitor__, **option) for option in CONFIG_OPTIONS]
# # End Monitor Configuration
# #########################################################################################


# A special value we return as the result of the disk_io_counters metric evaluation if we
# get an exception indicating diskperf has not been run to turn on the counters.
# We have to use this special value as a hack because there's too many layers in the way to
# do it a more direct route.
__NO_DISK_PERF__ = "no_disk_perf_signal"


# #########################################################################################
# #########################################################################################
# ## System Metrics / Dimensions -
# ##
# ##    Metrics define the capibilities of this monitor.  These some utility functions
# ##    along with the list(s) of metrics themselves.
# ##
def _gather_metric(method, attribute=None, transform=None):
    """Curry arbitrary process metric extraction

    @param method: a callable member of the process object interface
    @param attribute: an optional data member, of the data structure returned by ``method``
    @param transform: An optional function that can be used to modify the value of the metric that `method` returned.

    @type method: callable
    @type attribute: str
    @type transform: func()
    """
    doc = "Extract the {} attribute from the given process object".format
    if attribute:
        doc = "Extract the {}().{} attribute from the given process object".format

    def gather_metric():
        """Dynamically Generated """
        try:
            metric = methodcaller(method)  # pylint: disable=redefined-outer-name
            value = metric(psutil)

            if attribute:
                value = attrgetter(attribute)(value)
            if transform is not None:
                value = transform(value)
            yield value, None
        except RuntimeError as e:
            # Special case the expected exception we see if we call disk_io_counters without the
            # user executing 'diskperf -y' on their machine before use.  Yes, it is a hack relying
            # on the exception message, but sometimes you have to do what you have to do.  At least we
            # package a specific version of psutils in with the windows executable, so we should know if
            # the message changes.
            message = getattr(e, "message", str(e))
            if (
                message == "couldn't find any physical disk"
                and method == "disk_io_counters"
            ):
                yield __NO_DISK_PERF__, None
            else:
                raise e

    gather_metric.__doc__ = doc(method, attribute)
    return gather_metric


def partion_disk_usage(sub_metric):
    mountpoints_initialized = [0]
    mountpoints = []

    def gather_metric():
        if mountpoints_initialized[0] == 0:
            for p in psutil.disk_partitions():
                # Only add to list of mountpoints if fstype is
                # specified.  This prevents reading from empty drives
                # such as cd-roms, card readers etc.
                if p.fstype:
                    mountpoints.append(p.mountpoint)
            mountpoints_initialized[0] = 1

        for mountpoint in mountpoints:
            try:
                diskusage = psutil.disk_usage(mountpoint)
                yield getattr(diskusage, sub_metric), {"partition": mountpoint}
            except OSError:
                # Certain partitions, like a CD/DVD drive, are expected to fail
                pass

    gather_metric.__doc__ = "TODO"
    return gather_metric


def uptime(start_time):
    """Calculate the difference between now() and the given create_time.

    @param start_time: milliseconds passed since 'event' (not since epoc)
    @type float
    """
    from datetime import datetime

    return datetime.now() - datetime.fromtimestamp(start_time)


try:
    from operator import methodcaller, attrgetter
except ImportError:

    def methodcaller(name, *args, **kwargs):  # type: ignore
        def caller(obj):
            return getattr(obj, name)(*args, **kwargs)

        return caller


try:
    from collections import namedtuple

    METRIC = namedtuple("METRIC", "config dispatch")
except ImportError:

    class NamedTupleHack(object):
        def __init__(self, *args):
            self._typename = args[0]
            self._fieldnames = args[1:]

        def __str__(self):
            return "<{typename}: ({fieldnames})...>".format(
                typename=self._typename, fieldnames=self._fieldnames[0]
            )

    METRIC = NamedTupleHack("Metric", "config dispatch")  # type: ignore


METRIC_CONFIG = dict  # pylint: disable=invalid-name
GATHER_METRIC = _gather_metric


# pylint: disable=bad-whitespace
# =================================================================================
# ============================    System CPU    ===================================
# =================================================================================
_SYSTEM_CPU_METRICS = [
    METRIC(  # ------------------  User CPU ----------------------------
        METRIC_CONFIG(
            metric_name="winsys.cpu",
            description="The amount of time in seconds the CPU has spent executing instructions in user space.",
            category="CPU",
            unit="secs",
            cumulative=True,
            extra_fields={"type": "user"},
        ),
        GATHER_METRIC("cpu_times", "user"),
    ),
    METRIC(  # ------------------  System CPU ----------------------------
        METRIC_CONFIG(
            metric_name="winsys.cpu",
            description="The amount of time in seconds the CPU has spent executing instructions in kernel space.",
            category="CPU",
            unit="secs",
            cumulative=True,
            extra_fields={"type": "system"},
        ),
        GATHER_METRIC("cpu_times", "system"),
    ),
    METRIC(  # ------------------  Idle CPU ----------------------------
        METRIC_CONFIG(
            metric_name="winsys.cpu",
            description="The amount of time in seconds the CPU has been idle.",
            category="CPU",
            unit="secs",
            cumulative=True,
            extra_fields={"type": "idle"},
        ),
        GATHER_METRIC("cpu_times", "idle"),
    ),
    # TODO: Additional attributes for this section
    #  * ...
]


def calculate_uptime(boot_time):
    """Calculates the uptime for the system based on its boot time.

    @param boot_time: The time when the system was started in seconds past epoch.
    @type boot_time: float

    @return: The number of seconds since the system was last started.
    @rtype: float
    """
    return time.time() - boot_time


# =================================================================================
# ========================    UPTIME METRICS     ===============================
# =================================================================================
_UPTIME_METRICS = [
    METRIC(  # ------------------  System Boot Time   ----------------------------
        METRIC_CONFIG(
            metric_name="winsys.uptime",
            description="Seconds since the system boot time.",
            category="Uptime",
            unit="secs",
            cumulative=True,
            extra_fields={},
        ),
        GATHER_METRIC("boot_time", None, transform=calculate_uptime),
    ),
    # TODO: Additional attributes for this section
    #  * ...
]

# =================================================================================
# ========================    Swap Memory    ===============================
# =================================================================================
_VIRTUAL_MEMORY_METRICS = [
    METRIC(  # ------------------    Total Swap Memory    ----------------------------
        METRIC_CONFIG(
            metric_name="winsys.memory.total",
            description="The number of bytes of swap space available.",
            category="Memory",
            unit="bytes",
            # cumulative      = {cumulative},
            extra_fields={"type": "swap"},
        ),
        GATHER_METRIC("swap_memory", "total"),
    ),
    METRIC(  # ------------------    Used Virtual Memory    ----------------------------
        METRIC_CONFIG(
            metric_name="winsys.memory.used",
            description="The number of bytes of swap currently in use.",
            category="Memory",
            unit="bytes",
            # cumulative      = {cumulative},
            extra_fields={"type": "swap"},
        ),
        GATHER_METRIC("swap_memory", "used"),
    ),
    METRIC(  # ------------------    Free Virtual Memory    ----------------------------
        METRIC_CONFIG(
            metric_name="winsys.memory.free",
            description="The number of bytes of swap currently free.",
            category="Memory",
            unit="bytes",
            # cumulative      = {cumulative},
            extra_fields={"type": "swap"},
        ),
        GATHER_METRIC("swap_memory", "free"),
    ),
    # TODO: Additional attributes for this section
    #  * ...
]

# =================================================================================
# ========================    Physical Memory    ===============================
# =================================================================================
_PHYSICAL_MEMORY_METRICS = [
    METRIC(  # ------------------    Total Physical Memory    ----------------------------
        METRIC_CONFIG(
            metric_name="winsys.memory.total",
            description="The number of bytes of RAM.",
            category="Memory",
            unit="bytes",
            # cumulative      = {cumulative},
            extra_fields={"type": "physical"},
        ),
        GATHER_METRIC("virtual_memory", "total"),
    ),
    METRIC(  # ------------------    Used Physical Memory    ----------------------------
        METRIC_CONFIG(
            metric_name="winsys.memory.used",
            description="The number of bytes of RAM currently in use.",
            category="Memory",
            unit="bytes",
            # cumulative      = {cumulative},
            extra_fields={"type": "physical"},
        ),
        GATHER_METRIC("virtual_memory", "used"),
    ),
    METRIC(  # ------------------    Free Physical Memory    ----------------------------
        METRIC_CONFIG(
            metric_name="winsys.memory.free",
            description="The number of bytes of RAM that are not in use.",
            category="Memory",
            unit="bytes",
            # cumulative      = {cumulative},
            extra_fields={"type": "physical"},
        ),
        GATHER_METRIC("virtual_memory", "free"),
    ),
    METRIC(  # ------------------    Free Physical Memory    ----------------------------
        METRIC_CONFIG(
            metric_name="winsys.memory.available",
            description="The number of bytes of RAM that are available for allocation.  This includes memory "
            "currently in use for caches but can be freed for other purposes.",
            category="Memory",
            unit="bytes",
            # cumulative      = {cumulative},
            extra_fields={"type": "physical"},
        ),
        GATHER_METRIC("virtual_memory", "available"),
    ),
    # TODO: Additional attributes for this section
    #  * ...
]


# =================================================================================
# ========================    Network IO Counters   ===============================
# =================================================================================
_NETWORK_IO_METRICS = [
    # TODO: Add in per-interface metrics.  This can be gathered using psutils.  You just have to set pernic=True
    # on the call to net_io_counters.  The current structure of this code makes it difficult though.
    METRIC(  # ------------------   Bytes Sent  ----------------------------
        METRIC_CONFIG(
            metric_name="winsys.network.bytes",
            description="The number of bytes transmitted by the network interfaces.",
            category="Network",
            unit="bytes",
            cumulative=True,
            extra_fields={"direction": "sent"},
        ),
        GATHER_METRIC("net_io_counters", "bytes_sent"),
    ),
    METRIC(  # ------------------   Bytes Recv  ----------------------------
        METRIC_CONFIG(
            metric_name="winsys.network.bytes",
            description="The number of bytes received by the network interfaces.",
            category="Network",
            unit="bytes",
            cumulative=True,
            extra_fields={"direction": "recv"},
        ),
        GATHER_METRIC("net_io_counters", "bytes_recv"),
    ),
    METRIC(  # ------------------   Packets Sent  ----------------------------
        METRIC_CONFIG(
            metric_name="winsys.network.packets",
            description="The number of packets transmitted by the network intefaces.",
            category="Network",
            unit="packets",
            cumulative=True,
            extra_fields={"direction": "sent"},
        ),
        GATHER_METRIC("net_io_counters", "packets_sent"),
    ),
    METRIC(  # ------------------   Packets Recv  ----------------------------
        METRIC_CONFIG(
            metric_name="winsys.network.packets",
            description="The number of packets received by the network interfaces.",
            category="Network",
            unit="packets",
            cumulative=True,
            extra_fields={"direction": "recv"},
        ),
        GATHER_METRIC("net_io_counters", "packets_recv"),
    ),
    # TODO: Additional attributes for this section
    #  * dropped packets in/out
    #  * error packets in/out
    #  * various interfaces
]


# =================================================================================
# ========================     Disk IO Counters     ===============================
# =================================================================================
_DISK_IO_METRICS = [
    METRIC(  # ------------------   Disk Bytes Read    ----------------------------
        METRIC_CONFIG(
            metric_name="winsys.disk.io.bytes",
            description="The number of bytes read from disk.",
            category="Disk",
            unit="bytes",
            cumulative=True,
            extra_fields={"type": "read"},
        ),
        GATHER_METRIC("disk_io_counters", "read_bytes"),
    ),
    METRIC(  # ------------------  Disk Bytes Written  ----------------------------
        METRIC_CONFIG(
            metric_name="winsys.disk.io.bytes",
            description="The number of bytes written to disk.",
            category="Disk",
            unit="bytes",
            cumulative=True,
            extra_fields={"type": "write"},
        ),
        GATHER_METRIC("disk_io_counters", "write_bytes"),
    ),
    METRIC(  # ------------------   Disk Read Count    ----------------------------
        METRIC_CONFIG(
            metric_name="winsys.disk.io.ops",
            description="The number of disk read operations issued since boot time.",
            category="Disk",
            unit="count",
            cumulative=True,
            extra_fields={"type": "read"},
        ),
        GATHER_METRIC("disk_io_counters", "read_count"),
    ),
    METRIC(  # ------------------   Disk Write Count    ----------------------------
        METRIC_CONFIG(
            metric_name="winsys.disk.io.ops",
            description="The number of disk write operations issued since boot time.",
            category="Disk",
            unit="count",
            cumulative=True,
            extra_fields={"type": "write"},
        ),
        GATHER_METRIC("disk_io_counters", "write_count"),
    ),
    # TODO: Additional attributes for this section
    #  * ...
]

# TODO: Add Disk Usage per partion

_DISK_USAGE_METRICS = [
    METRIC(
        METRIC_CONFIG(
            metric_name="winsys.disk.usage.percent",
            description="Disk usage percentage for each disk partition.",
            category="Disk",
            unit="percent",
            cumulative=False,
            extra_fields={"partition": ""},
        ),
        partion_disk_usage("percent"),
    ),
    METRIC(
        METRIC_CONFIG(
            metric_name="winsys.disk.usage.used",
            description="The number of bytes used for each disk partition",
            category="Disk",
            unit="byte",
            cumulative=False,
            extra_fields={"partition": ""},
        ),
        partion_disk_usage("used"),
    ),
    METRIC(
        METRIC_CONFIG(
            metric_name="winsys.disk.usage.total",
            description="The maximum number of bytes that can be used on each disk partition.",
            category="Disk",
            unit="byte",
            cumulative=False,
            extra_fields={"partition": ""},
        ),
        partion_disk_usage("total"),
    ),
    METRIC(
        METRIC_CONFIG(
            metric_name="winsys.disk.usage.free",
            description="The number of free bytes on each disk partition.",
            category="Disk",
            unit="byte",
            cumulative=False,
            extra_fields={"partition": ""},
        ),
        partion_disk_usage("free"),
    ),
]
# pylint: enable=bad-whitespace

METRICS = (
    _SYSTEM_CPU_METRICS
    + _UPTIME_METRICS
    + _VIRTUAL_MEMORY_METRICS
    + _PHYSICAL_MEMORY_METRICS
    + _NETWORK_IO_METRICS
    + _DISK_IO_METRICS
    + _DISK_USAGE_METRICS
)
_ = [define_metric(__monitor__, **metric.config) for metric in METRICS]

#
# Logging / Reporting - defines the method and content in which the metrics are reported.
#
define_log_field(__monitor__, "monitor", "Always ``windows_system_metrics``.")
define_log_field(
    __monitor__, "metric", 'The name of a metric being measured, e.g. "winsys.cpu".'
)
define_log_field(__monitor__, "value", "The metric value.")


class SystemMonitor(ScalyrMonitor):
    """A Scalyr agent monitor that records system metrics for Windows platforms.

    This agent monitor plugin records CPU consumption, memory usage, and other metrics for the server on which
    the agent is running.

    There is no required configuration for this monitor and is generally automatically run by the agent.
    """

    def __init__(self, config, logger, **kwargs):
        """TODO: Fucntion documentation
        """
        if psutil is None:
            raise UnsupportedSystem(
                "windows_system_metrics",
                'You must install the python module "psutil" to use this module.  Typically, this'
                "can be done with the following command:"
                "  pip install psutil",
            )
        sampling_rate = kwargs.get("sampling_interval_secs", 30)
        global_config = kwargs.get("global_config")
        super(SystemMonitor, self).__init__(
            config, logger, sampling_rate, global_config=global_config
        )

    def gather_sample(self):
        """TODO: Fucntion documentation
        """
        try:
            for idx, metric in enumerate(METRICS):
                metric_name = metric.config["metric_name"]
                for (metric_value, extra_fields) in metric.dispatch():
                    # We might get this metric value if we were doing the io counters metrics and the user has
                    # not turned on disk performance yet.
                    if metric_value == __NO_DISK_PERF__:
                        self._logger.warn(
                            'disk.io metrics disabled.  You may need to run "diskperf -y" on machine'
                            "to enable IO counters",
                            limit_once_per_x_secs=3600,
                            limit_key="win_diskperf",
                            error_code="win32DiskPerDisabled",
                        )
                    else:
                        if extra_fields is None:
                            extra_fields = metric.config["extra_fields"]
                        self._logger.emit_value(
                            metric_name, metric_value, extra_fields=extra_fields
                        )
        except Exception:
            self._logger.exception("Failed to gather sample due to exception")
