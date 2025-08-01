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
# A ScalyrMonitor that collects metrics on a running Linux process.  The
# collected metrics include CPU and memory usage.
#
# Note, this can be run in standalone mode by:
#     python -m scalyr_agent.run_monitor scalyr_agent.builtin_monitors.linux_process_metrics -c "{ pid:1234}"
#
#   where 1234 is the process id of the target process.
# See documentation for other ways to match processes.
#
# author:  Steven Czerwinski <czerwin@scalyr.com>
from __future__ import unicode_literals
from __future__ import absolute_import

__author__ = "czerwin@scalyr.com"

import os
import errno
import re
import sys
import time
from subprocess import Popen, PIPE
from io import open

import six
from six.moves import range

from scalyr_agent.compat import custom_defaultdict as defaultdict
from scalyr_agent import ScalyrMonitor, BadMonitorConfiguration
from scalyr_agent import define_config_option, define_metric, define_log_field

__monitor__ = __name__

define_config_option(
    __monitor__,
    "module",
    "Always `scalyr_agent.builtin_monitors.linux_process_metrics`",
    convert_to=six.text_type,
    required_option=True,
)
define_config_option(
    __monitor__,
    "id",
    "An id, included with each event. Shows in the UI as a value for the `instance` "
    "field. This is especially useful if you are running multiple instances of this "
    "plugin to import metrics from multiple processes. Each instance has a separate "
    "`{...}` stanza in the configuration file (`/etc/scalyr-agent-2/agent.json`).",
    required_option=True,
    convert_to=six.text_type,
)
define_config_option(
    __monitor__,
    "commandline",
    "A regular expression, matching on the command line output of `ps aux`, "
    "to identify the process of interest. If multiple processes match, only "
    "the first will be used by default. See `aggregate_multiple_processes`, "
    "and `include_child_processes` to match on multiple processes.",
    default=None,
    convert_to=six.text_type,
)
define_config_option(
    __monitor__,
    "aggregate_multiple_processes",
    "Optional (defaults to `false`). When `true`, *all* processes matched by "
    "`commandline` are included. Each metric is a summation of all matches.",
    convert_to=bool,
    default=False,
)
define_config_option(
    __monitor__,
    "include_child_processes",
    "Optional (defaults to `false`). When `true`, all child processes matching "
    "`commandline` processes are included. Each metric is a summation of all "
    "processes (parent and children). This property is resursive; any children "
    "of the child process(es) are also included.",
    convert_to=bool,
    default=False,
)
define_config_option(
    __monitor__,
    "pid",
    "Process identifier. An alternative to `commandline` to specify a process. "
    "Ignored if `commandline` is set.",
    default=None,
    convert_to=six.text_type,
)


define_metric(
    __monitor__,
    "app.cpu",
    "User-mode CPU usage, in 1/100ths of a second. The value is cumulative since boot.",
    extra_fields={"type": "user"},
    unit="secs:0.01",
    cumulative=True,
)

define_metric(
    __monitor__,
    "app.cpu",
    "System-mode CPU usage, in 1/100ths of a second. The value is cumulative since boot.",
    extra_fields={"type": "system"},
    unit="secs:0.01",
    cumulative=True,
)

define_metric(
    __monitor__,
    "app.uptime",
    "Process uptime, in milliseconds.",
    unit="milliseconds",
    cumulative=True,
)

define_metric(__monitor__, "app.threads", "Number of threads used by the process.")

define_metric(__monitor__, "app.nice", "Nice priority value for the process.")

define_metric(
    __monitor__,
    "app.mem.bytes",
    "Bytes used by virtual memory.",
    extra_fields={"type": "vmsize"},
    unit="bytes",
)

define_metric(
    __monitor__,
    "app.mem.bytes",
    "Bytes used by resident memory.",
    extra_fields={"type": "resident"},
    unit="bytes",
)

define_metric(
    __monitor__,
    "app.mem.bytes",
    "Peak virtual memory use, in bytes.",
    extra_fields={"type": "peak_vmsize"},
    unit="bytes",
)

define_metric(
    __monitor__,
    "app.mem.bytes",
    "Peak resident memory use, in bytes.",
    extra_fields={"type": "peak_resident"},
    unit="bytes",
)

define_metric(
    __monitor__,
    "app.mem.majflt",
    "Number of page faults that require loading from disk. "
    "The value is cumulative since boot.",
    cumulative=True,
)

define_metric(
    __monitor__,
    "app.disk.bytes",
    "Bytes read from disk. The value is cumulative since boot.",
    extra_fields={"type": "read"},
    unit="bytes",
    cumulative=True,
)

define_metric(
    __monitor__,
    "app.disk.requests",
    "Number of disk read requests. The value is cumulative since boot.",
    extra_fields={"type": "read"},
    cumulative=True,
)

define_metric(
    __monitor__,
    "app.disk.bytes",
    "Bytes written to disk. The value is cumulative since boot.",
    extra_fields={"type": "write"},
    unit="bytes",
    cumulative=True,
)

define_metric(
    __monitor__,
    "app.disk.requests",
    "Number of disk write requests. The value is cumulative since boot.",
    extra_fields={"type": "write"},
    cumulative=True,
)

define_metric(
    __monitor__,
    "app.io.fds",
    "Number of open file descriptors.",
    extra_fields={"type": "open"},
)

define_metric(
    __monitor__,
    "app.io.wait",
    "Time waiting for I/O completion, in 1/100ths of a second. "
    "The value is cumulative since boot.",
    unit="secs:0.01",
    cumulative=True,
)

