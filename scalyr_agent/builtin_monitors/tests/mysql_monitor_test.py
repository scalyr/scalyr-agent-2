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

__author__ = 'imron@scalyr.com'

import sys
from mock import patch

from scalyr_agent import UnsupportedSystem
from scalyr_agent.test_base import ScalyrTestCase

class MySqlMonitorTest(ScalyrTestCase):

    def _import_mysql_monitor(self):
        import scalyr_agent.builtin_monitors.mysql_monitor
        self.assertTrue( True )

    def test_min_python_version(self):
        if sys.version_info[:2] < (2, 7):
            self.assertRaises( UnsupportedSystem, lambda: self._import_mysql_monitor() )
        else:
            self._import_mysql_monitor()

    def test_missing_qcache_hits(self):
        if sys.version_info[:2] < (2, 7):
            print("Skipping test 'test_missing_qcache_hits'.\n"
                  "This test is non-critical for pre-2.7 testing.\n" )
            return

        from scalyr_agent.builtin_monitors.mysql_monitor import MysqlDB

        class TestMysqlDB(MysqlDB):
            def __init__( self ):
                # do nothing, because we don't actually want to connect to a DB
                # for this test
                pass

        db = TestMysqlDB()

        globalVars = {}
        globalStatusMap = {
            'global.com_select': 10
        }
        expected = 0 
        actual = db._derived_stat_query_cache_efficiency(globalVars, globalStatusMap)
        self.assertEqual( expected, actual )

