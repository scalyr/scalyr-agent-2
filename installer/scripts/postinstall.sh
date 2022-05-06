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

# {{ check-python }} # this placeholder has to replaced during the build with a functions that checks python version.

# Return success if the current symlinks point to a valid Python interpreter (2.7, or >= 3.5)
is_current_python_valid() {
  # Parse currently used python command from the shebang from currently configured main script.
  # shellcheck disable=SC2155
  local command=$(cat /usr/share/scalyr-agent-2/bin/scalyr-agent-2 | head -n1 | grep -Eo "python[0-9]")
  local exit_code=$?
  # Get version of the current used Python.
  if [[ -z "${command}" || "${exit_code}" -ne "0" ]]; then return 1; fi
  # shellcheck disable=SC2155
  local current_version=$(/usr/share/scalyr-agent-2/bin/scalyr-agent-2-config --report-python-version | grep -Eo "[0-9](.[0-9]+)+");
  exit_code=$?
  if [[ -z "${current_version}" || "${exit_code}" -ne "0" ]]; then return 1; fi
  is_python_valid "$command" "$current_version"
}

switch_python() {
  local python_bin_name=$1

  # Verify that a suitable Python version is available and set up the agent symlinks
  if is_python_valid "$python_bin_name" ; then
    echo "+ The Scalyr Agent will use the default system $python_bin_name binary (/usr/bin/env $python_bin_name)."
    /usr/share/scalyr-agent-2/bin/scalyr-switch-python "$python_bin_name"
    return 0
  fi

  return 1
}

check_python_version() {
  # Check to see if the current symlink setup points to a valid python interpreter.  If we are already good, then
  # we do not need to change anything.  This handles the case where a customer may have already changed the symlink
  # to something like python3 (as long as it is valid, we do not tweak it).
  if is_current_python_valid; then
    return 0
  fi

  echo ". Trying to switch the Python interpreter for the Scalyr Agent."

  # Verify that a suitable Python version is available and set up the agent symlinks
  if switch_python "python" || switch_python "python2" || switch_python "python3" ; then
    return 0
  fi

  echo "Warning, no valid Python interpreter found."
}

# Function which ensures that the provided file path permissions for "group" match the
# provided permission bit in octal notation.
# This function can operate on a file or on a directory.
ensure_path_group_permissions() {
  file_path=$1
  wanted_permissions_group=$2

  if [ "${wanted_permissions_group}" -lt 0 ] || [ "${wanted_permissions_group}" -gt 7 ]; then
    echo "wanted_permissions_group value needs to be between 0 and 7"
    return 1
  fi

  # Will output permissions on octal mode - xyz, e.g. 644
  file_permissions=$(stat -c %a "${file_path}")
  # Permissions for owner - e.g. 6
  file_permissions_owner=$(echo -n "$file_permissions" | head -c 1)
  # Permissions for group - e.g. 4
  file_permissions_group=$(echo -n "$file_permissions" | head -c 2 | tail -c 1)
  # Permissions for other - e.g. 4
  file_permissions_others=$(echo -n "$file_permissions" | tail -c 1)

  # NOTE: We re-use existing fs permissions for owner and other
  if [ "${file_permissions_group}" -ne "${wanted_permissions_group}" ]; then
    new_permissions="${file_permissions_owner}${wanted_permissions_group}${file_permissions_others}"
    echo "Changing permissions for file ${file_path} from \"${file_permissions}\" to \"${new_permissions}\"."

    # NOTE: On CI chmod sometimes fails with 'getpwuid(): uid not found: 1001' which is likely
    # related to some unfinished provisioning on the CI or similar. We simply ignore any
    # errors returned by chmod.
    set +e
    set +o pipefail
    chmod "${new_permissions}" "${file_path}" > /dev/null 2>&1 || true;
    set -e
    set -o pipefail
  fi
}

