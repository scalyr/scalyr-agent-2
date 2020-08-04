# Copyright 2020 Scalyr Inc.
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
# ==============================================================================
#
# A list of monitor modules to include for the Windows binary.  We need to manually specify this because monitors
# are loaded dynamically and PyInstaller cannot infer them through its static
# analysis.  Any monitor that should be included in the Windows binary must be listed here.  We use a pylint
# checker to enforce this.


WINDOWS_MONITOR_MODULES_TO_INCLUDE = [
    "scalyr_agent.builtin_monitors.windows_system_metrics",
    "scalyr_agent.builtin_monitors.windows_process_metrics",
    "scalyr_agent.builtin_monitors.apache_monitor",
    "scalyr_agent.builtin_monitors.graphite_monitor",
    "scalyr_agent.builtin_monitors.mysql_monitor",
    "scalyr_agent.builtin_monitors.nginx_monitor",
    "scalyr_agent.builtin_monitors.shell_monitor",
    "scalyr_agent.builtin_monitors.syslog_monitor",
    "scalyr_agent.builtin_monitors.test_monitor",
    "scalyr_agent.builtin_monitors.url_monitor",
    "scalyr_agent.builtin_monitors.windows_event_log_monitor",
]
