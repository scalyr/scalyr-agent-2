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
set -e

# Give it some time to finish provisioning process. It's possible that we can SSH in before
# cloud-init fully finished
sleep 10

sudo apt-get update -y
sudo apt-get install -y {python_package}

wget -q https://www.scalyr.com/scalyr-repo/stable/latest/install-scalyr-agent-2.sh
sudo bash ./install-scalyr-agent-2.sh --set-api-key "{scalyr_api_key}"

# Install old version
sudo apt-get install -y --allow-downgrades "scalyr-agent-2={package_from_version}"
sudo /etc/init.d/scalyr-agent-2 restart

sleep 5

# Run some basic sanity checks
sudo scalyr-agent-2 status -v
echo ""

sudo scalyr-agent-2 status -v | grep "{package_from_version}"
sudo scalyr-agent-2 status -v | grep agent.log
sudo scalyr-agent-2 status -v | grep linux_system_metrics
sudo scalyr-agent-2 status -v | grep linux_process_metrics

# Verify rc*.d symlinks are in place
ls -la /etc/rc*.d/ | grep scalyr-agent
echo ""

ls -la /etc/rc*.d/ | grep scalyr-agent | wc -l | grep 7

# Upgrade to new version
sudo apt-get install -y "scalyr-agent-2={package_to_version}"
sudo /etc/init.d/scalyr-agent-2 restart

sleep 5

# Verify status works and symlinks are in place
sudo scalyr-agent-2 status -v
echo ""

sudo scalyr-agent-2 status -v | grep "{package_to_version}"
sudo scalyr-agent-2 status -v | grep agent.log
sudo scalyr-agent-2 status -v | grep linux_system_metrics
sudo scalyr-agent-2 status -v | grep linux_process_metrics

# Verify rc*.d symlinks are in place
ls -la /etc/rc*.d/ | grep scalyr-agent
echo ""
ls -la /etc/rc*.d/ | grep scalyr-agent | wc -l | grep 7
