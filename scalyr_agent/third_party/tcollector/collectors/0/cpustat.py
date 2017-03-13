#!/usr/bin/python

"""cpu stats collector TSDB """
#
# cpustat
#
# cpu.count              number of cpus on the system

import os
import socket
import subprocess
import sys
import time


COLLECTION_INTERVAL = 30  # seconds

# Scalyr edit:  Check environment variable for collection interval.  TODO:  See if we can centralize code, but
# difficult without requiring collectors including common module which is goes against tcollector architecture.
try:
    if "TCOLLECTOR_SAMPLE_INTERVAL" in os.environ:
        COLLECTION_INTERVAL = float(os.environ["TCOLLECTOR_SAMPLE_INTERVAL"])
except ValueError:
    pass


def main():
    """cpustat main loop"""

    while True:
        # Scalyr edit to add in check for parent.  A ppid of 1 means our parent has died.
        if os.getppid() == 1:
            sys.exit(1)

        ts = int(time.time())

        nproc = subprocess.Popen(["nproc", "--all"], stdout=subprocess.PIPE)
        stdout, _ = nproc.communicate()
        if nproc.returncode == 0:
            fields = stdout.split()
            if fields[0].isdigit():
                print ("cpu.count %d %s" % (ts, fields[0] ) )
        else:
            print >> sys.stderr, "nproc --all returned %r" % df_proc.returncode

        sys.stdout.flush()
        time.sleep(COLLECTION_INTERVAL)

if __name__ == "__main__":
    main()
