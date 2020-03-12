#!/usr/bin/python
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

"""iostat statistics for TSDB"""

# data is from /proc/diskstats

# Calculate disk statistics.  We handle 2.6 kernel output only, both
# pre-2.6.25 and post (which added back per-partition disk stats).
# (diskstats output significantly changed from 2.4).
# The fields (from iostats.txt) are mainly rate counters
# (either number of operations or number of milliseconds doing a
# particular operation), so let's just let TSD do the rate
# calculation for us.
#
# /proc/diskstats has 11 stats for a given device
# these are all rate counters except ios_in_progress
# .read_requests       Number of reads completed
# .read_merged         Number of reads merged
# .read_sectors        Number of sectors read
# .msec_read           Time in msec spent reading
# .write_requests      Number of writes completed
# .write_merged        Number of writes merged
# .write_sectors       Number of sectors written
# .msec_write          Time in msec spent writing
# .ios_in_progress     Number of I/O operations in progress
# .msec_total          Time in msec doing I/O
# .msec_weighted_total Weighted time doing I/O (multiplied by ios_in_progress)

# in 2.6.25 and later, by-partition stats are reported same as disks
# in 2.6 before 2.6.25, partitions have 4 stats per partition
# .read_issued
# .read_sectors
# .write_issued
# .write_sectors
# For partitions, these *_issued are counters collected before
# requests are merged, so aren't the same as *_requests (which is
# post-merge, which more closely represents represents the actual
# number of disk transactions).

# Given that diskstats provides both per-disk and per-partition data,
# for TSDB purposes we want to put them under different metrics (versus
# the same metric and different tags).  Otherwise, if you look at a
# given metric, the data for a given box will be double-counted, since
# a given operation will increment both the disk series and the
# partition series.  To fix this, we output by-disk data to iostat.disk.*
# and by-partition data to iostat.part.*.

# TODO: Add additional tags to map partitions/disks back to mount
# points/swap so you can (for example) plot just swap partition
# activity or /var/lib/mysql partition activity no matter which
# disk/partition this happens to be.  This is nontrivial, especially
# when you have to handle mapping of /dev/mapper to dm-N, pulling out
# swap partitions from /proc/swaps, etc.

# TODO: add some generated stats from iostat -x like svctm, await,
# %util.  These need to pull in cpu idle counters from /proc.


from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

import os
import sys
import time
from io import open

COLLECTION_INTERVAL = 30  # seconds

# Scalyr edit:  Check environment variable for collection interval.  TODO:  See if we can centralize code, but
# difficult without requiring collectors including common module which is goes against tcollector architecture.
try:
    if "TCOLLECTOR_SAMPLE_INTERVAL" in os.environ:
        COLLECTION_INTERVAL = float(os.environ["TCOLLECTOR_SAMPLE_INTERVAL"])
except ValueError:
    pass

# Docs come from the Linux kernel's Documentation/iostats.txt
FIELDS_DISK = (
    "read_requests",  # Total number of reads completed successfully.
    "read_merged",  # Adjacent read requests merged in a single req.
    "read_sectors",  # Total number of sectors read successfully.
    "msec_read",  # Total number of ms spent by all reads.
    "write_requests",  # total number of writes completed successfully.
    "write_merged",  # Adjacent write requests merged in a single req.
    "write_sectors",  # total number of sectors written successfully.
    "msec_write",  # Total number of ms spent by all writes.
    "ios_in_progress",  # Number of actual I/O requests currently in flight.
    "msec_total",  # Amount of time during which ios_in_progress >= 1.
    "msec_weighted_total",  # Measure of recent I/O completion time and backlog.
)

FIELDS_PART = (
    "read_issued",
    "read_sectors",
    "write_issued",
    "write_sectors",
)


def main():
    """iostats main loop."""
    f_diskstats = open("/proc/diskstats", "r")

    while True:
        # Scalyr edit to add in check for parent.  A ppid of 1 means our parent has died.
        if os.getppid() == 1:
            sys.exit(1)

        parse_and_print_metrics(f_diskstats=f_diskstats)

        sys.stdout.flush()
        time.sleep(COLLECTION_INTERVAL)


def parse_and_print_metrics(f_diskstats, output_file_sucess=None, output_file_error=None):
    """
    Parse /proc/diskstats and print metrics to the provided file handle.

    :param f_diskstats: Open file handle to /proc/diskstats file. That's done to avoid re-opening
    the file on each function call / main loop iteration
    """
    output_file_sucess = output_file_sucess or sys.stdout
    output_file_error = output_file_error or sys.stderr

    f_diskstats.seek(0)
    ts = int(time.time())
    for line in f_diskstats:
        # maj, min, devicename, [list of stats, see above]
        values = line.split(None)
        # shortcut the deduper and just skip disks that
        # haven't done a single read.  This elimiates a bunch
        # of loopback, ramdisk, and cdrom devices but still
        # lets us report on the rare case that we actually use
        # a ramdisk.
        if values[3] == "0":
            continue

        if int(values[1]) % 16 == 0 and int(values[0]) > 1:
            metric = "iostat.disk."
        else:
            metric = "iostat.part."

        # Sometimes there can be a slash in the device name, see bug #8.
        # TODO(tsuna): Remove the substitution once TSD allows `/' in tags.
        device = values[2].replace("/", "_")
        # For now we simply ignore values which were added in newer versions of kernel
        if len(values) >= 14:
            # full stats line
            # 14 fields - up to kernel 4.18
            # 18 fields - kernel >= 4.18 - 5.5
            # 20 fields - kernel >= 5.5
            # See https://www.kernel.org/doc/Documentation/ABI/testing/procfs-diskstats for
            # details
            for i in range(11):
                print(
                    "%s%s %d %s dev=%s"
                    % (metric, FIELDS_DISK[i], ts, values[i + 3], device), file=output_file_sucess
                )
        elif len(values) == 7:
            # partial stats line
            for i in range(4):
                print(
                    "%s%s %d %s dev=%s"
                    % (metric, FIELDS_PART[i], ts, values[i + 3], device), file=output_file_sucess
                )
        else:
            print("Cannot parse /proc/diskstats line: ", line, file=output_file_error)
            continue


if __name__ == "__main__":
    main()