define_log_field(__monitor__, "monitor", "Always `linux_process_metrics`.")
define_log_field(
    __monitor__,
    "instance",
    "The `id` value from Step **2**, e.g. `tomcat`.",
)
define_log_field(
    __monitor__,
    "app",
    "Same as `instance`; created for compatibility with the original Scalyr Agent.",
)
define_log_field(__monitor__, "metric", 'Name of the metric, e.g. "app.cpu".')
define_log_field(__monitor__, "value", "Value of the metric.")


class Metric(object):
    """
    This class is an abstraction for a linux metric that contains the
    metric name eg. CPU and type eg. system/user etc. A combination of the
    two make the metric unique.
    """

    __slots__ = "name", "type", "_frozen"

    def __hash__(self):
        x = hash(self.name) + 13 * hash(self.type)
        return x % sys.maxsize

    def __eq__(self, other):
        return other.name == self.name and other.type == self.type

    def __init__(self, name, _type):
        self.name = name
        self.type = _type
        self._frozen = True

    def __setattr__(self, name, value):
        if getattr(self, "_frozen", False):
            raise AttributeError("can't set attribute")
        super(Metric, self).__setattr__(name, value)

    @property
    def is_cumulative(self):
        """
        A cumulative metric is one that needs a prior value to calculate the next value.
        i.e. only the deltas for the current observed values are reported.

        A non-cumulative metric is one where the absolute observed value is reported every time.

        @return: True if the metric is cumulative, False otherwise
        """
        return self.name in (
            "app.cpu",
            "app.uptime",
            "app.disk.bytes",
            "app.disk.requests",
            "app.mem.majflt",
            "app.io.wait",
        )

    def __repr__(self):
        return "<Metric name=%s,type=%s>" % (self.name, self.type)


class MetricPrinter:
    """Helper class that emits metrics for the specified monitor."""

    def __init__(self, logger, monitor_id):
        """Initializes the class.

        @param logger: The logger instances to use to report metrics.
        @param monitor_id: The id of the monitor instance, used to identify all metrics reported through the logger.
        @type logger: scalyr_logging.AgentLogger
        @type monitor_id: str
        """
        self.__logger = logger
        self.__id = monitor_id


class BaseReader:
    """The base class for all readers.  Each derived reader class is responsible for
    collecting a set of statistics from a single per-process file from the /proc file system
    such as /proc/self/stat.  We create an instance for a reader for each application
    that is being monitored.  This instance is created once and then used from
    then on until the monitored process terminates.
    """

    def __init__(self, pid, monitor_id, logger, file_pattern):
        """Initializes the base class.

        @param pid: The id of the process being monitored.
        @param monitor_id: The id of the monitor instance, used to identify all metrics reported through the logger.
        @param logger: The logger instance to use for reporting the metrics.
        @param file_pattern: A pattern that is used to determine the path of the file to be read.  It should
            contain a %d in it which will be replaced by the process id number.  For example, "/proc/%d/stat"

        @type pid: int
        @type monitor_id: str
        @type logger: scalyr_logging.AgentLogger
        @type file_pattern: str
        """
        self._pid = pid
        self._id = monitor_id
        self._file_pattern = file_pattern
        # The file object to be read.  We always keep this open and just seek to zero when we need to
        # re-read it.  Some of the /proc files do better with this approach.
        self._file = None
        # The time we last collected the metrics.
        self._timestamp = None
        # True if the reader failed for some unrecoverable error.
        self._failed = False
        self._logger = logger
        self._metric_printer = MetricPrinter(logger, monitor_id)

    def run_single_cycle(self, collector=None):
        """
        Runs a single cycle of the sample collection.

        It should read the monitored file and extract all metrics.
        @param collector: Optional - a dictionary to collect the metric values.
                          The collector has key as Metric, and value as the actual observed scalar.
                          eg: {
                                ("app.net.bytes", "in"): 12222,
                                ("app.net.bytes", "out"): 20,
                              }
                          Note: a new collector will be instantiated if None is passed in.
        @return: An empty dict or the optional collector with collected metric values
        """

        self._timestamp = int(time.time())

        # There are certain error conditions, such as the system not supporting
        # a particular proc file type, that we will never recover from.  So,
        # just always early exit.
        if self._failed:
            return {}

        filename = self._file_pattern % self._pid

        if not collector:
            collector = {}
        if self._file is None:
            try:
                self._file = open(filename, "r")
            except IOError as e:
                # We take a simple approach.  If we don't find the file or
                # don't have permissions for it, then just don't collect this
                # stat from now on.  If the user changes the configuration file
                # we will try again to read the file then.
                self._failed = True
                if e.errno == errno.EACCES:
                    self._logger.error(
                        "The agent does not have permission to read %s.  "
                        "Maybe you should run it as root.",
                        filename,
                    )
                elif e.errno == errno.ENOENT:
                    self._logger.error(
                        (
                            "The agent cannot read %s.  Your system may not support that proc file "
                            'type or the process with pid "%s" doesn\'t exist'
                        ),
                        filename,
                        self._pid,
                    )
                # Ignore 'process not found' errors (likely caused because the process exited
                # but re-raise the exception for all other errors
                elif e.errno != errno.ESRCH:
                    raise e

        if self._file is not None:
            try:
                self._file.seek(0)

                return self.gather_sample(self._file, collector=collector)

            except IOError as e:
                # log the error if the errno isn't 'process not found'. Process not found likely means the
                # process exited, so we ignore that because it's within the realm of expected behaviour
                if e.errno != errno.ESRCH:
                    self._logger.error(
                        "Error gathering sample for file: '%s'\n\t%s"
                        % (filename, six.text_type(e))
                    )

                # close the file. This will cause the file to be reopened next call to run_single_cycle
                self.close()
        return collector

    def gather_sample(self, my_file, collector=None):
        """Reads the metrics from the file and records them.

        Derived classes must override this method to perform the actual work of
        collecting their specific samples.

        @param my_file: The file to read.
        @type my_file: FileIO
        @param collector: The optional collector dictionary
        @type collector: None or dict
        """

        pass

    def close(self):
        """Closes any files held open by this reader."""
        try:
            self._failed = True
            if self._file is not None:
                self._file.close()
            self._failed = False
        finally:
            self._file = None


