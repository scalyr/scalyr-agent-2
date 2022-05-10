#!/usr/bin/env bash
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

# Script which runs AMI based install and upgrade tests for various distros in
# parallel.
#
# Usage: run-ami-tests-in-bg-sh [stable|development]
#

echo_with_date() {
    date +"[%Y-%m-%d %H:%M:%S] $*"
}

# Create directory which output log files will be saved
mkdir -p outputs

TEST_TYPE="$1"
TEST_OS="$2"

if [ -z "${INSTALLER_SCRIPT_URL}" ]; then
    echo_with_date "INSTALLER_SCRIPT_URL environment variable not set"
    exit 1
fi

if [ "${TEST_TYPE}" != "stable" ] && [ "${TEST_TYPE}" != "development" ]; then
    echo_with_date "Test type: 'stable' or 'development' must be specified."
    exit 1
fi

if [ "${TEST_OS}" != "linux" ] && [ "${TEST_OS}" != "windows" ]; then
    echo_with_date "Test OS: 'linux' or 'windows' must be specified."
    exit 1
fi

echo_with_date "Running AMI sanity tests concurrently in the background (this may take up to 10 minutes and no output may be produced by this script for up to 5 minutes)..."
echo_with_date "Using INSTALLER_SCRIPT_URL=${INSTALLER_SCRIPT_URL}"
echo_with_date ""

# We run sanity test for each image concurrently in background
if [ "${TEST_TYPE}" == "stable" ]; then
  echo_with_date "Run sanity tests for the stable package versions."
  # For Windows tests we need to download latest stable version from the repo and use that
  curl -o VERSION -f https://raw.githubusercontent.com/scalyr/scalyr-agent-2/release/VERSION
  LATEST_VERSION=$(cat VERSION)
  curl -o /tmp/workspace/ScalyrAgentInstaller.msi -L -f "https://www.scalyr.com/scalyr-repo/stable/latest/ScalyrAgentInstaller-${LATEST_VERSION}.msi"

  if [ "${TEST_OS}" == "windows" ]; then
    true
    # TODO: Re enable once v2.1.30 is out - until the unicode event log tests will fail
    #python tests/ami/packages_sanity_tests.py --distro=WindowsServer2012 --type=install --to-version=/tmp/workspace/ScalyrAgentInstaller.msi --paramiko-debug-log=outputs/WindowsServer2012-install-paramiko.log &> outputs/WindowsServer2012-install.log &
    #python tests/ami/packages_sanity_tests.py --distro=WindowsServer2016 --type=install --to-version=/tmp/workspace/ScalyrAgentInstaller.msi --paramiko-debug-log=outputs/WindowsServer2016-install-paramiko.log &> outputs/WindowsServer2016-install.log &
    #python tests/ami/packages_sanity_tests.py --distro=WindowsServer2019 --type=install --to-version=/tmp/workspace/ScalyrAgentInstaller.msi --paramiko-debug-log=outputs/WindowsServer2019-install-paramiko.log &> outputs/WindowsServer2019-install.log &
  elif [ "${TEST_OS}" == "linux" ]; then
    # Tests below utilize installer script to test installing latest stable version of the package
    # TODO: Uncomment once new release with post / pre install Python version fix has been released
    #python tests/ami/packages_sanity_tests.py --distro=ubuntu2204 --type=install --to-version=current --installer-script-url="${INSTALLER_SCRIPT_URL}" &> outputs/ubuntu2204-install.log &
    python tests/ami/packages_sanity_tests.py --distro=ubuntu1804 --type=install --to-version=current --installer-script-url="${INSTALLER_SCRIPT_URL}" --paramiko-debug-log=outputs/ubuntu1804-install-paramiko.log &> outputs/ubuntu1804-install.log &
    # NOTE: Here we also install "yum-utils" package so we test a regression where our installer
    # would incorrectly detect yum as a package manager on Ubuntu system with yum-utils installed
    python tests/ami/packages_sanity_tests.py --distro=ubuntu1604 --type=install --to-version=current --additional-packages=yum-utils --installer-script-url="${INSTALLER_SCRIPT_URL}" --paramiko-debug-log=outputs/ubuntu1604-install-paramiko.log &> outputs/ubuntu1604-install.log &
    python tests/ami/packages_sanity_tests.py --distro=ubuntu1404 --type=install --to-version=current --installer-script-url="${INSTALLER_SCRIPT_URL}" --paramiko-debug-log=outputs/ubuntu1404-install-paramiko.log &> outputs/ubuntu1404-install.log &
    python tests/ami/packages_sanity_tests.py --distro=debian1003 --type=install --to-version=current --installer-script-url="${INSTALLER_SCRIPT_URL}" --paramiko-debug-log=outputs/debian1003-install-paramiko.log &> outputs/debian1003-install.log &
    python tests/ami/packages_sanity_tests.py --distro=centos7 --type=install --to-version=current --installer-script-url="${INSTALLER_SCRIPT_URL}" --paramiko-debug-log=outputs/centos7-install-paramiko.log &> outputs/centos7-install.log &
    # disable centos 8, because of it's EOL and the poor connection between vault repos.
    #python tests/ami/packages_sanity_tests.py --distro=centos8 --type=install --to-version=current --installer-script-url="${INSTALLER_SCRIPT_URL}" &> outputs/centos8-install.log &
    python tests/ami/packages_sanity_tests.py --distro=amazonlinux2 --type=install --to-version=current --installer-script-url="${INSTALLER_SCRIPT_URL}" --paramiko-debug-log=outputs/amazonlinux2-install-paramiko.log &> outputs/amazonlinux2-install.log &
  fi
