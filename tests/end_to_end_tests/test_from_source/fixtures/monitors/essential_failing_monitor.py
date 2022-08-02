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

import time

from scalyr_agent.scalyr_monitor import ScalyrMonitor


class FailingMonitor(ScalyrMonitor):
    """
    A dummy monitor that fails some time after launch.
    It is a part of the test that verifies that monitor, which has option 'stop_agent_on_failure',
    will fail the whole agent if the monitor fails itself.
    """

    def _initialize(self):
        self._fail_time = time.time() + 30
        self.to_fail_increment_counter = False
        self.set_sample_interval(3)

    def gather_sample(self):
        if time.time() >= self._fail_time:
            self.to_fail_increment_counter = True
            raise Exception(f"Monitor '{self.monitor_id}' bad error.")

        self._logger.info(f"Monitor '{self.monitor_id}' is not dead, yet...")
        self._logger.emit_value("dummy", "dummy")

    def increment_counter(self, reported_lines=0, errors=0):
        # This exception has to lead to stop of the whole monitor.
        if self.to_fail_increment_counter:
            # Since the 'increment_counter' is the only place where we can conveniently fail the whole monitor
            # We have to be sure that the error which has to be raised here is only occur in monitors thread.
            # It's important, since the 'increment_counter' is also used by the AgentLogger, and we don't want
            # that this synthetic error happens in logger.
            self.to_fail_increment_counter = False
            self._logger.error(f"Monitor '{self.monitor_id}' Dead.")
            raise Exception(f"Monitor '{self.monitor_id}' critical error.")