class StatReader(BaseReader):
    """Reads and records statistics from the /proc/$pid/stat file.

    The recorded metrics are listed below.  They all also have an app=[id] field as well.
      app.cpu type=user:     number of 1/100ths seconds of user cpu time
      app.cpu type=system:   number of 1/100ths seconds of system cpu time
      app.uptime:            number of milliseconds of uptime
      app.threads:           the number of threads being used by the process
      app.nice:              the nice value for the process
    """

    def __init__(self, pid, monitor_id, logger):
        """Initializes the reader.

        @param pid: The id of the process
        @param monitor_id: The id of the monitor instance
        @param logger: The logger to use to record metrics

        @type pid: int
        @type monitor_id: str
        @type logger: scalyr_agent.AgentLogger
        """

        BaseReader.__init__(self, pid, monitor_id, logger, "/proc/%ld/stat")
        # Need the number of jiffies_per_sec for this server to calculate some times.
        self._jiffies_per_sec = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        # The when this machine was last booted up.  This is required to calculate the process uptime.
        self._boot_time_ms = None

    def __calculate_time_cs(self, jiffies):
        """Returns the number of centiseconds (1/100ths secs) for the given number of jiffies (a weird timing unit
        used the kernel).

        @param jiffies: The number of jiffies.
        @type jiffies: int

        @return: The number of centiseconds for the specified number of jiffies.
        @rtype: int
        """

        return int((jiffies * 100.0) / self._jiffies_per_sec)

    def calculate_time_ms(self, jiffies):
        """Returns the number of milliseconds for the given number of jiffies (a weird timing unit
        used the kernel).

        @param jiffies: The number of jiffies.
        @type jiffies: int

        @return: The number of milliseconds for the specified number of jiffies.
        @rtype: int
        """

        return int((jiffies * 1000.0) / self._jiffies_per_sec)

    def __get_uptime_ms(self):
        """Returns the number of milliseconds the system has been up.

        @return: The number of milliseconds the system has been up.
        @rtype: int
        """

        if self._boot_time_ms is None:
            # We read /proc/uptime once to get the current boot time.
            uptime_file = None
            try:
                uptime_file = open("/proc/uptime", "r")
                # The first number in the file is the number of seconds since
                # boot time.  So, we just use that to calculate the milliseconds
                # past epoch.
                self._boot_time_ms = int(time.time()) * 1000 - int(
                    float(uptime_file.readline().split()[0]) * 1000.0
                )
            finally:
                if uptime_file is not None:
                    uptime_file.close()

        # Calculate the uptime by just taking current time and subtracting out
        # the boot time.
        return int(time.time()) * 1000 - self._boot_time_ms

    def gather_sample(self, stat_file, collector=None):
        """Gathers the metrics from the stat file.

        @param stat_file: The file to read.
        @type stat_file: FileIO
        @param collector: Optional collector dictionary
        @type collector: None or dict
        """
        if not collector:
            collector = {}
        # The file format is just a single line of all the fields.
        line = stat_file.readlines()[0]
        # Chop off first part which is the pid and executable file. The
        # executable file is terminated with a paren so just search for that.
        line = line[(line.find(") ") + 2) :]
        fields = line.split()
        # Then the fields we want are just at fixed field positions in the
        # string.  Just grab them.

        # See http://man7.org/linux/man-pages/man5/proc.5.html for reference on field numbers
        # Keep in mind that we chop first 3 values away (pid, command line, state), so you need to
        # subtract 3 from the field numbers from the man page (e.g. on the man page nice is number
        # 19, but in our case it's 16 aka 19 - 3)
        process_uptime = self.__get_uptime_ms() - self.calculate_time_ms(
            int(fields[19])
        )

        collector.update(
            {
                Metric("app.cpu", "user"): self.__calculate_time_cs(int(fields[11])),
                Metric("app.cpu", "system"): self.__calculate_time_cs(int(fields[12])),
                Metric("app.uptime", None): process_uptime,
                Metric("app.nice", None): float(fields[16]),
                Metric("app.threads", None): int(fields[17]),
                Metric("app.mem.majflt", None): int(fields[9]),
                Metric("app.io.wait", None): (
                    int(fields[39]) if len(fields) >= 39 else 0
                ),
            }
        )
        return collector