else
  echo_with_date "Run sanity tests for the new packages from the current revision."

  if [ "${TEST_OS}" == "windows" ]; then
    # Tests below install package which is built as part of a Circle CI job
    python tests/ami/packages_sanity_tests.py --distro=WindowsServer2012 --type=install --to-version=/tmp/workspace/ScalyrAgentInstaller.msi --paramiko-debug-log=outputs/WindowsServer2012-install-paramiko.log &> outputs/WindowsServer2012-install.log &
    python tests/ami/packages_sanity_tests.py --distro=WindowsServer2016 --type=install --to-version=/tmp/workspace/ScalyrAgentInstaller.msi --paramiko-debug-log=outputs/WindowsServer2016-install-paramiko.log &> outputs/WindowsServer2016-install.log &
    python tests/ami/packages_sanity_tests.py --distro=WindowsServer2019 --type=install --to-version=/tmp/workspace/ScalyrAgentInstaller.msi --paramiko-debug-log=outputs/WindowsServer2019-install-paramiko.log &> outputs/WindowsServer2019-install.log &
  elif [ "${TEST_OS}" == "linux" ]; then
    python tests/ami/packages_sanity_tests.py --distro=ubuntu2204 --type=install --installer-script-url="${INSTALLER_SCRIPT_URL}" --to-version=/tmp/workspace/scalyr-agent-2.deb --paramiko-debug-log=outputs/ubuntu2204-install-paramiko.log &> outputs/ubuntu2204-install.log &

    # Tests below install latest stable version using an installer script and then upgrade to a
    # version which was built as part of a Circle CI job
    # TODO: Uncomment once new release with post / pre install Python version fix has been released
    #python tests/ami/packages_sanity_tests.py --distro=ubuntu2204 --type=upgrade --from-version=current --installer-script-url="${INSTALLER_SCRIPT_URL}" --to-version=/tmp/workspace/scalyr-agent-2.deb --paramiko-debug-log=outputs/ubuntu2204-upgrade-paramiko.log  &> outputs/ubuntu2204-upgrade.log &
    python tests/ami/packages_sanity_tests.py --distro=ubuntu1804 --type=upgrade --from-version=current --installer-script-url="${INSTALLER_SCRIPT_URL}" --to-version=/tmp/workspace/scalyr-agent-2.deb --paramiko-debug-log=outputs/ubuntu1804-upgrade-paramiko.log &> outputs/ubuntu1804-upgrade.log &
    python tests/ami/packages_sanity_tests.py --distro=ubuntu1604 --type=upgrade --from-version=current --installer-script-url="${INSTALLER_SCRIPT_URL}" --to-version=/tmp/workspace/scalyr-agent-2.deb --paramiko-debug-log=outputs/ubuntu1604-upgrade-paramiko.log &> outputs/ubuntu1604-upgrade.log &
    python tests/ami/packages_sanity_tests.py --distro=ubuntu1404 --type=upgrade --from-version=current --installer-script-url="${INSTALLER_SCRIPT_URL}" --to-version=/tmp/workspace/scalyr-agent-2.deb --paramiko-debug-log=outputs/ubuntu1404-upgrade-paramiko.log &> outputs/ubuntu1404-upgrade.log &
    python tests/ami/packages_sanity_tests.py --distro=debian1003 --type=upgrade --from-version=current --installer-script-url="${INSTALLER_SCRIPT_URL}" --to-version=/tmp/workspace/scalyr-agent-2.deb --paramiko-debug-log=outputs/debian1003-upgrade-paramiko.log &> outputs/debian1003-upgrade.log &
    python tests/ami/packages_sanity_tests.py --distro=centos7 --type=upgrade --from-version=current --to-version=/tmp/workspace/scalyr-agent-2.rpm --installer-script-url="${INSTALLER_SCRIPT_URL}" --paramiko-debug-log=outputs/centos7-upgrade-paramiko.log &> outputs/centos7-upgrade.log &
    # disable centos 8, because of it's EOL and the poor connection between vault repos.
    # python tests/ami/packages_sanity_tests.py --distro=centos8 --type=upgrade --from-version=current --to-version=/tmp/workspace/scalyr-agent-2.rpm --installer-script-url="${INSTALLER_SCRIPT_URL}" &> outputs/centos8-upgrade.log &
    python tests/ami/packages_sanity_tests.py --distro=amazonlinux2 --type=upgrade --from-version=current --to-version=/tmp/workspace/scalyr-agent-2.rpm --installer-script-url="${INSTALLER_SCRIPT_URL}" --paramiko-debug-log=outputs/amazonlinux2-upgrade-paramiko.log &> outputs/amazonlinux2-upgrade.log &
  fi
