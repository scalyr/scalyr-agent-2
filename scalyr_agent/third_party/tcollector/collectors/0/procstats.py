#!/usr/bin/env python
# This file is part of tcollector.
# Copyright (C) 2010  StumbleUpon, Inc.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.  This program is distributed in the hope that it
# will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Lesser
# General Public License for more details.  You should have received a copy
# of the GNU Lesser General Public License along with this program.  If not,
# see <http://www.gnu.org/licenses/>.
#
"""import various /proc stats from /proc into TSDB"""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals
import os
import sys
import time
import subprocess
import re
from io import open

COLLECTION_INTERVAL = 30  # seconds
NUMADIR = "/sys/devices/system/node"

# Scalyr edit:  Check environment variable for collection interval.  TODO:  See if we can centralize code, but
# difficult without requiring collectors including common module which is goes against tcollector architecture.
try:
    if "TCOLLECTOR_SAMPLE_INTERVAL" in os.environ:
        COLLECTION_INTERVAL = float(os.environ["TCOLLECTOR_SAMPLE_INTERVAL"])
except ValueError:
    pass


def open_sysfs_numa_stats():
    """Returns a possibly empty list of opened files."""
    try:
        nodes = os.listdir(NUMADIR)
    except OSError as error:
        (errno, msg) = error.args
        if errno == 2:  # No such file or directory
            return []  # We don't have NUMA stats.
        raise

    nodes = [node for node in nodes if node.startswith("node")]
    numastats = []
    for node in nodes:
        try:
            numastats.append(open(os.path.join(NUMADIR, node, "numastat")))
        except OSError as error:
            (errno, msg) = error.args
            if errno == 2:  # No such file or directory
                continue
            raise
    return numastats


def print_numa_stats(numafiles):
    """From a list of opened files, extracts and prints NUMA stats."""
    for numafile in numafiles:
        numafile.seek(0)
        node_id = int(numafile.name[numafile.name.find("/node/node") + 10 : -9])
        ts = int(time.time())
        stats = dict(line.split() for line in numafile.read().splitlines())
        for stat, tag in (  # hit: process wanted memory from this node and got it
            ("numa_hit", "hit"),
            # miss: process wanted another node and got it from
            # this one instead.
            ("numa_miss", "miss"),
        ):
            print(
                "sys.numa.zoneallocs %d %s node=%d type=%s"
                % (ts, stats[stat], node_id, tag)
            )
        # Count this one as a separate metric because we can't sum up hit +
        # miss + foreign, this would result in double-counting of all misses.
        # See `zone_statistics' in the code of the kernel.
        # foreign: process wanted memory from this node but got it from
        # another node.  So maybe this node is out of free pages.
        print(
            "sys.numa.foreign_allocs %d %s node=%d"
            % (ts, stats["numa_foreign"], node_id)
        )
        # When is memory allocated to a node that's local or remote to where
        # the process is running.
        for stat, tag in (("local_node", "local"), ("other_node", "remote")):
            print(
                "sys.numa.allocation %d %s node=%d type=%s"
                % (ts, stats[stat], node_id, tag)
            )
        # Pages successfully allocated with the interleave policy.
        print(
            "sys.numa.interleave %d %s node=%d type=hit"
            % (ts, stats["interleave_hit"], node_id)
        )


# Scalyr - print number of cpus
def print_cpu_stats():
    ts = int(time.time())
    nproc = subprocess.Popen(["nproc", "--all"], stdout=subprocess.PIPE)
    stdout, _ = nproc.communicate()
    if nproc.returncode == 0:
        fields = stdout.decode("utf-8").split()
        if fields[0].isdigit():
            print("sys.cpu.count %d %s" % (ts, fields[0]))
    else:
        print("nproc --all returned %r" % nproc.returncode, file=sys.stderr)


