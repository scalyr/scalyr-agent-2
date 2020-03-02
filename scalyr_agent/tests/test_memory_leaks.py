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

"""
Module which adds tests for previous known memory leaks and makes sure they
are not present anymore.
"""

from __future__ import unicode_literals
from __future__ import absolute_import

if False:
    from typing import Any
    from typing import Set

import os
import gc
import unittest

import pytest

from scalyr_agent.configuration import Configuration
from scalyr_agent.platform_controller import DefaultPaths
from scalyr_agent.util import StoppableThread
from scalyr_agent.json_lib import JsonObject
from six.moves import range

BASE_DIR = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))

__all__ = ["MemoryLeaksTestCase"]


# By default all the tests run inside a single process so we mark this test and run it separately
# since we don't want other tests to affect behavior of this test.
@pytest.mark.memory_leak
class MemoryLeaksTestCase(unittest.TestCase):
    def setUp(self):
        super(MemoryLeaksTestCase, self).setUp()
        gc.set_debug(gc.DEBUG_SAVEALL)

        os.environ["TEST_VAR"] = "foobar"

        # There are always some uncollectable objects which are part of the runners which we
        # are not interested in.
        gc.collect()
        self.base_gargage = self._garbage_to_set(gc.garbage)

    def test_config_parse_memory_leak(self):
        # There was a memory leak with config.parse() and underlying __perform_substitutions method
        config_path = os.path.join(BASE_DIR, "fixtures/configs/agent2.json")
        default_paths = DefaultPaths(
            "/var/log/scalyr-agent-2",
            "/etc/scalyr-agent-2/agent.json",
            "/var/lib/scalyr-agent-2",
        )

        # New config object is created
        for index in range(0, 50):
            config = Configuration(
                file_path=config_path, default_paths=default_paths, logger=None
            )
            config.parse()
            self.assertNoNewGarbage()

        # Existing config object is reused
        config = Configuration(
            file_path=config_path, default_paths=default_paths, logger=None
        )
        for index in range(0, 50):
            config.parse()
            self.assertNoNewGarbage()

    def test_stopptable_thread_init_memory_leak(self):
        # There was a bug with StoppableThread constructor having a cycle
        for index in range(0, 50):
            thread = StoppableThread(name="test1")
            self.assertTrue(thread)
            self.assertNoNewGarbage()

    def test_json_object_to_dict_memory_leak(self):
        content = {"foo": "bar", "a": 2, "b": [1, 2, 3]}

        # New object
        for index in range(0, 50):
            json_object = JsonObject(content=content)
            dict_value = json_object.to_dict()
            self.assertEqual(content, dict_value)

            self.assertNoNewGarbage()

        # Existing object
        json_object = JsonObject(content=content)

        for index in range(0, 50):
            dict_value = json_object.to_dict()
            self.assertEqual(content, dict_value)
            self.assertNoNewGarbage()

    def test_assertion_methods_work_correctly(self):
        class Object1(object):
            pass

        # 1. Collectable object
        obj1 = Object1()
        del obj1

        gc.collect()
        garbage = self._garbage_to_set(gc.garbage)
        new_garbage = garbage.difference(self.base_gargage)
        self.assertNoNewGarbage()

        # 2. Cyclic reference
        obj1 = Object1()
        obj1.self = obj1
        del obj1

        gc.collect()
        garbage = self._garbage_to_set(gc.garbage)
        new_garbage = garbage.difference(self.base_gargage)
        self.assertEqual(len(new_garbage), 2)
        self.assertRaises(AssertionError, self.assertNoNewGarbage)

    def assertNoNewGarbage(self):
        """
        Perform garbage collection and assert no new uncollectable or unreferenced garbage has been
        generated.
        """
        gc.collect()

        garbage = self._garbage_to_set(gc.garbage)
        new_garbage = garbage.difference(self.base_gargage)
        self.assertEqual(len(new_garbage), 0, "Expected no new garbage")

    def _garbage_to_set(self, garbage):
        # type: (Any) -> Set[str]
        """
        Return set with serializable gargage data.

        By default garbage object contains various types (e.g. cell) which are not serializable so
        we use simple string representation which is sufficient for our use case.
        """
        return set([str(obj) for obj in garbage])
