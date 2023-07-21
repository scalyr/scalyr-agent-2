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
import shlex

import pytest

import pg8000

from tests.utils.agent_runner import AgentRunner

from tests.utils.dockerized import dockerized_case
from tests.image_builder.monitors.common import CommonMonitorBuilder
from tests.utils.log_reader import LogMetricReader, AgentLogReader

import six

HOST = "localhost"
USERNAME = "scalyr_test_user"
PASSWORD = "scalyr_test_password"
DATABASE = "scalyr_test_db"


@pytest.fixture()
def postgresql_client():
    os.system("service postgresql start")

    os.system(
        "psql -c \"CREATE USER {} WITH PASSWORD '{}'\";".format(
            shlex.quote(USERNAME), shlex.quote(PASSWORD)
        )
    )
    os.system('psql -c "CREATE DATABASE {};"'.format(shlex.quote(USERNAME)))
    os.system('psql -c "CREATE DATABASE {};"'.format(shlex.quote(DATABASE)))

    time.sleep(3)

    client = pg8000.connect(host=HOST, user=USERNAME, password=PASSWORD, db=DATABASE)

    yield client
    client.close()


@pytest.fixture()
def postgres_cursor(postgresql_client):
    cursor = postgresql_client.cursor()

    yield cursor

    cursor.close()


class PostgresAgentRunner(AgentRunner):
    def __init__(self):
        super(PostgresAgentRunner, self).__init__(
            enable_coverage=True, send_to_server=False
        )

        self.mysql_log_path = self.add_log_file(
            self.agent_logs_dir_path / "postgres_monitor.log"
        )

    @property
    def _agent_config(self):  # type: () -> Dict[six.text_type, Any]
        config = super(PostgresAgentRunner, self)._agent_config
        config["monitors"].append(
            {
                "database_host": HOST,
                "database_name": DATABASE,
                "database_password": PASSWORD,
                "database_port": 5432,
                "database_username": USERNAME,
                "id": "mydb",
                "module": "scalyr_agent.builtin_monitors.postgres_monitor",
            }
        )

        return config


class PostgresLogReader(LogMetricReader):
    LINE_PATTERN = r"\s*(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}.\d+Z)\s\[postgres_monitor\((?P<instance_id>[^\]]+)\)\]\s(?P<metric_name>[^\s]+)\s(?P<metric_value>.+)"


def _test(request, python_version):
    postgres_cursor = request.getfixturevalue("postgres_cursor")

    runner = PostgresAgentRunner()

    runner.start(executable=python_version)

    time.sleep(1)

    agent_log_reader = AgentLogReader(runner.agent_log_file_path)
    agent_log_reader.start()

    # wait for agent logs about postgres monitor is started.
    agent_log_reader.wait_for_matching_line(
        pattern=r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+Z INFO \[core\] \[scalyr_agent.monitors_manager:\d+\] Starting monitor postgres_monitor\(mydb\)"
    )

    # just wait more to be sure that there are no errors in the agent.log.
    agent_log_reader.wait(3)

    postgres_cursor.execute(
        "CREATE TABLE test_table( id SERIAL PRIMARY KEY, text VARCHAR(255));"
    )

    reader = PostgresLogReader(runner.mysql_log_path)
    reader.start()

    metrics_to_check = ["postgres.database.size"]

    reader.wait_for_metrics_exist(metrics_to_check)

    postgres_cursor.execute("SELECT * FROM test_table")

    rows = postgres_cursor.fetchall()

    assert len(rows) == 0

    postgres_cursor.execute(
        "INSERT INTO test_table (text) values ('row1') RETURNING id"
    )
    (row1_id,) = postgres_cursor.fetchone()

    postgres_cursor.execute("SELECT * FROM test_table")
    rows = postgres_cursor.fetchall()

    assert len(rows) == 1

    postgres_cursor.execute(
        "INSERT INTO test_table (text) values ('row2') RETURNING id"
    )
    (row2_id,) = postgres_cursor.fetchone()

    postgres_cursor.execute("SELECT * FROM test_table")
    rows = postgres_cursor.fetchall()

    assert len(rows) == 2

    postgres_cursor.execute("DELETE FROM test_table WHERE id={0};".format(row2_id))

    postgres_cursor.execute("SELECT * FROM test_table;")
    rows = postgres_cursor.fetchall()

    assert len(rows) == 1

    postgres_cursor.execute(
        "UPDATE test_table SET text='updated_row1' WHERE id={0};".format(row1_id)
    )

    postgres_cursor.execute("SELECT text FROM test_table WHERE id={0}".format(row1_id))

    (row1_text,) = postgres_cursor.fetchone()
    assert row1_text == "updated_row1"

    agent_log_reader.go_to_end()


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(CommonMonitorBuilder, __file__)
def test_postgres_python2(request):
    _test(request, python_version="python2")


@pytest.mark.usefixtures("agent_environment")
@dockerized_case(CommonMonitorBuilder, __file__)
def test_postgres_python3(request):
    _test(request, python_version="python3")
