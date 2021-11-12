# Copyright 2021 Scalyr Inc.
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
from __future__ import print_function

import os
import io
import sys
import unittest
from io import open

import mock

BASE_DIR = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))

MODULE_PATH = os.path.abspath(
    os.path.join(BASE_DIR, "../../../scalyr_agent/third_party/tcollector/collectors/0")
)
FIXTURES_DIR = os.path.abspath(os.path.join(BASE_DIR, "../fixtures/netstat"))
sys.path.append(MODULE_PATH)

# pylint: disable=import-error
# type: ignore
from netstat import parse_and_print_metrics


class NetStatTcollectorTestCase(unittest.TestCase):
    @mock.patch("iostat.time.time", mock.Mock(return_value=100))
    def test_verify_proc_netstat_kernel_5_11(self):
        file_path_netstat = os.path.join(
            FIXTURES_DIR, "netstat_ubuntu_20_04_kernel_5.11.0.txt"
        )
        file_path_sockstat = os.path.join(
            FIXTURES_DIR, "sockstat_ubuntu_20_04_kernel_5.11.0.txt"
        )

        output_file_sucess = io.StringIO()
        output_file_error = io.StringIO()

        with open(file_path_netstat, "r") as f_netstat, open(
            file_path_sockstat, "r"
        ) as f_sockstat:
            parse_and_print_metrics(
                f_netstat, f_sockstat, output_file_sucess, output_file_error
            )

        output_success = output_file_sucess.getvalue()
        output_error = output_file_error.getvalue()
        output_success_lines = output_success.strip().split("\n")

        self.assertEqual(output_error, "")
        self.assertEqual(
            output_success_lines[0], "net.sockstat.num_sockets 100 4 type=tcp"
        )
        self.assertEqual(
            output_success_lines[-1], "net.stat.tcp.receive.queue.full 100 0"
        )
        self.assertEqual(len(output_success_lines), 40)
