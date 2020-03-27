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
"""df disk space and inode counts for TSDB """
#
# dfstat.py
#
# df.1kblocks.total      total size of fs
# df.1kblocks.used       blocks used
# df.1kblocks.available  blocks available
# df.inodes.total        number of inodes
# df.inodes.used        number of inodes
# df.inodes.free        number of inodes

# All metrics are tagged with mount= and fstype=
# This makes it easier to exclude stuff like
# tmpfs mounts from disk usage reports.

# Because tsdb does not like slashes in tags, slashes will
# be replaced by underscores in the mount= tag.  In theory
# this could cause problems if you have a mountpoint of
# "/foo/bar/" and "/foo_bar/".


from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals
import os
import subprocess
import sys
import time


COLLECTION_INTERVAL = 30  # seconds
LOCAL_DISKS_ONLY = True

# Scalyr edit:  Check environment variable for collection interval and local disks only.  TODO:  See if we can
# centralize code, but difficult without requiring collectors including common module which is goes against tcollector
# architecture.

try:
    if "TCOLLECTOR_SAMPLE_INTERVAL" in os.environ:
        COLLECTION_INTERVAL = float(os.environ["TCOLLECTOR_SAMPLE_INTERVAL"])
    if "TCOLLECTOR_LOCAL_DISKS_ONLY" in os.environ:
        LOCAL_DISKS_ONLY = os.environ["TCOLLECTOR_LOCAL_DISKS_ONLY"].lower() == "true"
except ValueError:
    pass


def main():
    """dfstats main loop"""

    while True:
        # Scalyr edit to add in check for parent.  A ppid of 1 means our parent has died.
        if os.getppid() == 1:
            sys.exit(1)

        # Scalyr edit: conditional options on whether to restrict to local disks only or not.
        if LOCAL_DISKS_ONLY:
            df_options = "-PlTk"
            df_inodes_options = "-PlTi"
        else:
            df_options = "-PTk"
            df_inodes_options = "-PTi"

        ts = int(time.time())
        # 1kblocks
        df_proc = subprocess.Popen(["df", df_options], stdout=subprocess.PIPE)
        stdout, _ = df_proc.communicate()
        if df_proc.returncode == 0:
            # Scalyr edit.  We've found some systems list the same mount point multiple times in the df output.
            # To prevent duplicte timestamp warnings, we keep track of which mount points we've reported.
            reported_mounts = {}
            for line in stdout.decode("utf-8").split("\n"):  # pylint: disable=E1103
                fields = line.split()
                # skip header/blank lines
                if not line or not fields[2].isdigit():
                    continue
                # Skip mounts/types we don't care about.
                # Most of this stuff is of type tmpfs, but we don't
                # want to blacklist all tmpfs since sometimes it's
                # used for active filesystems (/var/run, /tmp)
                # that we do want to track.
                if fields[1] in ("debugfs", "devtmpfs"):
                    continue
                if fields[6] == "/dev":
                    continue
                # /dev/shm, /lib/init_rw, /lib/modules, etc
                # if fields[6].startswith(("/lib/", "/dev/")):  # python2.5+
                if fields[6].startswith("/lib/"):
                    continue
                if fields[6].startswith("/dev/"):
                    continue

                mount = fields[6]

                # Scalyr edit.
                if mount in reported_mounts:
                    continue
                reported_mounts[mount] = True

                print(
                    "df.1kblocks.total %d %s mount=%s fstype=%s"
                    % (ts, fields[2], mount, fields[1])
                )
                print(
                    "df.1kblocks.used %d %s mount=%s fstype=%s"
                    % (ts, fields[3], mount, fields[1])
                )
                print(
                    "df.1kblocks.free %d %s mount=%s fstype=%s"
                    % (ts, fields[4], mount, fields[1])
                )
        else:
            print(
                "df %s returned %r" % (df_options, df_proc.returncode), file=sys.stderr
            )

        ts = int(time.time())
        # inodes
        df_proc = subprocess.Popen(["df", df_inodes_options], stdout=subprocess.PIPE)
        stdout, _ = df_proc.communicate()
        if df_proc.returncode == 0:
            # Scalyr edit.  We've found some systems list the same mount point multiple times in the df output.
            # To prevent duplicte timestamp warnings, we keep track of which mount points we've reported.
            reported_mounts = {}
            for line in stdout.decode("utf-8").split("\n"):  # pylint: disable=E1103
                fields = line.split()
                if not line or not fields[2].isdigit():
                    continue

                mount = fields[6]

                # Scalyr edit.
                if mount in reported_mounts:
                    continue
                reported_mounts[mount] = True

                print(
                    "df.inodes.total %d %s mount=%s fstype=%s"
                    % (ts, fields[2], mount, fields[1])
                )
                print(
                    "df.inodes.used %d %s mount=%s fstype=%s"
                    % (ts, fields[3], mount, fields[1])
                )
                print(
                    "df.inodes.free %d %s mount=%s fstype=%s"
                    % (ts, fields[4], mount, fields[1])
                )
        else:
            print(
                "df %s returned %r" % (df_inodes_options, df_proc.returncode),
                file=sys.stderr,
            )

        sys.stdout.flush()
        time.sleep(COLLECTION_INTERVAL)


if __name__ == "__main__":
    main()
