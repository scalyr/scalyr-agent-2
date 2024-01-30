# Copyright 2022 Scalyr Inc.
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

try:
    from scalyr_agent.builtin_monitors.windows_event_log_monitor import Cache
except:
    Cache = None

from scalyr_agent.test_base import BaseScalyrLogCaptureTestCase, skipIf

import sys
import time


@skipIf(sys.version_info < (3, 0, 0), "Skipping under Python 2")
@skipIf(sys.platform != "Windows", "Skipping on non-Windows platforms")
class CacheTest(BaseScalyrLogCaptureTestCase):
    def test_fixed_size(self):
        cache = Cache(3, 3600)

        cache["a"] = 1
        cache["b"] = 2
        cache["c"] = 3

        self.assertTrue(len(cache) == 3)
        self.assertTrue("a" in cache)

        cache["d"] = 4

        self.assertTrue(len(cache) == 3)
        self.assertTrue("a" not in cache)

    def test_ttl_via_contains(self):
        cache = Cache(1000, 0.001)

        cache["a"] = 1
        self.assertTrue("a" in cache)

        time.sleep(0.001)
        self.assertTrue("a" not in cache)

    def test_ttl_via_iter(self):
        cache = Cache(1000, 0.001)

        cache["a"] = 1
        self.assertTrue("a" in cache)

        time.sleep(0.001)
        self.assertTrue(len([k for k in cache]) == 0)

    def test_ttl_via_values(self):
        cache = Cache(1000, 0.001)

        cache["a"] = 1
        self.assertTrue("a" in cache)

        time.sleep(0.001)
        self.assertTrue(len([v for v in cache.values()]) == 0)

    def test_ttl_via_len(self):
        cache = Cache(1000, 0.001)

        cache["a"] = 1
        self.assertTrue("a" in cache)

        time.sleep(0.001)
        self.assertTrue(len(cache) == 0)
