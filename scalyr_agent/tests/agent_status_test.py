# Copyright 2014 Scalyr Inc.
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
# author: Steven Czerwinski <czerwin@scalyr.com>

__author__ = 'czerwin@scalyr.com'

import cStringIO
import os

from scalyr_agent.agent_status import OverallStats, AgentStatus, ConfigStatus, LogProcessorStatus, MonitorStatus
from scalyr_agent.agent_status import CopyingManagerStatus, MonitorManagerStatus, LogMatcherStatus, report_status

from scalyr_agent.test_base import ScalyrTestCase

class TestOverallStats(ScalyrTestCase):

    def test_read_file_as_json(self):
        a = OverallStats()
        b = OverallStats()

        a.total_bytes_copied = 1
        a.total_bytes_skipped = 2
        a.total_bytes_subsampled = 3
        a.total_bytes_failed = 4
        a.total_redactions = 5
        a.total_copy_requests_errors = 6
        a.total_monitor_reported_lines = 7
        a.total_monitor_errors = 8

        a.total_requests_sent = 1
        a.total_requests_failed = 2
        a.total_request_bytes_sent = 3
        a.total_compressed_request_bytes_sent = 1
        a.total_response_bytes_received = 4
        a.total_request_latency_secs = 5
        a.total_connections_created = 6

        b.total_bytes_copied = 9
        b.total_bytes_skipped = 10
        b.total_bytes_subsampled = 11
        b.total_bytes_failed = 12
        b.total_redactions = 13
        b.total_copy_requests_errors = 14
        b.total_monitor_reported_lines = 15
        b.total_monitor_errors = 16

        b.total_requests_sent = 7
        b.total_requests_failed = 8
        b.total_request_bytes_sent = 9
        b.total_compressed_request_bytes_sent = 4
        b.total_response_bytes_received = 10
        b.total_request_latency_secs = 11
        b.total_connections_created = 12

        c = a + b

        self.assertEquals(c.total_bytes_copied, 10)
        self.assertEquals(c.total_bytes_skipped, 12)
        self.assertEquals(c.total_bytes_subsampled, 14)
        self.assertEquals(c.total_bytes_failed, 16)
        self.assertEquals(c.total_redactions, 18)
        self.assertEquals(c.total_copy_requests_errors, 20)
        self.assertEquals(c.total_monitor_reported_lines, 22)
        self.assertEquals(c.total_monitor_errors, 24)

        self.assertEquals(c.total_requests_sent, 8)
        self.assertEquals(c.total_requests_failed, 10)
        self.assertEquals(c.total_request_bytes_sent, 12)
        self.assertEquals(c.total_compressed_request_bytes_sent, 5)
        self.assertEquals(c.total_response_bytes_received, 14)
        self.assertEquals(c.total_request_latency_secs, 16)
        self.assertEquals(c.total_connections_created, 18)


