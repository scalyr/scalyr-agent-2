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
This module contains some tests which rely on reload() functionality so they need to run isolated
from other tests in a separate process to avoid cross test pollution and related failures.

Those tests are marked with pytest.mark.forked which ensures they run in a separate subprocess.
"""

from __future__ import unicode_literals
from __future__ import absolute_import


import sys
import importlib

import six
import mock
import pytest

from scalyr_agent.test_base import ScalyrTestCase
from scalyr_agent.test_base import skipIf

if six.PY3:
    reload = importlib.reload


class TestDefaultJsonLibrary(ScalyrTestCase):
    def tearDown(self):
        super(TestDefaultJsonLibrary, self).tearDown()

        for value in ["scalyr_agent.util", "orjson", "ujson", "json"]:
            if value in sys.modules:
                del sys.modules[value]

    @skipIf(six.PY2, "Skipping under Python 2")
    @pytest.mark.forked
    @pytest.mark.relies_on_reload
    @pytest.mark.needs_to_run_isolated
    def test_correct_default_json_library_is_used_python3(self):
        sys.modules["orjson"] = mock.Mock()

        import scalyr_agent.util

        reload(scalyr_agent.util)

        self.assertEqual(scalyr_agent.util.get_json_lib(), "orjson")

        sys.modules["orjson"] = None
        sys.modules["ujson"] = mock.Mock()

        import scalyr_agent.util

        reload(scalyr_agent.util)

        self.assertEqual(scalyr_agent.util.get_json_lib(), "ujson")

        sys.modules["orjson"] = None
        sys.modules["ujson"] = None
        sys.modules["json"] = mock.Mock()

        import scalyr_agent.util

        reload(scalyr_agent.util)

        self.assertEqual(scalyr_agent.util.get_json_lib(), "json")

    @skipIf(six.PY3, "Skipping under Python 3")
    @pytest.mark.forked
    @pytest.mark.relies_on_reload
    @pytest.mark.needs_to_run_isolated
    def test_correct_default_json_library_is_used_python2(self):
        # NOTE: orjson is not available on Python 2 so we should not try and use it
        sys.modules["orjson"] = mock.Mock()
        sys.modules["ujson"] = mock.Mock()

        import scalyr_agent.util

        reload(scalyr_agent.util)

        self.assertEqual(scalyr_agent.util.get_json_lib(), "ujson")

        sys.modules["orjson"] = None
        sys.modules["ujson"] = mock.Mock()

        import scalyr_agent.util

        reload(scalyr_agent.util)

        self.assertEqual(scalyr_agent.util.get_json_lib(), "ujson")

        sys.modules["orjson"] = None
        sys.modules["ujson"] = None
        sys.modules["json"] = mock.Mock()

        import scalyr_agent.util

        reload(scalyr_agent.util)

        self.assertEqual(scalyr_agent.util.get_json_lib(), "json")