class StatusReader(BaseReader):
    """Reads and records statistics from the /proc/$pid/status file.

    The recorded metrics are listed below.  They all also have an app=[id] field as well.
      app.mem.bytes type=vmsize:        the number of bytes of virtual memory in use
      app.mem.bytes type=resident:      the number of bytes of resident memory in use
      app.mem.bytes type=peak_vmsize:   the maximum number of bytes used for virtual memory for process
      app.mem.bytes type=peak_resident: the maximum number of bytes of resident memory ever used by process
    """

    def __init__(self, pid, monitor_id, logger):
        """Initializes the reader.

        @param pid: The id of the process
        @param monitor_id: The id of the monitor instance
        @param logger: The logger to use to record metrics

        @type pid: int
        @type monitor_id: str
        @type logger: scalyr_agent.AgentLogger
        """
        BaseReader.__init__(self, pid, monitor_id, logger, "/proc/%ld/status")

    def gather_sample(self, stat_file, collector=None):
        """Gathers the metrics from the status file.

        @param stat_file: The file to read.
        @type stat_file: FileIO
        @param collector: Optional collector dictionary
        @type collector: None or dict
        """

        if not collector:
            collector = {}

        for line in stat_file:
            # Each line has a format of:
            # Tag: Value
            #
            # We parse out all lines looking like that and match the stats we care about.
            m = re.search(r"^(\w+):\s*(\d+)", line)
            if m is None:
                continue

            field_name = m.group(1)
            int_value = int(m.group(2))
            # FDSize is not the same as the number of open file descriptors. Disable
            # for now.
            # if field_name == "FDSize":
            #     self.print_sample("app.fd", int_value)
            if field_name == "VmSize":
                collector.update({Metric("app.mem.bytes", "vmsize"): int_value * 1024})
            elif field_name == "VmPeak":
                collector.update(
                    {Metric("app.mem.bytes", "peak_vmsize"): int_value * 1024}
                )
            elif field_name == "VmRSS":
                collector.update(
                    {Metric("app.mem.bytes", "resident"): int_value * 1024}
                )
            elif field_name == "VmHWM":
                collector.update(
                    {Metric("app.mem.bytes", "peak_resident"): int_value * 1024}
                )
        return collector


# Reads stats from /proc/$pid/io.
class IoReader(BaseReader):
    """Reads and records statistics from the /proc/$pid/io file.  Note, this io file is only supported on
    kernels 2.6.20 and beyond, but that kernel has been around since 2007.

    The recorded metrics are listed below.  They all also have an app=[id] field as well.
      app.disk.bytes type=read:         the number of bytes read from disk
      app.disk.requests type=read:      the number of disk requests.
      app.disk.bytes type=write:        the number of bytes written to disk
      app.disk.requests type=write:     the number of disk requests.
    """

    def __init__(self, pid, monitor_id, logger):
        """Initializes the reader.

        @param pid: The id of the process
        @param monitor_id: The id of the monitor instance
        @param logger: The logger to use to record metrics

        @type pid: int
        @type monitor_id: str
        @type logger: scalyr_agent.AgentLogger
        """
        BaseReader.__init__(self, pid, monitor_id, logger, "/proc/%ld/io")

    def gather_sample(self, stat_file, collector=None):
        """Gathers the metrics from the io file.

        @param stat_file: The file to read.
        @type stat_file: FileIO
        @param collector: Optional collector dictionary
        @type collector: None or dict
        """

        if not collector:
            collector = {}

        # File format is single value per line with "fieldname:" prefix.
        for x in stat_file:
            fields = x.split()
            if len(fields) == 0:
                continue
            if not collector:
                collector = {}
            if fields[0] == "rchar:":
                collector.update({Metric("app.disk.bytes", "read"): int(fields[1])})
            elif fields[0] == "syscr:":
                collector.update({Metric("app.disk.requests", "read"): int(fields[1])})
            elif fields[0] == "wchar:":
                collector.update({Metric("app.disk.bytes", "write"): int(fields[1])})
            elif fields[0] == "syscw:":
                collector.update({Metric("app.disk.requests", "write"): int(fields[1])})
        return collector


class NetStatReader(BaseReader):
    """NOTE:  This is not a per-process stat file, so this reader is DISABLED for now.

    Reads and records statistics from the /proc/$pid/net/netstat file.

    The recorded metrics are listed below.  They all also have an app=[id] field as well.
      app.net.bytes type=in:  The number of bytes read in from the network
      app.net.bytes type=out:  The number of bytes written to the network
      app.net.tcp_retransmits:  The number of retransmits
    """

    def __init__(self, pid, monitor_id, logger):
        """Initializes the reader.

        @param pid: The id of the process
        @param monitor_id: The id of the monitor instance
        @param logger: The logger to use to record metrics

        @type pid: int
        @type monitor_id: str
        @type logger: scalyr_agent.AgentLogger
        """

        BaseReader.__init__(self, pid, monitor_id, logger, "/proc/%ld/net/netstat")

    def gather_sample(self, stat_file, collector=None):
        """Gathers the metrics from the netstate file.

        @param stat_file: The file to read.
        @type stat_file: FileIO
        @param collector: Optional collector dictionary
        @type collector: None or dict
        """

        # This file format is weird.  Each set of stats is outputted in two
        # lines.  First, a header line that list the field names.  Then a
        # a value line where each value is specified in the appropriate column.
        # You have to match the column name from the header line to determine
        # what that column's value is.  Also, each pair of lines is prefixed
        # with the same name to make it clear they are tied together.
        all_lines = stat_file.readlines()
        # We will create an array of all of the column names in field_names
        # and all of the corresponding values in field_values.
        field_names = []
        field_values = []

        # To simplify the stats, we add together the two forms of retransmit
        # I could find in the netstats.  Those to fast retransmit Reno and those
        # to selective Ack.
        retransmits = 0
        found_retransmit_metric = False

        # Read over lines, looking at adjacent lines.  If their row names match,
        # then append their column names and values to field_names
        # and field_values.  This will break if the two rows are not adjacent
        # but I do not think that happens in practice.  If it does, we just
        # won't report the stats.
        for i in range(0, len(all_lines) - 1):
            names_split = all_lines[i].split()
            values_split = all_lines[i + 1].split()
            # Check the row names are the same.
            if names_split[0] == values_split[0] and len(names_split) == len(
                values_split
            ):
                field_names.extend(names_split)
                field_values.extend(values_split)

        if not collector:
            collector = {}

        # Now go back and look for the actual stats we care about.
        for i in range(0, len(field_names)):
            if field_names[i] == "InOctets":
                collector.update({Metric("app.net.bytes", "in"): field_values[i]})
            elif field_names[i] == "OutOctets":
                collector.update({Metric("app.net.bytes", "out"): field_values[i]})
            elif field_names[i] == "TCPRenoRecovery":
                retransmits += int(field_values[i])
                found_retransmit_metric = True
            elif field_names[i] == "TCPSackRecovery":
                retransmits += int(field_values[i])
                found_retransmit_metric = True

        # If we found both forms of retransmit, add them up.
        if found_retransmit_metric:
            collector.update({Metric("app.net.tcp_retransmits", None): retransmits})
        return collector


