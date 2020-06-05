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

# This script is used in circleci ami package tests.

# run sanity test for each image concurrently in backgroung.
python tests/ami/packages_sanity_tests.py --distro=WindowsServer2012 --type=install --to-version=/tmp/workspace/ScalyrAgentInstaller.msi &> outputs/WindowsServer2012.log & \
python tests/ami/packages_sanity_tests.py --distro=WindowsServer2016 --type=install --to-version=/tmp/workspace/ScalyrAgentInstaller.msi &> outputs/WindowsServer2016.log & \
python tests/ami/packages_sanity_tests.py --distro=WindowsServer2019 --type=install --to-version=/tmp/workspace/ScalyrAgentInstaller.msi &> outputs/WindowsServer2019.log & \
python tests/ami/packages_sanity_tests.py --distro=ubuntu1804 --type=upgrade --from-version=current --to-version=/tmp/workspace/scalyr-agent-2.deb &> outputs/ubuntu1804.log & \
python tests/ami/packages_sanity_tests.py --distro=ubuntu1604 --type=upgrade --from-version=current --to-version=/tmp/workspace/scalyr-agent-2.deb &> outputs/ubuntu1604.log & \
python tests/ami/packages_sanity_tests.py --distro=ubuntu1404 --type=upgrade --from-version=current --to-version=/tmp/workspace/scalyr-agent-2.deb &> outputs/ubuntu1404.log & \
python tests/ami/packages_sanity_tests.py --distro=centos7 --type=upgrade --from-version=current --to-version=/tmp/workspace/scalyr-agent-2.rpm &> outputs/centos7.log &

# Wait for every job.
for job in `jobs -p`
do
    wait $job || let "FAIL+=1"
done

# Exit with error if some of the jobs failed.
if [ "$FAIL" -ne "0" ];
then
    echo "FAIL"
    exit 1
fi