fi

# Store command line args and log paths for all the jobs for a friendlier output on failure
JOB_DISTRO_NAMES=()
JOB_TEST_TYPES=()
JOBS_COMMAND_LINE_ARGS=()
JOBS_LOG_FILE_PATHS=()

# NOTE: Circle CI uses pyenv exec to spawn python process so we need to wait here a bit so we
# capture right command line args to display for JOB_COMMAND_LINE_ARGS variable.
# This only affects display and nothing else.
sleep 4

for job_pid in $(jobs -p)
do
    JOB_COMMAND_LINE_ARGS=$(ps -ww -f "${job_pid}" | tail -1 | tr -d "\n" | awk '{for(i=9;i<=NF;++i)printf $i""FS}')
    JOBS_COMMAND_LINE_ARGS[${job_pid}]=${JOB_COMMAND_LINE_ARGS}

    DISTRO_NAME=$(echo "${JOB_COMMAND_LINE_ARGS}" | awk -F "distro=" '{print $2}' | awk '{print $1}')
    TEST_TYPE=$(echo "${JOB_COMMAND_LINE_ARGS}" | awk -F "type=" '{print $2}' | awk '{print $1}')

    JOB_DISTRO_NAMES[${job_pid}]="${DISTRO_NAME}"
    JOB_TEST_TYPES[${job_pid}]="${TEST_TYPE}"

    JOBS_LOG_FILE_PATHS[${job_pid}]="outputs/${DISTRO_NAME}-${TEST_TYPE}.log"
    JOBS_PARAMIKO_LOG_FILE_PATHS[${job_pid}]="outputs/${DISTRO_NAME}-${TEST_TYPE}-paramiko.log"
done

echo_with_date ""

FAIL_COUNTER=0

# Wait for all the jobs to finish
for job_pid in $(jobs -p)
do
    JOB_TEST_TYPE=${JOB_TEST_TYPES[${job_pid}]}
    JOB_DISTRO_NAME=${JOB_DISTRO_NAMES[${job_pid}]}
    JOB_COMMAND_LINE_ARGS=${JOBS_COMMAND_LINE_ARGS[${job_pid}]}
    JOB_LOG_FILE_PATH=${JOBS_LOG_FILE_PATHS[${job_pid}]}
    JOB_PARAMIKO_LOG_FILE_PATH=${JOBS_PARAMIKO_LOG_FILE_PATHS[${job_pid}]}

    echo_with_date ""
    echo_with_date "============================================================================================"
    echo_with_date ""

    if wait "${job_pid}"; then
        echo_with_date "Job \"${JOB_TEST_TYPE}\" for OS \"${JOB_DISTRO_NAME}\" finished successfully: \"${JOB_COMMAND_LINE_ARGS}\"."
    else
        ((FAIL_COUNTER=FAIL_COUNTER+1))

        echo_with_date "Job \"${JOB_TEST_TYPE}\" for OS \"${JOB_DISTRO_NAME}\" failed: \"${JOB_COMMAND_LINE_ARGS}\"."
        echo_with_date "Showing output from ${JOB_LOG_FILE_PATH}:"
        echo_with_date "--------------------------------------------------------------------------------------"
        cat "${JOB_LOG_FILE_PATH}" || true
        echo_with_date "--------------------------------------------------------------------------------------"
        echo_with_date "Showing paramiko debug output from ${JOB_PARAMIKO_LOG_FILE_PATH}:"
        cat "${JOB_PARAMIKO_LOG_FILE_PATH}" || true
        echo_with_date "--------------------------------------------------------------------------------------"
    fi

    echo_with_date ""
    echo_with_date "Jobs still running: $(jobs -p | wc -l)"
    echo_with_date ""
    echo_with_date "============================================================================================"
done

# Exit with error if some of the jobs failed.
if [ "${FAIL_COUNTER}" -ne 0 ];
then
    echo_with_date ""
    echo_with_date "${FAIL_COUNTER} of the AMI tests failed. Please check the output logs above."
    echo_with_date "NOTE: Output for all the jobs are also available as job build artifacts."
    echo_with_date ""
    exit 1
else
    echo_with_date ""
    echo_with_date "All the AMI tests have completed successfully."
    echo_with_date ""
    exit 0
fi
