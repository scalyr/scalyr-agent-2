# Copyright 2023 Scalyr Inc.
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
# An example ScalyrMonitor plugin to demonstrate how they can be written.
#
# Note, this can be run in standalone mode by:
#     python -m scalyr_agent.run_monitor -c "{ gauss_mean: 0.5 }" scalyr_agent.builtin_monitors.test_monitor
#
# author:  Ales Novak <ales.novak@sentinelone.com>


from scalyr_agent import ScalyrMonitor, define_config_option

__monitor__ = __name__

import six

define_config_option(
    __monitor__,
    "module",
    "Always `tests.unit.test_monitor`",
    convert_to=six.text_type,
    required_option=True,
)

define_config_option(
    __monitor__,
    "secure_url",
    "Considered secure",
    convert_to=six.text_type,
    required_option=True,
)

define_config_option(
    __monitor__,
    "insecure_url",
    "Considered insecure",
    convert_to=six.text_type,
    required_option=True,
    allow_http=False
)

class TestMonitor(ScalyrMonitor):
    pass