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

from __future__ import absolute_import

import sys
import unittest
import platform

import mock

if platform.system() != "Windows":
    from scalyr_agent.third_party.tcollector import tcollector  # pylint: disable=import-error
else:
    tcollector = None  # type: ignore

from scalyr_agent.test_base import skipIf


class TcollectorCollectorsTestCase(unittest.TestCase):
    @skipIf(platform.system() == "Windows", "Skipping Linux platform tests on Windows")
    @mock.patch("scalyr_agent.third_party.tcollector.tcollector.set_nonblocking", mock.Mock())
    @mock.patch("scalyr_agent.third_party.tcollector.tcollector.subprocess.Popen")
    def test_correct_python_binary_is_used_for_subprocess(self, mock_popen):
        col = mock.Mock()
        col.name = "foo"
        col.filename = "filename"
        col.interval = 5

        mock_proc = mock.Mock()
        mock_proc.pid = 100
        mock_popen.return_value = mock_proc

        self.assertEqual(mock_popen.call_count, 0)

        tcollector.spawn_collector(col=col)

        call_args = mock_popen.call_args_list[0][0]
        self.assertEqual(mock_popen.call_count, 1)
        self.assertEqual(call_args[0], [sys.executable, "filename"])
