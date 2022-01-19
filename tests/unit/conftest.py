# Copyright 2014-2022 Scalyr Inc.
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

# We ignore Python 3 only tests and modules under Python 2
collect_ignore = ["setup.py"]
if sys.version_info < (3, 6, 0):
    collect_ignore.append("tests/unit/builtin_monitors/openmetrics_monitor_test.py")
    collect_ignore.append("builtin_monitors/openmetrics_monitor_test.py")
    collect_ignore.append(
        "tests/unit/builtin_monitors/kubernetes_openmetrics_monitor_test.py"
    )
    collect_ignore.append("builtin_monitors/kubernetes_openmetrics_monitor_test.py")