class TestReportStatus(ScalyrTestCase):
    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved_env)

    def setUp(self):
        self.saved_env = dict(os.environ)
        os.environ.clear()
        self.time = 1409958853
        self.status = AgentStatus()
        self.status.launch_time = self.time - 86400
        self.status.log_path = '/var/logs/scalyr-agent/agent.log'
        self.status.scalyr_server = 'https://agent.scalyr.com'
        self.status.server_host = 'test_machine'
        self.status.user = 'root'
        self.status.version = '2.0.0.beta.7'

        config_status = ConfigStatus()
        self.status.config_status = config_status
        config_status.last_read_time = self.time - 43200
        config_status.last_check_time = self.time
        config_status.last_good_read = self.time - 43000
        config_status.path = '/etc/scalyr-agent-2/agent.json'
        config_status.status = 'Good'
        config_status.additional_paths = ['/etc/scalyr-agent-2/agent.d/server.json']

        copying_status = CopyingManagerStatus()
        self.status.copying_manager_status = copying_status
        copying_status.last_attempt_size = 10000
        copying_status.last_attempt_time = self.time - 60
        copying_status.last_response_status = 'success'
        copying_status.total_errors = 0
        copying_status.total_bytes_uploaded = 10000
        copying_status.last_success_time = self.time - 60

        # Add in one log path that isn't a glob but does not have any matches yet.
        log_matcher = LogMatcherStatus()
        copying_status.log_matchers.append(log_matcher)
        log_matcher.is_glob = False
        log_matcher.last_check_time = self.time - 10
        log_matcher.log_path = '/var/logs/tomcat6/access.log'

        # Add in another matcher that isn't a glob but does have a match.
        log_matcher = LogMatcherStatus()
        copying_status.log_matchers.append(log_matcher)
        log_matcher.is_glob = False
        log_matcher.last_check_time = self.time - 10
        log_matcher.log_path = '/var/logs/tomcat6/catalina.log'
        process_status = LogProcessorStatus()
        log_matcher.log_processors_status.append(process_status)
        process_status.log_path = '/var/logs/tomcat6/catalina.log'
        process_status.last_scan_time = self.time - 120
        process_status.total_bytes_copied = 2341234
        process_status.total_bytes_pending = 1243
        process_status.total_bytes_skipped = 12
        process_status.total_bytes_failed = 1432
        process_status.total_bytes_dropped_by_sampling = 0
        process_status.total_lines_copied = 214324
        process_status.total_lines_dropped_by_sampling = 0
        process_status.total_redactions = 0

        # Add in another matcher that is a glob and has two matches.
        log_matcher = LogMatcherStatus()
        copying_status.log_matchers.append(log_matcher)
        log_matcher.is_glob = True
        log_matcher.last_check_time = self.time - 10
        log_matcher.log_path = '/var/logs/cron/*.log'
        process_status = LogProcessorStatus()
        log_matcher.log_processors_status.append(process_status)
        process_status.log_path = '/var/logs/cron/logrotate.log'
        process_status.last_scan_time = self.time - 120
        process_status.total_bytes_copied = 2341234
        process_status.total_bytes_pending = 1243
        process_status.total_bytes_skipped = 12
        process_status.total_bytes_failed = 1432
        process_status.total_bytes_dropped_by_sampling = 0
        process_status.total_lines_copied = 214324
        process_status.total_lines_dropped_by_sampling = 0
        process_status.total_redactions = 0
        process_status = LogProcessorStatus()
        log_matcher.log_processors_status.append(process_status)
        process_status.log_path = '/var/logs/cron/ohno.log'
        process_status.last_scan_time = self.time - 120
        process_status.total_bytes_copied = 23434
        process_status.total_bytes_pending = 12943
        process_status.total_bytes_skipped = 12
        process_status.total_bytes_failed = 1432
        process_status.total_bytes_dropped_by_sampling = 5
        process_status.total_lines_copied = 214324
        process_status.total_lines_dropped_by_sampling = 10
        process_status.total_redactions = 10

        # One more glob that doesn't have any matches.
        log_matcher = LogMatcherStatus()
        copying_status.log_matchers.append(log_matcher)
        log_matcher.is_glob = True
        log_matcher.last_check_time = self.time - 10
        log_matcher.log_path = '/var/logs/silly/*.log'

        # Now for the monitors.
        monitor_manager = MonitorManagerStatus()
        self.status.monitor_manager_status = monitor_manager
        monitor_manager.total_alive_monitors = 2

        monitor_status = MonitorStatus()
        monitor_manager.monitors_status.append(monitor_status)
        monitor_status.is_alive = True
        monitor_status.monitor_name = 'linux_process_metrics(agent)'
        monitor_status.reported_lines = 50
        monitor_status.errors = 2

        monitor_status = MonitorStatus()
        monitor_manager.monitors_status.append(monitor_status)
        monitor_status.is_alive = True
        monitor_status.monitor_name = 'linux_system_metrics()'
        monitor_status.reported_lines = 20
        monitor_status.errors = 0

        monitor_status = MonitorStatus()
        monitor_manager.monitors_status.append(monitor_status)
        monitor_status.is_alive = False
        monitor_status.monitor_name = 'bad_monitor()'
        monitor_status.reported_lines = 20
        monitor_status.errors = 40

    def test_basic(self):
        output = cStringIO.StringIO()

        # Environment variables
        os.environ['SCALYR_API_KEY'] = 'This private key should be redacted'
        # intentionally leave out required scalyr_server
        os.environ['scalyr_K8S_CLUSTER_NAME'] = 'test_cluster'
        os.environ['K8S_EVENT_DISABLE'] = 'Special-case-included despite missing prefix.  Appears at end of main keys.'
        os.environ['SCALYR_K8S_EVENT_DISABLE'] = 'true'
        os.environ['SCALYR_AAA'] = 'Should appear just after main keys'
        os.environ['SCALYR_XXX_A'] = 'A before b (ignores case)'
        os.environ['sCaLyR_XXX_b'] = 'b after A (ignores case)'
        os.environ['SCALYR_ZZZ'] = 'Should appear at the end'
        report_status(output, self.status, self.time)

        expected_output = """Scalyr Agent status.  See https://www.scalyr.com/help/scalyr-agent-2 for help

Current time:     Fri Sep  5 23:14:13 2014 UTC
Agent started at: Thu Sep  4 23:14:13 2014 UTC
Version:          2.0.0.beta.7
Agent running as: root
Agent log:        /var/logs/scalyr-agent/agent.log
ServerHost:       test_machine

View data from this agent at: https://www.scalyr.com/events?filter=$serverHost%3D%27test_machine%27


Agent configuration:
====================

Configuration files:   /etc/scalyr-agent-2/agent.json
                       /etc/scalyr-agent-2/agent.d/server.json
Status:                Good (files parsed successfully)
Last checked:          Fri Sep  5 23:14:13 2014 UTC
Last changed observed: Fri Sep  5 11:14:13 2014 UTC

Environment variables: SCALYR_API_KEY = <Redacted>
                       SCALYR_SERVER = <Missing>
                       K8S_EVENT_DISABLE = Special-case-included despite missing prefix.  Appears at end of main keys.
                       SCALYR_AAA = Should appear just after main keys
                       scalyr_K8S_CLUSTER_NAME = test_cluster
                       SCALYR_K8S_EVENT_DISABLE = true
                       SCALYR_XXX_A = A before b (ignores case)
                       sCaLyR_XXX_b = b after A (ignores case)
                       SCALYR_ZZZ = Should appear at the end


Log transmission:
=================

(these statistics cover the period from Fri Sep  5 11:14:13 2014 UTC)

Bytes uploaded successfully:               10000
Last successful communication with Scalyr: Fri Sep  5 23:13:13 2014 UTC
Last attempt:                              Fri Sep  5 23:13:13 2014 UTC
Last copy request size:                    10000

Path /var/logs/tomcat6/access.log: no matching readable file, last checked Fri Sep  5 23:14:03 2014 UTC
Path /var/logs/tomcat6/catalina.log: copied 2341234 bytes (214324 lines), 1243 bytes pending, 12 bytes skipped, 1432 bytes failed, last checked Fri Sep  5 23:12:13 2014 UTC

Glob: /var/logs/cron/*.log:: last scanned for glob matches at Fri Sep  5 23:14:03 2014 UTC
  /var/logs/cron/logrotate.log: copied 2341234 bytes (214324 lines), 1243 bytes pending, 12 bytes skipped, 1432 bytes failed, last checked Fri Sep  5 23:12:13 2014 UTC
  /var/logs/cron/ohno.log: copied 23434 bytes (214324 lines), 12943 bytes pending, 12 bytes skipped, 1432 bytes failed, 5 bytes dropped by sampling (10 lines), 10 redactions, last checked Fri Sep  5 23:12:13 2014 UTC
Glob: /var/logs/silly/*.log:: last scanned for glob matches at Fri Sep  5 23:14:03 2014 UTC


Monitors:
=========

(these statistics cover the period from Fri Sep  5 11:14:13 2014 UTC)

Running monitors:
  linux_process_metrics(agent): 50 lines emitted, 2 errors
  linux_system_metrics(): 20 lines emitted, 0 errors

Failed monitors:
  bad_monitor() 20 lines emitted, 40 errors
"""
        self.assertEquals(expected_output, output.getvalue())

    def test_bad_config(self):
        self.status.config_status.last_error = 'Bad stuff'

        output = cStringIO.StringIO()
        report_status(output, self.status, self.time)

        expected_output = """Scalyr Agent status.  See https://www.scalyr.com/help/scalyr-agent-2 for help

Current time:     Fri Sep  5 23:14:13 2014 UTC
Agent started at: Thu Sep  4 23:14:13 2014 UTC
Version:          2.0.0.beta.7
Agent running as: root
Agent log:        /var/logs/scalyr-agent/agent.log
ServerHost:       test_machine

View data from this agent at: https://www.scalyr.com/events?filter=$serverHost%3D%27test_machine%27


Agent configuration:
====================

Configuration files:   /etc/scalyr-agent-2/agent.json
                       /etc/scalyr-agent-2/agent.d/server.json
Status:                Bad (could not parse, using last good version)
Last checked:          Fri Sep  5 23:14:13 2014 UTC
Last changed observed: Fri Sep  5 11:14:13 2014 UTC
Parsing error:         Bad stuff

Environment variables: SCALYR_API_KEY = <Missing>
                       SCALYR_SERVER = <Missing>


Log transmission:
=================

(these statistics cover the period from Fri Sep  5 11:14:13 2014 UTC)

Bytes uploaded successfully:               10000
Last successful communication with Scalyr: Fri Sep  5 23:13:13 2014 UTC
Last attempt:                              Fri Sep  5 23:13:13 2014 UTC
Last copy request size:                    10000

Path /var/logs/tomcat6/access.log: no matching readable file, last checked Fri Sep  5 23:14:03 2014 UTC
Path /var/logs/tomcat6/catalina.log: copied 2341234 bytes (214324 lines), 1243 bytes pending, 12 bytes skipped, 1432 bytes failed, last checked Fri Sep  5 23:12:13 2014 UTC

Glob: /var/logs/cron/*.log:: last scanned for glob matches at Fri Sep  5 23:14:03 2014 UTC
  /var/logs/cron/logrotate.log: copied 2341234 bytes (214324 lines), 1243 bytes pending, 12 bytes skipped, 1432 bytes failed, last checked Fri Sep  5 23:12:13 2014 UTC
  /var/logs/cron/ohno.log: copied 23434 bytes (214324 lines), 12943 bytes pending, 12 bytes skipped, 1432 bytes failed, 5 bytes dropped by sampling (10 lines), 10 redactions, last checked Fri Sep  5 23:12:13 2014 UTC
Glob: /var/logs/silly/*.log:: last scanned for glob matches at Fri Sep  5 23:14:03 2014 UTC


Monitors:
=========

(these statistics cover the period from Fri Sep  5 11:14:13 2014 UTC)

Running monitors:
  linux_process_metrics(agent): 50 lines emitted, 2 errors
  linux_system_metrics(): 20 lines emitted, 0 errors

Failed monitors:
  bad_monitor() 20 lines emitted, 40 errors
"""
        self.assertEquals(expected_output, output.getvalue())

    def test_bad_copy_response(self):
        self.status.copying_manager_status.last_response = 'Some weird stuff'
        self.status.copying_manager_status.last_response_status = 'error'
        self.status.copying_manager_status.total_errors = 5

        output = cStringIO.StringIO()
        report_status(output, self.status, self.time)

        expected_output = """Scalyr Agent status.  See https://www.scalyr.com/help/scalyr-agent-2 for help

Current time:     Fri Sep  5 23:14:13 2014 UTC
Agent started at: Thu Sep  4 23:14:13 2014 UTC
Version:          2.0.0.beta.7
Agent running as: root
Agent log:        /var/logs/scalyr-agent/agent.log
ServerHost:       test_machine

View data from this agent at: https://www.scalyr.com/events?filter=$serverHost%3D%27test_machine%27


Agent configuration:
====================

Configuration files:   /etc/scalyr-agent-2/agent.json
                       /etc/scalyr-agent-2/agent.d/server.json
Status:                Good (files parsed successfully)
Last checked:          Fri Sep  5 23:14:13 2014 UTC
Last changed observed: Fri Sep  5 11:14:13 2014 UTC

Environment variables: SCALYR_API_KEY = <Missing>
                       SCALYR_SERVER = <Missing>


Log transmission:
=================

(these statistics cover the period from Fri Sep  5 11:14:13 2014 UTC)

Bytes uploaded successfully:               10000
Last successful communication with Scalyr: Fri Sep  5 23:13:13 2014 UTC
Last attempt:                              Fri Sep  5 23:13:13 2014 UTC
Last copy request size:                    10000
Last copy response size:                   16
Last copy response status:                 error
Last copy response:                        Some weird stuff
Total responses with errors:               5 (see '/var/logs/scalyr-agent/agent.log' for details)

Path /var/logs/tomcat6/access.log: no matching readable file, last checked Fri Sep  5 23:14:03 2014 UTC
Path /var/logs/tomcat6/catalina.log: copied 2341234 bytes (214324 lines), 1243 bytes pending, 12 bytes skipped, 1432 bytes failed, last checked Fri Sep  5 23:12:13 2014 UTC

Glob: /var/logs/cron/*.log:: last scanned for glob matches at Fri Sep  5 23:14:03 2014 UTC
  /var/logs/cron/logrotate.log: copied 2341234 bytes (214324 lines), 1243 bytes pending, 12 bytes skipped, 1432 bytes failed, last checked Fri Sep  5 23:12:13 2014 UTC
  /var/logs/cron/ohno.log: copied 23434 bytes (214324 lines), 12943 bytes pending, 12 bytes skipped, 1432 bytes failed, 5 bytes dropped by sampling (10 lines), 10 redactions, last checked Fri Sep  5 23:12:13 2014 UTC
Glob: /var/logs/silly/*.log:: last scanned for glob matches at Fri Sep  5 23:14:03 2014 UTC


Monitors:
=========

(these statistics cover the period from Fri Sep  5 11:14:13 2014 UTC)

Running monitors:
  linux_process_metrics(agent): 50 lines emitted, 2 errors
  linux_system_metrics(): 20 lines emitted, 0 errors

Failed monitors:
  bad_monitor() 20 lines emitted, 40 errors
"""
        self.assertEquals(expected_output, output.getvalue())
