# Copyright 2019 Scalyr Inc.
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
# ------------------------------------------------------------------------
#
# author: Imron Alston <imron@scalyr.com>

from __future__ import absolute_import
from __future__ import print_function

__author__ = "imron@scalyr.com"

import mock

from scalyr_agent.test_base import ScalyrTestCase
from scalyr_agent.builtin_monitors.mysql_monitor import MysqlDB


class TestMysqlDB(MysqlDB):
    def _connect(self):
        self._db = mock.Mock()
        self._cursor = mock.Mock()
        self._query = mock.Mock(return_value=None)

    def __xinit__(self):
        # do nothing, because we don't actually want to connect to a DB
        # for this test
        pass


class MySqlMonitorTest(ScalyrTestCase):
    def test_missing_qcache_hits(self):
        logger = mock.Mock()
        db = TestMysqlDB(logger=logger, type="host:port")

        globalVars = {}
        globalStatusMap = {"global.com_select": 10}
        expected = 0
        actual = db._derived_stat_query_cache_efficiency(globalVars, globalStatusMap)
        self.assertEqual(expected, actual)

    def test_replica_metrics_are_not_collected_when_config_option_is_false(self):
        # Default is True for backward compatibility reasons
        logger = mock.Mock()
        db = TestMysqlDB(logger=logger, type="host:port")
        self.assertEqual(db._query.call_count, 0)
        result = db.gather_cluster_status()
        self.assertEqual(db._query.call_count, 1)
        self.assertIsNone(result)

        # Explicit True
        logger = mock.Mock()
        db = TestMysqlDB(logger=logger, type="host:port", collect_replica_metrics=True)
        self.assertEqual(db._query.call_count, 0)
        result = db.gather_cluster_status()
        self.assertEqual(db._query.call_count, 1)
        self.assertIsNone(result)

        # Explicit False
        logger = mock.Mock()
        db = TestMysqlDB(logger=logger, type="host:port", collect_replica_metrics=False)
        self.assertEqual(db._query.call_count, 0)
        result = db.gather_cluster_status()
        logger.debug.assert_called_with(
            '"collect_replica_metrics" configuration option is set to False so replica / slave metrics won\'t be collected.'
        )
        self.assertEqual(db._query.call_count, 0)
        self.assertIsNone(result)