# Function which ensures that the provided file path permissions for "other" users match the
# provided permission bit in octal notation.
# This function can operate on a file or on a directory.
ensure_path_other_permissions() {
  file_path=$1
  wanted_permissions_other=$2

  if [ "${wanted_permissions_other}" -lt 0 ] || [ "${wanted_permissions_other}" -gt 7 ]; then
    echo "wanted_permissions_other value needs to be between 0 and 7"
    return 1
  fi

  # Will output permissions on octal mode - xyz, e.g. 644
  file_permissions=$(stat -c %a "${file_path}")
  # Permissions for owner and group - e.g. 644
  file_permissions_owner_group=$(echo -n "$file_permissions" | head -c 2)
  # Permissions for other - e.g. 4
  file_permissions_others=$(echo -n "$file_permissions" | tail -c 1)

  # NOTE: We re-use existing fs permissions for owner and group
  if [ "${file_permissions_others}" -ne "${wanted_permissions_other}" ]; then
    new_permissions="${file_permissions_owner_group}${wanted_permissions_other}"
    echo "Changing permissions for file ${file_path} from \"${file_permissions}\" to \"${new_permissions}\"."

    # NOTE: On CI chmod sometimes fails with 'getpwuid(): uid not found: 1001' which is likely
    # related to some unfinished provisioning on the CI or similar. We simply ignore any
    # errors returned by chmod.
    set +e
    set +o pipefail
    chmod "${new_permissions}" "${file_path}" > /dev/null 2>&1 || true;
    set -e
    set -o pipefail
  fi
}

# Function which ensures that the provided file path is not readable by "other" users aka has
# "0" value for permission in the octal notation. If permissions don't match, we update them
# and ensure value for the user part is "0".
# This function can operate on a file or on a directory.
ensure_path_not_readable_by_others() {
  file_path=$1
  ensure_path_other_permissions "${file_path}" "0"
}

check_python_version

config_owner=$(stat -c %U /etc/scalyr-agent-2/agent.json)
script_owner=$(stat -c %U /usr/share/scalyr-agent-2/bin/scalyr-agent-2)

# Determine if the agent had been previously configured to run as a
# different user than root.  We can determine this if agent.json
# has a different user.  If so, then make sure the newly installed files
# (like agent.sh) are changed to the correct owners.
if [ "$config_owner" != "$script_owner" ]; then
  echo "Changing owner for /etc/scalyr-agent-2/agent.json file from $script_owner to $config_owner"
  /usr/share/scalyr-agent-2/bin/scalyr-agent-2-config --set_user "$config_owner" > /dev/null 2>&1;
fi

# Ensure /etc/scalyr-agent-2/agent.json file is not readable by others
ensure_path_not_readable_by_others "/etc/scalyr-agent-2/agent.json"

# We also change agent.d group permissions to 751 since it used to be 771 due to default fpm behavior
ensure_path_group_permissions "/etc/scalyr-agent-2/agent.d" "5"

# Ensure agent.d/*.json files are note readable by others
# NOTE: Most software gives +x bit on *.d directories so we do the same
ensure_path_other_permissions "/etc/scalyr-agent-2/agent.d" "1"

if [ -d "/etc/scalyr-agent-2/agent.d" ]; then
  # NOTE: find + -print0 correctly handles whitespaces in  filenames and it's more robust than for,
  # but it may have cross platform issues. In that case we may need to revert to for.
  #for config_fragment_path in /etc/scalyr-agent-2/agent.d/*.json; do
  find /etc/scalyr-agent-2/agent.d/ -name "*.json" -print0 | while read -r -d $'\0' config_fragment_path; do
    ensure_path_not_readable_by_others "${config_fragment_path}"
  done
fi

# If this file exists this tells the installer that the service is managed by
# systemd and not init.d by default.
if [ -f "/etc/scalyr-agent-2/systemd_managed" ]; then
    echo "Found \"/etc/scalyr-agent-2/systemd_managed\" file which indicates service life cycle is managed using systemd, not creating any init.d symlinks"
else
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
fi

# Do a restart of the service if we are either installing/upgrading the
# package, instead of removing it.  For an RPM, a remove is indicated by
# a zero being passed into $1 (instead of 1 or higher).  For Debian, a
# remove is indicated something other than "configure" being passed into $1.
if [[ "$1" =~ ^[0-9]+$ && $1 -gt 0 ]] || [ "$1" == "configure" ]; then
  /etc/init.d/scalyr-agent-2 condrestart --quiet;

  exit $?;
else
  exit 0;
fi
