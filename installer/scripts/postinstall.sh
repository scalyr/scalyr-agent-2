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


config_source_path=$(readlink /usr/share/scalyr-agent-2/bin/scalyr-agent-2-config)
config_base_name=$(basename "${config_source_path}")

is_python_valid(){
  command=$1
  version=$(/usr/bin/env "${command}" --version 2>&1 | grep -o "[0-9].[0-9]")
  # shellcheck disable=SC2072
  if [[ -z "${version}" ]]; then
    return 1
  elif [[ "$version" < "2.6" ]]; then
    echo "Python ${version} is found but the minimum version for python 2 is 2.6."
    return 1
  elif [[ "$version" > "3" && "$version" < "3.5" ]]; then
    echo "Python ${version} is found but the minimum version for python 3 is 3.5."
    return 1
  else
    echo "Found1111 ${version}"
    return 0
  fi
}


check_python_version(){
  if is_python_valid python; then
    # 'python' command exists
    if [[  ${config_base_name} == "config_main.py" ]]; then
      # there is no python version that was done before.
      echo "The Scalyr agent will use the default python."
      /usr/share/scalyr-agent-2/bin/scalyr-switch-python default
      return 0
    fi
  fi
  echo "The defaut 'python' command is not found, will use python2 binary for running the agent."
  if is_python_valid python2;  then

    if [[  ${config_base_name} != "config_main_py3.py" ]]; then
      # if python version was not switched to python3 use python2
      if [[  ${config_base_name} == "config_main_py2.py" ]]; then
        echo "Use python2 version from previous installation."
      fi
      /usr/share/scalyr-agent-2/bin/scalyr-switch-python python2
      return 0
    fi
  fi
  echo "The 'python2' command is not found, will use python3 binary for running the agent."
  if is_python_valid python3; then
      if [[  ${config_base_name} == "config_main_py3.py" ]]; then
        echo "Use python3 version from previous installation."
      else
        /usr/share/scalyr-agent-2/bin/scalyr-switch-python python3
        return 0
      fi
  fi
}

check_python_version

config_owner=`stat -c %U /etc/scalyr-agent-2/agent.json`
script_owner=`stat -c %U /usr/share/scalyr-agent-2/bin/scalyr-agent-2`

# Determine if the agent had been previously configured to run as a
# different user than root.  We can determine this if agentConfig.json
# has a different user.  If so, then make sure the newly installed files
# (like agent.sh) are changed to the correct owners.
if [ "$config_owner" != "$script_owner" ]; then
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
