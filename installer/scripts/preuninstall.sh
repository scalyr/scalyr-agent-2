#!/bin/bash

# We only need to tweak the rc config if this is an uninstall of the package
# (rather than just removing this version because we are upgrading to
# a new one).  An uninstall is indicated by $1 == 0 for
# RPM and $1 == "remove" for Debian.
if [ "$1" == "0" -o "$1" == "remove" ]; then
  # Stop the service since we are about to completely remove it.
  service scalyr-agent-2 stop > /dev/null 2>&1

  # Remove the symlinks from the /etc/rcX.d directories.
  if [ -f /sbin/chkconfig -o -f /usr/sbin/chkconfig ]; then
    # For RPM-based systems.
    chkconfig --del scalyr-agent-2;
  elif [ -f /usr/sbin/update-rc.d -o -f /sbin/update-rc.d ]; then
    # For Debian-based systems.
    update-rc.d -f scalyr-agent-2 remove;
  else
    # All others.
    for x in 0 1 6; do
      rm /etc/rc$x.d/K02scalyr-agent-2;
    done

    for x in 2 3 4 5; do
      rm /etc/rc$x.d/S98scalyr-agent-2;
    done
  fi
fi

# Always remove the .pyc files and __pycache__ directories
find /usr/share/scalyr-agent-2 -type f -name '*.py[co]' -delete -o -type d -name __pycache__ -exec rm -r {} \;

exit 0;