def main():
    """procstats main loop"""

    f_uptime = open("/proc/uptime", "r")
    f_meminfo = open("/proc/meminfo", "r")
    f_vmstat = open("/proc/vmstat", "r")
    f_stat = open("/proc/stat", "r")
    f_loadavg = open("/proc/loadavg", "r")
    f_entropy_avail = open("/proc/sys/kernel/random/entropy_avail", "r")
    numastats = open_sysfs_numa_stats()

    while True:
        # Scalyr edit to add in check for parent.  A ppid of 1 means our parent has died.
        if os.getppid() == 1:
            sys.exit(1)

        # proc.uptime
        f_uptime.seek(0)
        ts = int(time.time())
        for line in f_uptime:
            m = re.match(r"(\S+)\s+(\S+)", line)
            if m:
                print("proc.uptime.total %d %s" % (ts, m.group(1)))
                print("proc.uptime.now %d %s" % (ts, m.group(2)))

        # proc.meminfo
        f_meminfo.seek(0)
        ts = int(time.time())
        for line in f_meminfo:
            m = re.match(r"(\w+):\s+(\d+)", line)
            if m:
                print("proc.meminfo.%s %d %s" % (m.group(1).lower(), ts, m.group(2)))

        # proc.vmstat
        f_vmstat.seek(0)
        ts = int(time.time())
        for line in f_vmstat:
            m = re.match(r"(\w+)\s+(\d+)", line)
            if not m:
                continue
            if m.group(1) in (
                "pgpgin",
                "pgpgout",
                "pswpin",
                "pswpout",
                "pgfault",
                "pgmajfault",
            ):
                print("proc.vmstat.%s %d %s" % (m.group(1), ts, m.group(2)))

        # proc.stat
        f_stat.seek(0)
        ts = int(time.time())
        for line in f_stat:
            m = re.match(r"(\w+)\s+(.*)", line)
            if not m:
                continue
            if m.group(1) == "cpu":
                fields = m.group(2).split()
                print("proc.stat.cpu %d %s type=user" % (ts, fields[0]))
                print("proc.stat.cpu %d %s type=nice" % (ts, fields[1]))
                print("proc.stat.cpu %d %s type=system" % (ts, fields[2]))
                print("proc.stat.cpu %d %s type=idle" % (ts, fields[3]))
                print("proc.stat.cpu %d %s type=iowait" % (ts, fields[4]))
                print("proc.stat.cpu %d %s type=irq" % (ts, fields[5]))
                print("proc.stat.cpu %d %s type=softirq" % (ts, fields[6]))
                # really old kernels don't have this field
                if len(fields) > 7:
                    print("proc.stat.cpu %d %s type=steal" % (ts, fields[7]))
                    # old kernels don't have this field
                    if len(fields) > 8:
                        print("proc.stat.cpu %d %s type=guest" % (ts, fields[8]))
            elif m.group(1) == "intr":
                print("proc.stat.intr %d %s" % (ts, m.group(2).split()[0]))
            elif m.group(1) == "ctxt":
                print("proc.stat.ctxt %d %s" % (ts, m.group(2)))
            elif m.group(1) == "processes":
                print("proc.stat.processes %d %s" % (ts, m.group(2)))
            elif m.group(1) == "procs_blocked":
                print("proc.stat.procs_blocked %d %s" % (ts, m.group(2)))

        f_loadavg.seek(0)
        ts = int(time.time())
        for line in f_loadavg:
            m = re.match(r"(\S+)\s+(\S+)\s+(\S+)\s+(\d+)/(\d+)\s+", line)
            if not m:
                continue
            print("proc.loadavg.1min %d %s" % (ts, m.group(1)))
            print("proc.loadavg.5min %d %s" % (ts, m.group(2)))
            print("proc.loadavg.15min %d %s" % (ts, m.group(3)))
            print("proc.loadavg.runnable %d %s" % (ts, m.group(4)))
            print("proc.loadavg.total_threads %d %s" % (ts, m.group(5)))

        f_entropy_avail.seek(0)
        ts = int(time.time())
        for line in f_entropy_avail:
            print("proc.kernel.entropy_avail %d %s" % (ts, line.strip()))

        print_numa_stats(numastats)

        print_cpu_stats()

        sys.stdout.flush()
        time.sleep(COLLECTION_INTERVAL)


if __name__ == "__main__":
    main()