class SockStatReader(BaseReader):
    """NOTE:  This is not a per-process stat file, so this reader is DISABLED for now.

    Reads and records statistics from the /proc/$pid/net/sockstat file.

    The recorded metrics are listed below.  They all also have an app=[id] field as well.
      app.net.sockets_in_use type=*:  The number of sockets in use
    """

    def __init__(self, pid, monitor_id, logger):
        BaseReader.__init__(self, pid, monitor_id, logger, "/proc/%ld/net/sockstat")

    def gather_sample(self, stat_file, collector=None):
        """Gathers the metrics from the sockstat file.

        @param stat_file: The file to read.
        @type stat_file: FileIO
        @param collector: Optional collector dictionary
        @type collector: None or dict
        """

        if not collector:
            collector = {}

        for line in stat_file:
            # We just look for the different "inuse" lines and output their
            # socket type along with the count.
            m = re.search(r"(\w+): inuse (\d+)", line)
            if m is not None:
                collector.update(
                    {
                        Metric("app.net.sockets_in_use", m.group(1).lower()): int(
                            m.group(2)
                        )
                    }
                )
        return collector


# Reads stats from /proc/$pid/fd.
class FileDescriptorReader:
    """
    Reads and records statistics from the /proc/$pid/fd directory.  Essentially it just counts the number of entries.
    The recorded metrics are listed below.  They all also have an app=[id] field as well.
    app.io.fds type=open:         the number of open file descriptors
    """

    def __init__(self, pid, monitor_id, logger):
        """Initializes the reader.

        @param pid: The id of the process
        @param monitor_id: The id of the monitor instance
        @param logger: The logger to use to record metrics

        @type pid: int
        @type monitor_id: str
        @type logger: scalyr_agent.AgentLogger
        """
        self.__pid = pid
        self.__monitor_id = monitor_id
        self.__logger = logger
        self.__metric_printer = MetricPrinter(logger, monitor_id)
        self.__path = "/proc/%ld/fd" % pid

    def run_single_cycle(self, collector=None):
        """

        @return:
        @rtype:
        """
        num_fds = None
        try:
            num_fds = len(os.listdir(self.__path))
        except OSError as e:
            # ignore file not found errors, it just means the process
            # is dead so just continue but return
            # 0 open fds.  Rethrow all other exceptions
            if e.errno != errno.ENOENT:
                raise e

        if not collector:
            collector = {}

        if num_fds is not None:
            collector.update({Metric("app.io.fds", "open"): num_fds})
        return collector

    def close(self):
        pass


class ProcessTracker(object):
    """
    This class is responsible for gathering the metrics for a process.
    Given a process id, it procures and stores different metrics using
    metric readers (deriving from BaseReader)

    This tracker records the following metrics:
      app.cpu type=user:                the number of 1/100ths seconds of user cpu time
      app.cpu type=system:              the number of 1/100ths seconds of system cpu time
      app.uptime:                       the number of milliseconds of uptime
      app.threads:                      the number of threads being used by the process
      app.nice:                         the nice value for the process
      app.mem.bytes type=vmsize:        the number of bytes of virtual memory in use
      app.mem.bytes type=resident:      the number of bytes of resident memory in use
      app.mem.bytes type=peak_vmsize:   the maximum number of bytes used for virtual memory for process
      app.mem.bytes type=peak_resident: the maximum number of bytes of resident memory ever used by process
      app.mem.majflt:                   the number of page faults requiring physical I/O.
      app.disk.bytes type=read:         the number of bytes read from disk
      app.disk.requests type=read:      the number of disk requests.
      app.disk.bytes type=write:        the number of bytes written to disk
      app.disk.requests type=write:     the number of disk requests.
      app.io.fds type=open:             the number of file descriptors held open by the process
      app.io.wait:                      the number of aggregated block I/O delays, in 1/100ths of a second.
    """

    def __init__(self, pid, logger, monitor_id=None):
        self.pid = pid
        self.monitor_id = monitor_id
        self._logger = logger
        self.gathers = [
            StatReader(self.pid, self.monitor_id, self._logger),
            StatusReader(self.pid, self.monitor_id, self._logger),
            IoReader(self.pid, self.monitor_id, self._logger),
            FileDescriptorReader(self.pid, self.monitor_id, self._logger),
        ]

        # TODO: Re-enable these if we can find a way to get them to truly report
        # per-app statistics.
        #        NetStatReader(self.pid, self.id, self._logger)
        #        SockStatReader(self.pid, self.id, self._logger)

    def collect(self):
        """
        Collects the metrics from the gathers
        """

        collector = {}
        for gather in self.gathers:
            try:
                stats = gather.run_single_cycle(collector=collector)
                if stats:
                    collector.update(stats)
            except Exception as ex:
                self._logger.exception(
                    "Exception while collecting metrics for PID: %s of type: %s. Details: %s",
                    self.pid,
                    type(gather),
                    repr(ex),
                )
        return collector

    def __repr__(self):
        return "<ProcessTracker pid=%s,monitor_id=%s>" % (self.pid, self.monitor_id)


