# Copyright 2014-2021 Scalyr Inc.
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

import os
import sys
import time
import unittest
import platform
import subprocess

from scalyr_agent.test_base import skipIf
from scalyr_agent import compat

BASE_DIR = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.abspath(
    os.path.join(BASE_DIR, "../../../scalyr_agent/third_party/tcollector/collectors/0")
)


class TCollectorSpawnTestCase(unittest.TestCase):
    """
    Test cases which verify that all the tcollector modules can be correctly spawned and don't
    return any errors.
    """

    @skipIf(platform.system() == "Windows", "Skipping Linux Monitor tests on Windows")
    @skipIf(platform.system() == "Darwin", "Skipping Linux Monitor tests on OSX")
    def test_spawn_dfstat_module(self):
        dfstat_path = os.path.join(MODULE_PATH, "dfstat.py")

        dfstat_process = subprocess.Popen(
            [sys.executable, dfstat_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        time.sleep(1)
        dfstat_process.kill()

        stdout, stderr = dfstat_process.communicate()
        self.assertEqual(
            len(stderr), 0, "Expected stderr to be empty, got %s" % (stderr)
        )
        self.assertTrue(
            b"df.inodes.total" in stdout,
            "Did not find expected data in stdout (%s)" % (stdout),
        )
        self.assertTrue(
            b"df.inodes.free" in stdout,
            "Did not find expected data in stdout (%s)" % (stdout),
        )

    @skipIf(platform.system() == "Windows", "Skipping Linux Monitor tests on Windows")
    @skipIf(platform.system() == "Darwin", "Skipping Linux Monitor tests on OSX")
    def test_spawn_ifstat_module(self):
        dfstat_path = os.path.join(MODULE_PATH, "ifstat.py")
        env = compat.os_environ_unicode.copy()
        env["TCOLLECTOR_INTERFACE_PREFIX"] = "eth,en,eno"

        ifstat_process = subprocess.Popen(
            [sys.executable, dfstat_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

        time.sleep(1)
        ifstat_process.kill()

        stdout, stderr = ifstat_process.communicate()
        self.assertEqual(
            len(stderr), 0, "Expected stderr to be empty, got %s" % (stderr)
        )
        self.assertTrue(
            b"proc.net.bytes" in stdout,
            "Did not find expected data in stdout (%s)" % (stdout),
        )
        self.assertTrue(
            b"proc.net.dropped" in stdout,
            "Did not find expected data in stdout (%s)" % (stdout),
        )

    @skipIf(platform.system() == "Windows", "Skipping Linux Monitor tests on Windows")
    @skipIf(platform.system() == "Darwin", "Skipping Linux Monitor tests on OSX")
    def test_spawn_iostat_module(self):
        iostat_path = os.path.join(MODULE_PATH, "iostat.py")

        ifstat_process = subprocess.Popen(
            [sys.executable, iostat_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        time.sleep(1)
        ifstat_process.kill()

        stdout, stderr = ifstat_process.communicate()
        self.assertEqual(
            len(stderr), 0, "Expected stderr to be empty, got %s" % (stderr)
        )
        self.assertTrue(
            b"iostat.disk.read_requests" in stdout,
            "Did not find expected data in stdout (%s)" % (stdout),
        )
        self.assertTrue(
            b"iostat.part.read_merged" in stdout,
            "Did not find expected data in stdout (%s)" % (stdout),
        )

    @skipIf(platform.system() == "Windows", "Skipping Linux Monitor tests on Windows")
    @skipIf(platform.system() == "Darwin", "Skipping Linux Monitor tests on OSX")
    def test_spawn_netstat_module(self):
        netstat_path = os.path.join(MODULE_PATH, "netstat.py")

        netstat_process = subprocess.Popen(
            [sys.executable, netstat_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        time.sleep(1)
        netstat_process.kill()

        stdout, stderr = netstat_process.communicate()
        self.assertEqual(
            len(stderr), 0, "Expected stderr to be empty, got %s" % (stderr)
        )
        self.assertTrue(
            b"net.sockstat.num_sockets" in stdout,
            "Did not find expected data in stdout (%s)" % (stdout),
        )
        self.assertTrue(
            b"net.stat.tcp.invalid_sack" in stdout,
            "Did not find expected data in stdout (%s)" % (stdout),
        )

    @skipIf(platform.system() == "Windows", "Skipping Linux Monitor tests on Windows")
    @skipIf(platform.system() == "Darwin", "Skipping Linux Monitor tests on OSX")
    def test_spawn_procstat_module(self):
        procstat_path = os.path.join(MODULE_PATH, "procstats.py")

        procstat_process = subprocess.Popen(
            [sys.executable, procstat_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        time.sleep(1)
        procstat_process.kill()

        stdout, stderr = procstat_process.communicate()
        self.assertEqual(
            len(stderr), 0, "Expected stderr to be empty, got %s" % (stderr)
        )
        self.assertTrue(
            b"proc.uptime.total" in stdout,
            "Did not find expected data in stdout (%s)" % (stdout),
        )
        self.assertTrue(
            b"proc.meminfo.cached" in stdout,
            "Did not find expected data in stdout (%s)" % (stdout),
        )
