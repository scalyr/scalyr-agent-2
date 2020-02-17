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
#
"""network interface stats for TSDB"""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals
import os
import sys
import time
import socket
import re
from io import open


# /proc/net/dev has 16 fields, 8 for receive and 8 for xmit
# The fields we care about are defined here.  The
# ones we want to skip we just leave empty.
# So we can aggregate up the total bytes, packets, etc
# we tag each metric with direction=in or =out
# and iface=

FIELDS = ("bytes", "packets", "errs", "dropped",
           None, None, None, None,)

COLLECTION_INTERVAL = 30  # seconds

# Scalyr edit:  Check environment variable for collection interval.  TODO:  See if we can centralize code, but
# difficult without requiring collectors including common module which is goes against tcollector architecture.
try:
    if "TCOLLECTOR_SAMPLE_INTERVAL" in os.environ:
        COLLECTION_INTERVAL = float(os.environ["TCOLLECTOR_SAMPLE_INTERVAL"])
except ValueError:
    pass

# Scalyr edit:  Check environment variable for for additional network interface prefixes.
NETWORK_INTERFACE_PREFIX = "eth"

try:
    if "TCOLLECTOR_INTERFACE_PREFIX" in os.environ:
        NETWORK_INTERFACE_PREFIX = os.environ["TCOLLECTOR_INTERFACE_PREFIX"]
except ValueError:
    pass

# Scalyr edit:  Check environment variable for for additional network interface suffix.
NETWORK_INTERFACE_SUFFIX = '\d+'
try:
    if "TCOLLECTOR_INTERFACE_SUFFIX" in os.environ:
        NETWORK_INTERFACE_SUFFIX = os.environ["TCOLLECTOR_INTERFACE_SUFFIX"]
except ValueError:
    pass

def main():
    """ifstat main loop"""
    interval = COLLECTION_INTERVAL

    # Scalyr edit:
    network_interface_prefixes = NETWORK_INTERFACE_PREFIX.split(',')
    for i in range(len(network_interface_prefixes)):
        network_interface_prefixes[i] = network_interface_prefixes[i].strip()

    f_netdev = open("/proc/net/dev", "r")

    # We just care about ethN interfaces.  We specifically
    # want to avoid bond interfaces, because interface
    # stats are still kept on the child interfaces when
    # you bond.  By skipping bond we avoid double counting.
    while True:
        # Scalyr edit to add in check for parent.  A ppid of 1 means our parent has died.
        if os.getppid() == 1:
            sys.exit(1)

        f_netdev.seek(0)
        ts = int(time.time())
        for line in f_netdev:
            # Scalyr edit
            m = None
            for interface in network_interface_prefixes:
                # 2->TODO is it important to expect at least one space character?
                m = re.match("\s*(%s%s):(.*)" % (interface, NETWORK_INTERFACE_SUFFIX), line)
                if m:
                    break
            if not m:
                continue
            stats = m.group(2).split(None)
            for i in range(8):
                if FIELDS[i]:
                    print(
                        "proc.net.%s %d %s iface=%s direction=in"
                        % (FIELDS[i], ts, stats[i], m.group(1))
                    )
                    print(
                        "proc.net.%s %d %s iface=%s direction=out"
                        % (FIELDS[i], ts, stats[i+8], m.group(1))
                    )

        sys.stdout.flush()
        time.sleep(interval)

if __name__ == "__main__":
    main()

