#!/bin/bash

config_owner=`stat -c %U /etc/scalyr-agent-2/agent.json`
script_owner=`stat -c %U /usr/share/scalyr-agent-2/bin/scalyr-agent-2`

# Determine if the agent had been previously configured to run as a
# different user than root.  We can determine this if agentConfig.json
# has a different user.  If so, then make sure the newly installed files
# (like agent.sh) are changed to the correct owners.
if [ "$config_owner" != "$script_owner" ]; then
  /usr/share/scalyr-agent-2/bin/scalyr-agent-2-config --set_user $config_owner > /dev/null 2>&1;
fi

# Add in the symlinks in the appropriate /etc/rcX.d/ directories
# to stop and start the service at boot time.
if [ -f /sbin/chkconfig -o -f /usr/sbin/chkconfig ]; then
  # For Redhat-based systems, use chkconfig to create links.
  chkconfig --add scalyr-agent-2;
elif [ -f /usr/sbin/update-rc.d -o -f /sbin/update-rc.d ]; then
  # For Debian-based systems, update-rc.d does the job.
  update-rc.d scalyr-agent-2 defaults 98 02;
else
  # Otherwise just fall back to creating them manually.
  for x in 0 1 6; do
    ln -s /etc/init.d/scalyr-agent-2 /etc/rc$x.d/K02scalyr-agent-2;
  done

  for x in 2 3 4 5; do
    ln -s /etc/init.d/scalyr-agent-2 /etc/rc$x.d/S98scalyr-agent-2;
  done
fi

# Do a restart of the service if we are either installing/upgrading the
# package, instead of removing it.  For an RPM, a remove is indicated by
# a zero being passed into $1 (instead of 1 or higher).  For Debian, a
# remove is indicated something other than "configure" being passed into $1.
if [[ "$1" =~ ^[0-9]+$ && $1 -gt 0 ]] || [ "$1" == "configure" ]; then
  service scalyr-agent-2 condrestart --quiet;
  exit $?;
else
  exit 0;
fi