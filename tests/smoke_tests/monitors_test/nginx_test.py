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

import time

import pytest

from scalyr_agent.third_party import pymysql

from tests.utils.agent_runner import AgentRunner

from tests.utils.dockerized import dockerized_case
from tests.images_builder.monitors.nginx import NginxBuilder
from tests.utils.log_reader import LogMetricReader

import six

HOST = "localhost"
USERNAME = "scalyr_test_user"
PASSWORD = "scalyr_test_password"
DATABASE = "scalyr_test_db"


@pytest.fixture()
def mysql_client():
    client = None
    while True:
        try:
            client = pymysql.connect(
                host=HOST, user=USERNAME, password=PASSWORD, db=DATABASE
            )
            break
        except pymysql.Error:
            time.sleep(0.1)
            continue

    yield client
    client.close()


@pytest.fixture()
def mysql_cursor(mysql_client):
    cursor = mysql_client.cursor()

    yield cursor

    cursor.close()


def _clear(cursor):
    cursor.execute("DROP TABLE IF EXISTS test_table;")
    return


@pytest.fixture()
def clear_db(mysql_cursor):
    _clear(mysql_cursor)


class NginxAgentRunner(AgentRunner):
    def __init__(self, python_version="python2"):
        super(NginxAgentRunner, self).__init__(python_version=python_version)

        # self.nginx_log_path = self.add_log_file(self.agent_logs_dir_path / "mysql_monitor.log")

    @property
    def _agent_config(self):  # type: () -> Dict[six.text_type, Any]
        config = super(MysqlAgentRunner, self)._agent_config
        config["monitors"].append(
            {
                "monitors": [
                    {
                        "module": "scalyr_agent.builtin_monitors.nginx_monitor",
                        "status_url": "http://localhost:80/nginx_status",
                    }
                ]
            }
        )

        return config


def _test(request, python_version):

    a = 10


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(NginxBuilder, __file__, second_exec=True)
def test_nginx_python2(request):
    _test(request, python_version="python2")


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(NginxBuilder, __file__, second_exec=True)
def test_nginx_python3(request):
    _test(request, python_version="python3")
