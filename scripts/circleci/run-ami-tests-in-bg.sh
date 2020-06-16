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
#
#


echo "Runing AMI sanity tests concurrently in the background (this may take up to 5 minutes)..."

# Create directory which output log files will be saved
mkdir -p outputs

TEST_TYPE="$1"

if [ "$TEST_TYPE" != "stable" ] && [ "$TEST_TYPE" != "development" ]; then
    echo "Test type: 'stable' or 'development' must be specified."
    exit 1
fi

if [ "$TEST_TYPE" != "stable" ]; then
  # Run sanity test for each image concurrently in background
  # Tests below utilize installer script to test installing latest stable version of the package
  python tests/ami/packages_sanity_tests.py --distro=ubuntu1804 --type=install --to-version=current --installer-script-url="https://www.scalyr.com/scalyr-repo/stable/latest/install-scalyr-agent-2.sh" &> outputs/ubuntu1804-install.log &
  python tests/ami/packages_sanity_tests.py --distro=ubuntu1604 --type=install --to-version=current --installer-script-url="https://www.scalyr.com/scalyr-repo/stable/latest/install-scalyr-agent-2.sh" &> outputs/ubuntu1604-install.log &
  python tests/ami/packages_sanity_tests.py --distro=ubuntu1404 --type=install --to-version=current --installer-script-url="https://www.scalyr.com/scalyr-repo/stable/latest/install-scalyr-agent-2.sh" &> outputs/ubuntu1404-install.log &
else
  # Tests below install package which is built as part of a Circle CI job
  python tests/ami/packages_sanity_tests.py --distro=WindowsServer2012 --type=install --to-version=/tmp/workspace/ScalyrAgentInstaller.msi &> outputs/WindowsServer2012-install.log &
  python tests/ami/packages_sanity_tests.py --distro=WindowsServer2016 --type=install --to-version=/tmp/workspace/ScalyrAgentInstaller.msi &> outputs/WindowsServer2016-install.log &
  python tests/ami/packages_sanity_tests.py --distro=WindowsServer2019 --type=install --to-version=/tmp/workspace/ScalyrAgentInstaller.msi &> outputs/WindowsServer2019-install.log &

  # Tests below install latest stable version using an installer script and then upgrade to a
  # version which was built as part of a Circle CI job
  python tests/ami/packages_sanity_tests.py --distro=ubuntu1804 --type=upgrade --from-version=current --to-version=/tmp/workspace/scalyr-agent-2.deb &> outputs/ubuntu1804-upgrade.log &
  python tests/ami/packages_sanity_tests.py --distro=ubuntu1604 --type=upgrade --from-version=current --to-version=/tmp/workspace/scalyr-agent-2.deb &> outputs/ubuntu1604-upgrade.log &
  python tests/ami/packages_sanity_tests.py --distro=ubuntu1404 --type=upgrade --from-version=current --to-version=/tmp/workspace/scalyr-agent-2.deb &> outputs/ubuntu1404-upgrade.log &
  python tests/ami/packages_sanity_tests.py --distro=centos7 --type=upgrade --from-version=current --to-version=/tmp/workspace/scalyr-agent-2.rpm &> outputs/centos7-upgrade.log &
fi

# Store command line args and log paths for all the jobs for a friendlier output on failure
JOBS_COMMAND_LINE_ARGS=()
JOBS_LOG_FILE_PATHS=()

for job_pid in $(jobs -p)
do
    JOB_COMMAND_LINE_ARGS=$(ps -ww -f "${job_pid}" | tail -1 | tr -d "\n" | awk '{for(i=9;i<=NF;++i)printf $i""FS}')
    JOBS_COMMAND_LINE_ARGS[${job_pid}]=${JOB_COMMAND_LINE_ARGS}

    DISTRO_NAME=$(echo "${JOB_COMMAND_LINE_ARGS}" | awk -F "distro=" '{print $2}' | awk '{print $1}')
    TEST_TYPE=$(echo "${JOB_COMMAND_LINE_ARGS}" | awk -F "type=" '{print $2}' | awk '{print $1}')

    JOBS_LOG_FILE_PATHS[${job_pid}]="outputs/${DISTRO_NAME}-${TEST_TYPE}.log"
done

echo ""

FAIL_COUNTER=0

# Wait for all the jobs to finish
for job_pid in $(jobs -p)
do
    JOB_COMMAND_LINE_ARGS=${JOBS_COMMAND_LINE_ARGS[${job_pid}]}
    JOB_LOG_FILE_PATH=${JOBS_LOG_FILE_PATHS[${job_pid}]}

    echo ""
    echo "============================================================================================"
    echo ""

    if wait "${job_pid}"; then
        echo "Job finished successfuly: \"${JOB_COMMAND_LINE_ARGS}\"."
    else
        ((FAIL_COUNTER=FAIL_COUNTER+1))

        echo "Job failed: \"${JOB_COMMAND_LINE_ARGS}\"."
        echo "Showing output from ${JOB_LOG_FILE_PATH}:"
        echo "--------------------------------------------------------------------------------------"
        cat "${JOB_LOG_FILE_PATH}" || true
        echo "--------------------------------------------------------------------------------------"
    fi

    echo ""
    echo "============================================================================================"
done

# Exit with error if some of the jobs failed.
if [ "${FAIL_COUNTER}" -ne 0 ];
then
    echo ""
    echo "${FAIL_COUNTER} of the the AMI tests failed. Please check the output logs above."
    echo "NOTE: Output for all the jobs are also available as job build artifacts."
    echo ""
    exit 1
else
    echo ""
    echo "All the AMI tests have completed successfuly."
    echo ""
    exit 0
fi