class ProcessList(object):
    """
    Class that encapsulates the listing of process(es) based on IDs, regular expressions etc.
    """

    def __init__(self):
        # list of {'pid': processid, 'ppid': parentprocessid,  'cmd': command }
        self.processes = []
        # key -> parent process id, value -> [child process ids...]
        self.parent_to_children_map = defaultdict(list)

        cmd = ["ps", "axo", "pid,ppid,command"]
        sub_proc = Popen(cmd, shell=False, stdout=PIPE)
        # regex intended to capture pid, ppid and the command eg:
        # 593     0 /bin/bash
        regex = r"\s*(\d+)\s+(\d+)\s+(.*)"
        # 2->TODO stdout is binary in Python3
        sub_proc_output = sub_proc.stdout.read()
        sub_proc_output = sub_proc_output.decode("utf-8", "replace")
        for line in sub_proc_output.splitlines(True):
            match = re.search(regex, line)
            if match:
                _pid, _ppid, _cmd = match.groups()
                self.processes.append(
                    {"pid": int(_pid), "ppid": int(_ppid), "cmd": _cmd}
                )

        current_pid = os.getpid()
        for _process in self.processes:
            ppid = _process["ppid"]
            pid = _process["pid"]
            if ppid != pid:
                self.parent_to_children_map[ppid].append(pid)

            if pid == current_pid:
                self._current_process = _process

    @property
    def current_process(self):
        """Return the process of the agent."""
        return self._current_process

    def get_matches_commandline(self, match_pattern):
        """
        Given a string, match the processes on the name
        @param match_pattern: process command match pattern
        @return: List of Process IDs
        """

        matches = []
        for _process in self.processes:
            if re.search(match_pattern, _process["cmd"]):
                matches.append(_process["pid"])
        return matches

    def get_child_processes(self, ppid):
        """
        Given a process id, return all children processes (recursively)
        @param ppid: parent process id
        @return: list of all children process ids
        """

        all_children = []
        children_to_explore = set()
        for _pid in self.parent_to_children_map[ppid]:
            all_children.append(_pid)
            children_to_explore.add(_pid)

        # get the children 'recursively'
        while children_to_explore:  # the invariant
            child_to_explore = children_to_explore.pop()
            if not self.parent_to_children_map.get(child_to_explore):
                continue
            unvisited = self.parent_to_children_map[child_to_explore]
            for node in unvisited:
                if node not in all_children:
                    children_to_explore.add(node)
                    all_children.append(node)
        return list(set(all_children))

    def get_running_processes(self):
        """
        Returns a list of all running process ids
        """

        all_processes = []
        for _process in self.processes:
            all_processes.append(_process["pid"])
        return all_processes

    def get_matches_commandline_with_children(self, match_pattern):
        """
        Like get_matches_commandline method, given a string, match the processes on the name
        but also returns the matched processes' children
        @param match_pattern: process command match pattern
        @return: List of Process IDs
        """

        matched_pids = self.get_matches_commandline(match_pattern)
        for matched_pid in matched_pids:
            matched_pids.extend(self.get_child_processes(matched_pid))
        return list(set(matched_pids))


