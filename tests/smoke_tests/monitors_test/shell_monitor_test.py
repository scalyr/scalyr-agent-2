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

from __future__ import unicode_literals
from __future__ import print_function
from __future__ import absolute_import

if False:
    from typing import Dict
    from typing import Any

import time

import pytest
import six

from tests.utils.agent_runner import AgentRunner
from tests.utils.log_reader import LogReader
from tests.utils.dockerized import dockerized_case
from tests.image_builder.monitors.shell import ShellMonitorBuilder


class ShellMonitorAgentRunner(AgentRunner):
    def __init__(self):
        super(ShellMonitorAgentRunner, self).__init__(enable_coverage=True)

        self.shell_monitor_log_path = self.add_log_file(
            self.agent_logs_dir_path / "shell_monitor.log"
        )

    @property
    def _agent_config(self):  # type: () -> Dict[six.text_type, Any]
        config = super(ShellMonitorAgentRunner, self)._agent_config
        config["monitors"].append(
            {
                "module": "scalyr_agent.builtin_monitors.shell_monitor",
                "id": "echo",
                "command": 'echo "Hello"',
            }
        )

        return config


def _test(python_version):
    runner = ShellMonitorAgentRunner()

    runner.start(executable=python_version)
    time.sleep(1)
    reader = LogReader(runner.shell_monitor_log_path)
    reader.start(wait_for_data=False)

    last_line = reader.wait_for_new_line()

    assert "Hello" in last_line
    assert "[shell_monitor(echo)]" in last_line

    runner.stop()


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(ShellMonitorBuilder, __file__)
def test_shell_python2(request):
    _test(python_version="python2")


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(ShellMonitorBuilder, __file__)
def test_shell_python3(request):
    _test(python_version="python3")
