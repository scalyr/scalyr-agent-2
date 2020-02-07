#!/usr/bin/python

from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals
import os
import random
import time
import sys


def main():
    """iostats main loop."""

    while True:
        # A ppid of 1 means our parent has died.
        if os.getppid() == 1:
            sys.exit(1)

        ts = int(time.time())
        print("gauss %d %f" % (ts, random.gauss(0.5, 0.25)))
        print("uniform %d %f" % (ts, random.random()))
        sys.stdout.flush()
        time.sleep(5)

if __name__ == "__main__":
    main()
