#!/bin/bash
# Copyright 2014-2020 Scalyr Inc.
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


echo "Entering postinstall"
ls -l /etc/init.d
echo "Second"
ls -l /etc/init.d/
echo "Third"
ls -l /etc/init.d/scalyr-agent-2

# Used below to execute a command to retrieve the Python interpreter version.
run_and_check_persion_version() {
  command=$1
  version=$(${command} 2>&1 | grep -o "[0-9].[0-9]")
  exit_code=$?

  # shellcheck disable=SC2072,SC2071
  if [[ -z "${version}" || "${exit_code}" -ne "0" ]]; then
    return 1
  elif [[ "$version" < "2.6" ]]; then
    echo "Python ${version} is found but the minimum version for Python 2 is 2.6."
    return 1
  elif [[ "$version" > "3" && "$version" < "3.5" ]]; then
    echo "Python ${version} is found but the minimum version for Python 3 is 3.5."
    return 1
  else
    return 0
  fi
}

# Checks to see if `/usr/bin/env $1` is a valid Python interpreter (2.6, 2.7, or >= 3.5)
is_python_valid() {
  command=$1
  run_and_check_persion_version "/usr/bin/env ${command} --version"
}

# Return success if the current symlinks point to a valid Python interpreter (2.6, 2.7, or >= 3.5)
is_current_python_valid() {
  run_and_check_persion_version "/usr/share/scalyr-agent-2/bin/scalyr-agent-2-config --report-python-version" > /dev/null 2>&1;
}

check_python_version() {
  # Check to see if the current symlink setup points to a valid python interpreter.  If we are already good, then
  # we do not need to change anything.  This handles the case where a customer may have already changed the symlink
  # to something like python3 (as long as it is valid, we do not tweak it).
  if is_current_python_valid; then
    return 0
  fi

  echo "Switching the Python interpreter used by the Scalyr Agent."
  # Verify that a suitable Python version is available and set up the agent symlinks
  if is_python_valid python; then
    # 'python' command exists
    echo "The Scalyr Agent will use the default system python binary (/usr/bin/env python)."
    /usr/share/scalyr-agent-2/bin/scalyr-switch-python default
    return 0
  fi

  echo "The default 'python' command not found, will use python2 binary (/usr/bin/env python2) for running the agent."
  if is_python_valid python2; then
    /usr/share/scalyr-agent-2/bin/scalyr-switch-python python2
    echo "The Scalyr Agent will use the python2 binary (/usr/bin/env python2)."
    return 0
  fi

  echo "The 'python2' command not found, will use python3 binary (/usr/bin/env python3) for running the agent."
  if is_python_valid python3; then
    echo "The Scalyr Agent will use the python3 binary (/usr/bin/env python3)."
    /usr/share/scalyr-agent-2/bin/scalyr-switch-python python3
    return 0
  fi

  echo "Warning, no valid Python interpreter found."
}

#check_python_version

config_owner=`stat -c %U /etc/scalyr-agent-2/agent.json`
script_owner=`stat -c %U /usr/share/scalyr-agent-2/bin/scalyr-agent-2`

# Determine if the agent had been previously configured to run as a
# different user than root.  We can determine this if agentConfig.json
# has a different user.  If so, then make sure the newly installed files
# (like agent.sh) are changed to the correct owners.
if [ "$config_owner" != "$script_owner" ]; then
  echo "Resetting owner"
  /usr/share/scalyr-agent-2/bin/scalyr-agent-2-config --set_user "$config_owner" > /dev/null 2>&1;
fi

# Add in the symlinks in the appropriate /etc/rcX.d/ directories
# to stop and start the service at boot time.
if [ -f /sbin/chkconfig ] || [ -f /usr/sbin/chkconfig ]; then
  # For Redhat-based systems, use chkconfig to create links.
  chkconfig --add scalyr-agent-2;
elif [ -f /usr/sbin/update-rc.d ] || [ -f /sbin/update-rc.d ]; then
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
