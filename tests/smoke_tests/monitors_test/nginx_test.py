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

if False:  # NOSONAR
    from typing import Dict
    from typing import Any

import time
import os

import pytest

from tests.utils.agent_runner import AgentRunner

from tests.utils.dockerized import dockerized_case
from tests.image_builder.monitors.common import CommonMonitorBuilder
from tests.utils.log_reader import LogMetricReader

import six


class NginxAgentRunner(AgentRunner):
    def __init__(self):
        super(NginxAgentRunner, self).__init__(
            enable_coverage=True, send_to_server=False
        )

        self.nginx_log_path = self.add_log_file(
            self.agent_logs_dir_path / "nginx_monitor.log"
        )

    @property
    def _agent_config(self):  # type: () -> Dict[six.text_type, Any]
        config = super(NginxAgentRunner, self)._agent_config
        config["monitors"].append(
            {
                "module": "scalyr_agent.builtin_monitors.nginx_monitor",
                "status_url": "http://localhost:80/nginx_status",
            }
        )

        return config


class NginxLogReader(LogMetricReader):
    LINE_PATTERN = r"\s*(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}.\d+Z)\s\[nginx_monitor\((?P<instance_id>[^\]]*)\)\]\s(?P<metric_name>[^\s]+)\s(?P<metric_value>.+)"


def _test(request, python_version):
    os.system("service nginx start")

    runner = NginxAgentRunner()

    runner.start(executable=python_version)
    time.sleep(1)

    reader = NginxLogReader(runner.nginx_log_path)

    reader.start()

    metric_names = [
        "nginx.connections.active",
        "nginx.connections.reading",
        "nginx.connections.writing",
        "nginx.connections.waiting",
    ]
    metrics = reader.get_metrics(metric_names)

    assert list(sorted(metrics.keys())) == sorted(metric_names)

    runner.stop()


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(CommonMonitorBuilder, __file__)
def test_nginx_python2(request):
    _test(request, python_version="python2")


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(CommonMonitorBuilder, __file__)
def test_nginx_python3(request):
    _test(request, python_version="python3")
