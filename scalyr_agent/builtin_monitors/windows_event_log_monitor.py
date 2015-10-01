# Copyright 2105 Scalyr Inc.
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
# author:  Imron Alston <imron@imralsoftware.com>

__author__ = 'imron@imralsoftware.com'

__monitor__ = __name__

define_config_option(__monitor__, 'module',
                     'Always ``scalyr_agent.builtin_monitors.windows_event_log_monitor``',
                     convert_to=str, required_option=True)
define_config_option( __monitor__, 'sources',
                     'Optional (defaults to ``Application, Security, System``). A comma separated list of event sources.\n'
                     'You can use this to specify which event sources you are interested in listening to.',
                     convert_to=str, default='Application, Security, System')

define_config_option(__monitor__, 'type',
                     'Optional (defaults to ``All``). A comma separated list of event types to log.\n'
                     'Valid values are: All, Error, Warning, Information, AuditSuccess and AuditFailure',
                     default='All', convert_to=str)

class WindowEventLogMonitor( ScalyrMonitor ):
    """
# Window Event Log Monitor

The Windows Event Log monitor upload messages from the windows event log to the Scalyr servers.
It can listen to multiple different event sources, and also filter by messages of a certain type.

@class=bg-warning docInfoPanel: An *agent monitor plugin* is a component of the Scalyr Agent. To use a plugin,
simply add it to the ``monitors`` section of the Scalyr Agent configuration file (``/etc/scalyr/agent.json``).
For more information, see [Agent Plugins](/help/scalyr-agent#plugins).


## Sample Configuration

This sample will configure the agent to accept syslog messages on TCP port 601 and UDP port 514, from localhost
only:

    monitors: [
      {
        module:                  "scalyr_agent.builtin_monitors.windows_event_log_monitor",
        sources:                 "Application, Security, System",
        type:                    "Error, Warning",
      }
    ]


    """
    def _initialize( self ):
        pass


    def gather_sample( self ):