class ProcessMonitor(ScalyrMonitor):  # pylint: disable=monitor-not-included-for-win32
    # fmt: off
    r"""
# Linux Process Metrics

Import CPU consumption, memory usage, and other metrics for a process, or group of processes, on a Linux server.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).

You can use this plugin to monitor resource usage for a web server, database, or other application.


## Installation

1\. Install the Scalyr Agent

If you haven't already done so, install the [Scalyr Agent](https://app.scalyr.com/help/welcome) on the Linux server.


2\. Configure the Scalyr Agent to import process metrics

Open the Scalyr Agent configuration file, located at `/etc/scalyr-agent-2/agent.json`.

Find the `monitors: [ ... ]` section and add a `{...}` stanza with the `module` property set for linux process metrics:

    monitors: [
      {
         module:      "scalyr_agent.builtin_monitors.linux_process_metrics",
         id:          "tomcat",
         commandline: "java.*tomcat6",
      }
    ]

The `id` property lets you identify the process you are monitoring. It is included in each event as a field named `instance`. The `commandline` property is a [regular expression](https://app.scalyr.com/help/regex), matching on the command line output of `ps aux`. If multiple processes match, only the first is used by default. The above example imports metrics for the first process whose command line output matches the regular expression `java.*tomcat6`.

To group *all* processes that match `commandline`, add the property `aggregate_multiple_processes`, and set it to `true`. Each metric will be a summation for all matched processes. For example, the `app.cpu` metric will sum CPU used for all matched processes. To match all processes whose command line output matches the regular expression `java.*tomcat6`:


    monitors: [
      {
         module:      "scalyr_agent.builtin_monitors.linux_process_metrics",
         id:          "tomcat",
         commandline: "java.*tomcat6",
         aggregate_multiple_processes: true
      }
    ]


You can also include child processes created by matching processes. Add the `include_child_processes` property, and set it to `true`. Any process whose parent matches `commandline` will be included in the summated metrics. This property is resursive; any children of the child processes will also be included. For example, to match all processes, and all child processes whose command line output matches the regular expression `java.*tomcat6`:


    monitors: [
      {
         module:      "scalyr_agent.builtin_monitors.linux_process_metrics",
         id:          "tomcat",
         commandline: "java.*tomcat6",
         aggregate_multiple_processes: true,
         include_child_processes: true
      }
    ]


You can select a process by process identifier (PID), instead of a `commandline` regex. See [Configuration Options](#options) below.

To import metrics for more than one process, add a a separate `{...}` stanza for each, and set a uniqe `id`.


3\. Save and confirm

Save the `agent.json` file. The Agent will detect changes within 30 seconds. Wait a few minutes for the Scalyr Agent to begin sending data.

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.


4.\ Configure the process metrics dashboard for each `id`

Log into Scalyr and click Dashboards > Linux Process Metrics. The dropdowns at the top of the page let you select the `serverHost` and `process` of interest. (We map the `instance` field, discussed above, to the `process` dropdown).

Click `...` in upper right of the page, then select "Edit JSON". Find these lines near the top of the JSON file:

    // On the next line, list each "id" that you've used in a linux_process_metrics
    // clause in the Scalyr Agent configuration file (agent.json).
    values: [ "agent" ]

The "agent" id is used to report metrics for the Scalyr Agent itself. Add each `id` you created to the `values` list. For example, to add "tomcat":

    values: [ "agent", "tomcat" ]

Click "Save File". The dashboard only shows some of the data collected by this plugin. To view all data, go to Search view and query [monitor = 'linux_process_metrics'](https://app.scalyr.com/events?filter=monitor+%3D+%27linux_process_metrics%27).

For help, contact us at [support@scalyr.com](mailto:support@scalyr.com).

    """
    # fmt: on

    def _initialize(self):
        """Performs monitor-specific initialization."""
        # The ids of the processes being monitored, if one has been matched.
        self.__pids = []

        self.__id = self._config.get(
            "id", required_field=True, convert_to=six.text_type
        )
        self.__commandline_matcher = self._config.get(
            "commandline", default=None, convert_to=six.text_type
        )
        self.__aggregate_multiple_processes = self._config.get(
            "aggregate_multiple_processes", default=False, convert_to=bool
        )
        self.__include_child_processes = self._config.get(
            "include_child_processes", default=False, convert_to=bool
        )

        self.__trackers = {}  # key -> process id, value -> ProcessTracker object

        # poll interval (in seconds) for matching processes when we are monitoring multiple processes
        # alive for all epochs of the monitor.
        self.__last_discovered = None

        self.__process_discovery_interval = self._config.get(
            "process_discovery_interval", default=120, convert_to=int
        )

        self.__target_pids = self._config.get(
            "pid", default=None, convert_to=six.text_type
        )
        if self.__target_pids:
            self.__target_pids = self.__target_pids.split(",")
        else:
            self.__target_pids = []

        # Last 2 values of all metrics which has form:
        # {
        #   '<process id>: {
        #                 <metric name>: [<metric at time 0>, <metric at time 1>],
        #                 <metric name>: [<metric at time 0>, <metric at time 1>],
        #                 }

        #   '<process id>: {
        #                 <metric name>: [<metric at time 0>, <metric at time 1>],
        #                 <metric name>: [<metric at time 0>, <metric at time 1>],
        #                 }
        # }
        self.__metrics_history = defaultdict(dict)

        # running total of metric values, both for cumulative and non-cumulative metrics
        self.__aggregated_metrics = {}

        if not (self.__commandline_matcher or self.__target_pids):
            raise BadMonitorConfiguration(
                "At least one of the following fields must be provide: commandline or pid",
                "commandline",
            )

        # Make sure to set our configuration so that the proper parser is used.
        self.log_config = {
            "parser": "agent-metrics",
            "path": "linux_process_metrics.log",
        }

    def record_metrics(self, pid, metrics):
        """
        For a process, record the metrics in a historical metrics collector
        Collects the historical result of each metric per process in __metrics_history

        @param pid: Process ID
        @param metrics: Collected metrics of the process
        @type pid: int
        @type metrics: dict
        @return: None
        """

        for _metric, _metric_value in metrics.items():
            if not self.__metrics_history[pid].get(_metric):
                self.__metrics_history[pid][_metric] = []
            self.__metrics_history[pid][_metric].append(_metric_value)
            # only keep the last 2 running history for any metric
            self.__metrics_history[pid][_metric] = self.__metrics_history[pid][_metric][
                -2:
            ]

    def _reset_absolute_metrics(self):
        """
        At the beginning of each process metric calculation, the absolute (non-cumulative) metrics
        need to be overwritten to the combined process(es) result. Only the cumulative
        metrics need the previous value to calculate delta. We should set the
        absolute metric to 0 in the beginning of this "epoch"
        """

        for pid, process_metrics in self.__metrics_history.items():
            for _metric, _metric_values in process_metrics.items():
                if not _metric.is_cumulative:
                    self.__aggregated_metrics[_metric] = 0

    def _calculate_aggregated_metrics(self):
        """
        Calculates the aggregated metric values based on the current running processes
        and the historical metric record
        """

        # using the historical values, calculate the aggregate
        # there are two kinds of metrics:
        # a) cumulative metrics - only the delta of the last 2 recorded values is used (eg cpu cycles)
        # b) absolute metrics - the last absolute value is used

        running_pids_set = set(self.__pids)

        for pid, process_metrics in self.__metrics_history.items():
            for _metric, _metric_values in process_metrics.items():
                if not self.__aggregated_metrics.get(_metric):
                    self.__aggregated_metrics[_metric] = 0
                if _metric.is_cumulative:
                    if pid in running_pids_set:
                        if len(_metric_values) > 1:
                            # only report the cumulative metrics for more than one sample
                            self.__aggregated_metrics[_metric] += (
                                _metric_values[-1] - _metric_values[-2]
                            )
                else:
                    if pid in running_pids_set:
                        # absolute metric - accumulate the last reported value
                        self.__aggregated_metrics[_metric] += _metric_values[-1]

    def _remove_dead_processes(self):
        # once the _calculate_aggregated_metrics has calculated the running total of the
        # metrics for the current epoch, remove the entries for the process id in the history
        # NOTE: the removal of the contributions (if applicable) should already be done so
        # removing the entry from the history is safe.

        all_pids = list(self.__metrics_history.keys())
        for _pid_to_remove in list(set(all_pids) - set(self.__pids)):
            # for all the absolute metrics, decrease the count that the dead processes accounted for
            del self.__metrics_history[_pid_to_remove]
            # remove it from the tracker
            if _pid_to_remove in self.__trackers:
                del self.__trackers[_pid_to_remove]

        # if no processes are running, there is no reason to report the running metric data
        if not self.__pids:
            self.__aggregated_metrics = {}

    def gather_sample(self):
        """Collect the per-process tracker for the monitored process(es).

        For multiple processes, there are a few cases we need to poll for:

        For `n` processes, if there are < n running processes at any given point,
        we should see if there are any pids or matching expression that gives pids
        that is currently not running, if so, get its tracker and run it.
        It is possible that one or more processes ran its course, but we can't assume that
        and we should keep polling for it.
        """

        for _pid in self._select_processes():
            if not self.__trackers.get(_pid):
                self.__trackers[_pid] = ProcessTracker(_pid, self._logger, self.__id)

        self._reset_absolute_metrics()

        for _tracker in self.__trackers.values():
            _metrics = _tracker.collect()
            self.record_metrics(_tracker.pid, _metrics)

        self._calculate_aggregated_metrics()
        self._remove_dead_processes()

        self.print_metrics()

    def print_metrics(self):
        # For backward compatibility, we also publish the monitor id as 'app' in all reported stats.  The old
        # Java agent did this and it is important to some dashboards.
        for _metric, _metric_value in self.__aggregated_metrics.items():
            extra = {"app": self.__id}
            if _metric.type:
                extra["type"] = _metric.type
            self._logger.emit_value(_metric.name, _metric_value, extra)

    @staticmethod
    def __is_running(pid):
        """Returns true if the current process is still running.

        @return:  True if the monitored process is still running.
        @rtype: bool
        """
        try:
            # signal flag 0 does not actually try to kill the process but does an error
            # check that is useful to see if a process is still running.
            os.kill(pid, 0)
            return True
        except OSError as e:
            # Errno #3 corresponds to the process not running.  We could get
            # other errors like this process does not have permission to send
            # a signal to self.pid.  But, if that error is returned to us, we
            # know the process is running at least, so we ignore the error.
            return e.errno != errno.ESRCH

    def _select_processes(self):
        """Returns a list of the process ids of processes that fulfills the match criteria.

        This will either use the commandline matcher or the target pid to find the process.
        If no process is matched, an empty list is returned.

        @return: The list of process id(s) of the matching process, or set()
        @rtype: list
        """

        # check if at least one process is running
        is_running = False
        for pid in self.__pids:
            if ProcessMonitor.__is_running(pid):
                is_running = True
                break  # at least one process is running

        if is_running:
            if not self.__aggregate_multiple_processes:
                return self.__pids

            # aggregate metrics, check the last discovered time
            if (
                self.__last_discovered
                and time.time() * 1000 - self.__last_discovered
                < self.__process_discovery_interval * 1000
            ):
                return self.__pids

        ps = ProcessList()
        if self.__commandline_matcher:
            self.__last_discovered = time.time() * 1000
            if self.__include_child_processes:
                matched_processes = ps.get_matches_commandline_with_children(
                    self.__commandline_matcher
                )
            else:
                matched_processes = ps.get_matches_commandline(
                    self.__commandline_matcher
                )
            self.__pids = matched_processes

            if not self.__aggregate_multiple_processes and len(self.__pids) > 1:
                # old behaviour where multiple processes were not supported for aggregation
                self._logger.warning(
                    "Multiple processes match the command '%s'.  Returning existing pid. "
                    "You can turn on the multi process aggregation support by adding the "
                    "aggregate_multiple_processes configuration to true"
                    % self.__commandline_matcher,
                    limit_once_per_x_secs=300,
                    limit_key="linux-process-monitor-existing-pid",
                )
                self.__pids = [self.__pids[0]]
        else:
            # See if the specified target pid is running.  If so, then return it.
            # Special cases:
            #   '$$' mean this process.
            #   '$$TBD' mean that the PID of the target process has not been determined yet and it will be set later.
            pids = []
            if self.__target_pids:
                for t_pid in self.__target_pids:
                    if t_pid == "$$":
                        t_pid = int(os.getpid())

                    # skip this until it will be replaced with a real PID.
                    elif t_pid == "$$TBD":
                        continue
                    else:
                        t_pid = int(t_pid)
                    pids.append(t_pid)
            self.__pids = pids
        return self.__pids

    def set_pid(self, pid):  # type: (int) -> None
        """
        Set the PID of the process that was marked as $$TBD.
        :param pid: Process PID
        """
        for i in range(len(self.__target_pids)):
            if self.__target_pids[i] == "$$TBD":
                self.__target_pids[i] = pid
                break

    @property
    def process_monitor_id(self):  # type: () -> six.text_type
        return self.__id


__all__ = ["ProcessMonitor"]
