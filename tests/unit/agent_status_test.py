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

from __future__ import unicode_literals
from __future__ import absolute_import

from io import open

__author__ = "czerwin@scalyr.com"

import io
import os
import json
import platform
import tempfile

import mock
import six

from scalyr_agent.agent_main import ScalyrAgent
from scalyr_agent.agent_main import STATUS_FORMAT_FILE
from scalyr_agent.configuration import Configuration
from scalyr_agent.platform_controller import PlatformController
from scalyr_agent.agent_status import (
    OverallStats,
    AgentStatus,
    ConfigStatus,
    LogProcessorStatus,
    MonitorStatus,
)
from scalyr_agent.agent_status import (
    CopyingManagerStatus,
    ShardedCopyingManagerStatus,
    MonitorManagerStatus,
    LogMatcherStatus,
    report_status,
    ApiKeyWorkerPoolStatus,
    CopyingManagerWorkerStatus,
)

from scalyr_agent.test_base import ScalyrTestCase
from scalyr_agent.compat import os_environ_unicode

BASE_DIR = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))


class TestOverallStats(ScalyrTestCase):
    def test___add___method(self):
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

        a.total_bytes_pending = 1
        a.skipped_new_bytes = 2
        a.skipped_preexisting_bytes = 3

        a.total_copy_iterations = 1
        a.total_read_time = 2
        a.total_compression_time = 3
        a.total_waiting_time = 4
        a.total_blocking_response_time = 5
        a.total_request_time = 6
        a.total_pipelined_requests = 7
        a.avg_bytes_produced_rate = 8
        a.avg_bytes_copied_rate = 9
        a.rate_limited_time_since_last_status = 10

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

        b.total_bytes_pending = 1
        b.skipped_new_bytes = 2
        b.skipped_preexisting_bytes = 3

        b.total_copy_iterations = 1
        b.total_read_time = 2
        b.total_compression_time = 3
        b.total_waiting_time = 4
        b.total_blocking_response_time = 5
        b.total_request_time = 6
        b.total_pipelined_requests = 7
        b.avg_bytes_produced_rate = 8
        b.avg_bytes_copied_rate = 9
        b.rate_limited_time_since_last_status = 10

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

        self.assertEquals(c.total_bytes_pending, 2)
        self.assertEquals(c.skipped_new_bytes, 4)
        self.assertEquals(c.skipped_preexisting_bytes, 6)

        self.assertEquals(c.total_copy_iterations, 2)
        self.assertEquals(c.total_read_time, 4)
        self.assertEquals(c.total_compression_time, 6)
        self.assertEquals(c.total_waiting_time, 8)
        self.assertEquals(c.total_blocking_response_time, 10)
        self.assertEquals(c.total_request_time, 12)
        self.assertEquals(c.total_pipelined_requests, 14)
        self.assertEquals(c.avg_bytes_produced_rate, 16)
        self.assertEquals(c.avg_bytes_copied_rate, 18)
        self.assertEquals(c.rate_limited_time_since_last_status, 20)


class TestReportStatus(ScalyrTestCase):
    maxDiff = None

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved_env)

    def setUp(self):
        super(TestReportStatus, self).setUp()
        self.saved_env = dict((k, v) for k, v in six.iteritems(os_environ_unicode))
        os.environ.clear()
        self.time = 1409958853
        self.status = AgentStatus()
        self.status.launch_time = self.time - 86400
        self.status.log_path = "/var/logs/scalyr-agent/agent.log"
        self.status.scalyr_server = "https://agent.scalyr.com"
        self.status.compression_type = "deflate"
        self.status.compression_level = 9
        self.status.server_host = "test_machine"
        self.status.user = "root"
        self.status.version = "2.0.0.beta.7"
        self.status.revision = "git revision"
        self.status.python_version = "3.6.8"

        config_status = ConfigStatus()
        self.status.config_status = config_status
        config_status.last_read_time = self.time - 43200
        config_status.last_check_time = self.time
        config_status.last_good_read = self.time - 43000
        config_status.path = "/etc/scalyr-agent-2/agent.json"
        config_status.status = "Good"
        config_status.additional_paths = ["/etc/scalyr-agent-2/agent.d/server.json"]

        copying_status = ShardedCopyingManagerStatus()
        self.status.copying_manager_status = copying_status
        copying_status.last_attempt_size = 10000
        copying_status.last_attempt_time = self.time - 60
        copying_status.last_responses_status_info = "All successful"
        copying_status.total_errors = 0
        copying_status.total_bytes_uploaded = 10000
        copying_status.last_success_time = self.time - 60
        copying_status.health_check_result = "Good"

        self.api_key1 = api_key1 = ApiKeyWorkerPoolStatus()
        api_key1.api_key_id = "0"
        api_key1.total_bytes_uploaded = 6000
        copying_status.api_key_worker_pools.append(api_key1)
        api_key1.last_success_time = self.time - 60
        api_key1.last_attempt_time = self.time - 60

        self.api_key2 = api_key2 = ApiKeyWorkerPoolStatus()
        api_key2.api_key_id = "1"
        api_key2.total_bytes_uploaded = 4000
        copying_status.api_key_worker_pools.append(api_key2)
        api_key2.last_success_time = self.time - 60
        api_key2.last_attempt_time = self.time - 60

        # =========

        api_key1.all_responses_successful = True
        api_key1.all_health_checks_good = True
        self.worker1_1 = worker1_1 = CopyingManagerWorkerStatus()
        worker1_1.worker_id = "worker1_1"
        worker1_1.last_response = "Everything is good."
        worker1_1.last_response_status = "success"
        worker1_1.health_check_result = "Good"

        self.worker1_2 = worker1_2 = CopyingManagerWorkerStatus()
        worker1_2.worker_id = "worker1_2"
        worker1_2.last_response = "Everything is good."
        worker1_2.last_response_status = "success"
        worker1_2.health_check_result = "Good"

        api_key1.workers.extend([worker1_1, worker1_2])

        # =

        copying_status.all_responses_successful = True
        copying_status.all_health_checks_good = True

        api_key2.all_responses_successful = True
        api_key2.all_health_checks_good = True
        self.worker2_1 = worker2_1 = CopyingManagerWorkerStatus()
        worker2_1.worker_id = "worker2_1"
        worker2_1.last_response = "Everything is good."
        worker2_1.last_response_status = "success"
        worker2_1.health_check_result = "Good"

        self.worker2_2 = worker2_2 = CopyingManagerWorkerStatus()
        worker2_2.worker_id = "worker2_2"
        worker2_2.last_response = "Everything is good."
        worker2_2.last_response_status = "success"
        worker2_2.health_check_result = "Good"
        api_key2.workers.extend([worker2_1, worker2_2])

        # =========

        # Add in one log path that isn't a glob but does not have any matches yet.
        log_matcher = LogMatcherStatus()
        copying_status.log_matchers.append(log_matcher)
        log_matcher.is_glob = False
        log_matcher.last_check_time = self.time - 10
        log_matcher.log_path = "/var/logs/tomcat6/access.log"

        # Add in another matcher that isn't a glob but does have a match.
        log_matcher = LogMatcherStatus()
        copying_status.log_matchers.append(log_matcher)
        log_matcher.is_glob = False
        log_matcher.last_check_time = self.time - 10
        log_matcher.log_path = "/var/logs/tomcat6/catalina.log"
        self.process_status1 = process_status1 = LogProcessorStatus()
        log_matcher.log_processors_status.append(process_status1)
        process_status1.log_path = "/var/logs/tomcat6/catalina.log"
        process_status1.last_scan_time = self.time - 120
        process_status1.total_bytes_copied = 2341234
        process_status1.total_bytes_pending = 1243
        process_status1.total_bytes_skipped = 12
        process_status1.total_bytes_failed = 1432
        process_status1.total_bytes_dropped_by_sampling = 0
        process_status1.total_lines_copied = 214324
        process_status1.total_lines_dropped_by_sampling = 0
        process_status1.total_redactions = 0
        worker1_1.log_processors.append(process_status1)

        # Add in another matcher that is a glob and has two matches.
        log_matcher = LogMatcherStatus()
        copying_status.log_matchers.append(log_matcher)
        log_matcher.is_glob = True
        log_matcher.last_check_time = self.time - 10
        log_matcher.log_path = "/var/logs/cron/*.log"
        self.process_status2 = process_status2 = LogProcessorStatus()
        log_matcher.log_processors_status.append(process_status2)
        process_status2.log_path = "/var/logs/cron/logrotate.log"
        process_status2.last_scan_time = self.time - 120
        process_status2.total_bytes_copied = 2341234
        process_status2.total_bytes_pending = 1243
        process_status2.total_bytes_skipped = 12
        process_status2.total_bytes_failed = 1432
        process_status2.total_bytes_dropped_by_sampling = 0
        process_status2.total_lines_copied = 214324
        process_status2.total_lines_dropped_by_sampling = 0
        process_status2.total_redactions = 0
        worker1_2.log_processors.append(process_status2)

        self.process_status3 = process_status3 = LogProcessorStatus()
        log_matcher.log_processors_status.append(process_status3)
        process_status3.log_path = "/var/logs/cron/ohno.log"
        process_status3.last_scan_time = self.time - 120
        process_status3.total_bytes_copied = 23434
        process_status3.total_bytes_pending = 12943
        process_status3.total_bytes_skipped = 12
        process_status3.total_bytes_failed = 1432
        process_status3.total_bytes_dropped_by_sampling = 5
        process_status3.total_lines_copied = 214324
        process_status3.total_lines_dropped_by_sampling = 10
        process_status3.total_redactions = 10
        worker2_1.log_processors.append(process_status3)

        # One more glob that doesn't have any matches.
        log_matcher = LogMatcherStatus()
        copying_status.log_matchers.append(log_matcher)
        log_matcher.is_glob = True
        log_matcher.last_check_time = self.time - 10
        log_matcher.log_path = "/var/logs/silly/*.log"

        # Now for the monitors.
        monitor_manager = MonitorManagerStatus()
        self.status.monitor_manager_status = monitor_manager
        monitor_manager.total_alive_monitors = 2

        monitor_status = MonitorStatus()
        monitor_manager.monitors_status.append(monitor_status)
        monitor_status.is_alive = True
        monitor_status.monitor_name = "linux_process_metrics(agent)"
        monitor_status.reported_lines = 50
        monitor_status.errors = 2

        monitor_status = MonitorStatus()
        monitor_manager.monitors_status.append(monitor_status)
        monitor_status.is_alive = True
        monitor_status.monitor_name = "linux_system_metrics()"
        monitor_status.reported_lines = 20
        monitor_status.errors = 0

        monitor_status = MonitorStatus()
        monitor_manager.monitors_status.append(monitor_status)
        monitor_status.is_alive = False
        monitor_status.monitor_name = "bad_monitor()"
        monitor_status.reported_lines = 20
        monitor_status.errors = 40

    def test_basic(self):
        output = io.StringIO()

        # Environment variables
        os.environ["SCALYR_API_KEY"] = "This private key should be redacted"
        # intentionally leave out required scalyr_server
        os.environ["SCALYR_K8S_CLUSTER_NAME"] = "test_cluster"
        os.environ[
            "K8S_EVENT_DISABLE"
        ] = "Special-case-included despite missing prefix.  Appears at end of main keys."
        os.environ["SCALYR_K8S_EVENT_DISABLE"] = "true"
        os.environ["SCALYR_AAA"] = "Should appear just after main keys"
        os.environ["SCALYR_XXX_A"] = "A before b (ignores case)"

        # On Windows keys are not case sensitive and get upper cased
        if platform.system() == "Windows":
            os.environ["SCALYR_XXX_B"] = "b after A (ignores case)"
        else:
            os.environ["sCaLyR_XXX_b"] = "b after A (ignores case)"

        os.environ["SCALYR_ZZZ"] = "Should appear at the end"
        report_status(output, self.status, self.time)

        expected_output = """Scalyr Agent status.  See https://www.scalyr.com/help/scalyr-agent-2 for help

Current time:            Fri Sep  5 23:14:13 2014 UTC
Agent started at:        Thu Sep  4 23:14:13 2014 UTC
Version:                 2.0.0.beta.7
VCS revision:            git revision
Python version:          3.6.8
Agent running as:        root
Agent log:               /var/logs/scalyr-agent/agent.log
ServerHost:              test_machine
Compression algorithm:   deflate
Compression level:       9

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
                       SCALYR_K8S_CLUSTER_NAME = test_cluster
                       SCALYR_K8S_EVENT_DISABLE = true
                       SCALYR_XXX_A = A before b (ignores case)
                       sCaLyR_XXX_b = b after A (ignores case)
                       SCALYR_ZZZ = Should appear at the end


Log transmission:
=================

(these statistics cover the period from Fri Sep  5 11:14:13 2014 UTC)

Bytes uploaded successfully:               10000
Last requests:                             All successful
Health check:                              Good

Api keys statistics
-------------------
Api key ID: 0
    Bytes uploaded successfully:               6000
    Last successful communication with Scalyr: Fri Sep  5 23:13:13 2014 UTC
    Last attempt:                              Fri Sep  5 23:13:13 2014 UTC
    Files:
        /var/logs/cron/logrotate.log
        /var/logs/tomcat6/catalina.log

Api key ID: 1
    Bytes uploaded successfully:               4000
    Last successful communication with Scalyr: Fri Sep  5 23:13:13 2014 UTC
    Last attempt:                              Fri Sep  5 23:13:13 2014 UTC
    Files:
        /var/logs/cron/ohno.log

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

        if platform.system() == "Windows":
            # On Windows keys are not case sensitive and get upper cased
            expected_output = expected_output.replace(
                "sCaLyR_XXX_b", "sCaLyR_XXX_b".upper()
            )

        self.assertEquals(expected_output, output.getvalue())

    def test_bad_config(self):
        self.status.config_status.last_error = "Bad stuff"

        output = io.StringIO()
        report_status(output, self.status, self.time)

        expected_output = """Scalyr Agent status.  See https://www.scalyr.com/help/scalyr-agent-2 for help

Current time:            Fri Sep  5 23:14:13 2014 UTC
Agent started at:        Thu Sep  4 23:14:13 2014 UTC
Version:                 2.0.0.beta.7
VCS revision:            git revision
Python version:          3.6.8
Agent running as:        root
Agent log:               /var/logs/scalyr-agent/agent.log
ServerHost:              test_machine
Compression algorithm:   deflate
Compression level:       9

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
Last requests:                             All successful
Health check:                              Good

Api keys statistics
-------------------
Api key ID: 0
    Bytes uploaded successfully:               6000
    Last successful communication with Scalyr: Fri Sep  5 23:13:13 2014 UTC
    Last attempt:                              Fri Sep  5 23:13:13 2014 UTC
    Files:
        /var/logs/cron/logrotate.log
        /var/logs/tomcat6/catalina.log

Api key ID: 1
    Bytes uploaded successfully:               4000
    Last successful communication with Scalyr: Fri Sep  5 23:13:13 2014 UTC
    Last attempt:                              Fri Sep  5 23:13:13 2014 UTC
    Files:
        /var/logs/cron/ohno.log

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
        # Set the responses for all workers of the first api key as failed.

        manager_status = self.status.copying_manager_status
        manager_status.last_responses_status_info = (
            "Last requests on some workers is not successful, see below for more info."
        )

        api_key1 = self.api_key1
        api_key1.total_errors = 5

        api_key1.all_responses_successful = False
        api_key1.all_health_checks_good = True
        worker1_1 = self.worker1_1
        worker1_1.last_response = "Bad response on worker1"
        worker1_1.last_response_status = "Bad"
        worker1_1.health_check_result = "Good"

        worker1_2 = self.worker1_2
        worker1_2.last_response = "Bad response on worker2"
        worker1_2.last_response_status = "Bad"
        worker1_2.health_check_result = "Good"

        manager_status.total_errors = 5

        output = io.StringIO()
        report_status(output, self.status, self.time)

        expected_output = """Scalyr Agent status.  See https://www.scalyr.com/help/scalyr-agent-2 for help

Current time:            Fri Sep  5 23:14:13 2014 UTC
Agent started at:        Thu Sep  4 23:14:13 2014 UTC
Version:                 2.0.0.beta.7
VCS revision:            git revision
Python version:          3.6.8
Agent running as:        root
Agent log:               /var/logs/scalyr-agent/agent.log
ServerHost:              test_machine
Compression algorithm:   deflate
Compression level:       9

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
Last requests:                             Last requests on some workers is not successful, see below for more info.
Health check:                              Good
Total responses with errors:               5 (see '/var/logs/scalyr-agent/agent.log' for details)

Api keys statistics
-------------------
Api key ID: 0
    Bytes uploaded successfully:               6000
    Last successful communication with Scalyr: Fri Sep  5 23:13:13 2014 UTC
    Last attempt:                              Fri Sep  5 23:13:13 2014 UTC
    Failed copy response statuses:
        worker1_1:
            Last copy response status:         Bad
            Last copy response:                Bad response on worker1
        worker1_2:
            Last copy response status:         Bad
            Last copy response:                Bad response on worker2
    Total responses with errors:               5 (see '/var/logs/scalyr-agent/agent.log' for details)
    Files:
        /var/logs/cron/logrotate.log
        /var/logs/tomcat6/catalina.log

Api key ID: 1
    Bytes uploaded successfully:               4000
    Last successful communication with Scalyr: Fri Sep  5 23:13:13 2014 UTC
    Last attempt:                              Fri Sep  5 23:13:13 2014 UTC
    Files:
        /var/logs/cron/ohno.log

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

    def test_no_health_check(self):
        output = io.StringIO()

        self.status.copying_manager_status.health_check_result = None

        # Environment variables
        os.environ["SCALYR_API_KEY"] = "This private key should be redacted"
        # intentionally leave out required scalyr_server
        os.environ["SCALYR_K8S_CLUSTER_NAME"] = "test_cluster"
        os.environ[
            "K8S_EVENT_DISABLE"
        ] = "Special-case-included despite missing prefix.  Appears at end of main keys."
        os.environ["SCALYR_K8S_EVENT_DISABLE"] = "true"
        os.environ["SCALYR_AAA"] = "Should appear just after main keys"
        os.environ["SCALYR_XXX_A"] = "A before b (ignores case)"

        # On Windows keys are not case sensitive and get upper cased
        if platform.system() == "Windows":
            os.environ["SCALYR_XXX_B"] = "b after A (ignores case)"
        else:
            os.environ["sCaLyR_XXX_b"] = "b after A (ignores case)"

        os.environ["SCALYR_ZZZ"] = "Should appear at the end"
        report_status(output, self.status, self.time)

        expected_output = """Scalyr Agent status.  See https://www.scalyr.com/help/scalyr-agent-2 for help

Current time:            Fri Sep  5 23:14:13 2014 UTC
Agent started at:        Thu Sep  4 23:14:13 2014 UTC
Version:                 2.0.0.beta.7
VCS revision:            git revision
Python version:          3.6.8
Agent running as:        root
Agent log:               /var/logs/scalyr-agent/agent.log
ServerHost:              test_machine
Compression algorithm:   deflate
Compression level:       9

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
                       SCALYR_K8S_CLUSTER_NAME = test_cluster
                       SCALYR_K8S_EVENT_DISABLE = true
                       SCALYR_XXX_A = A before b (ignores case)
                       sCaLyR_XXX_b = b after A (ignores case)
                       SCALYR_ZZZ = Should appear at the end


Log transmission:
=================

(these statistics cover the period from Fri Sep  5 11:14:13 2014 UTC)

Bytes uploaded successfully:               10000
Last requests:                             All successful

Api keys statistics
-------------------
Api key ID: 0
    Bytes uploaded successfully:               6000
    Last successful communication with Scalyr: Fri Sep  5 23:13:13 2014 UTC
    Last attempt:                              Fri Sep  5 23:13:13 2014 UTC
    Files:
        /var/logs/cron/logrotate.log
        /var/logs/tomcat6/catalina.log

Api key ID: 1
    Bytes uploaded successfully:               4000
    Last successful communication with Scalyr: Fri Sep  5 23:13:13 2014 UTC
    Last attempt:                              Fri Sep  5 23:13:13 2014 UTC
    Files:
        /var/logs/cron/ohno.log

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

        if platform.system() == "Windows":
            # On Windows keys are not case sensitive and get upper cased
            expected_output = expected_output.replace(
                "sCaLyR_XXX_b", "sCaLyR_XXX_b".upper()
            )

        self.assertEquals(expected_output, output.getvalue())

    def test_last_success_is_none(self):
        manager_status = self.status.copying_manager_status

        manager_status.last_responses_status_info = (
            "Last requests on some workers is not successful, see below for more info."
        )

        api_key1 = self.api_key1
        api_key1.all_responses_successful = False
        worker1_1 = self.worker1_1
        worker1_1.last_response = "Some weird stuff"
        worker1_1.last_response_status = "error"
        worker1_1.total_errors = 5
        api_key1.last_success_time = None
        worker1_1.last_success_time = None

        worker1_2 = self.worker1_2
        worker1_2.last_response = "Some weird stuff"
        worker1_2.last_response_status = "error"
        worker1_2.total_errors = 5
        worker1_2.last_success_time = None

        api_key1.total_errors = 10

        manager_status.total_errors = 10

        output = io.StringIO()
        report_status(output, self.status, self.time)
        expected_output = """Scalyr Agent status.  See https://www.scalyr.com/help/scalyr-agent-2 for help

Current time:            Fri Sep  5 23:14:13 2014 UTC
Agent started at:        Thu Sep  4 23:14:13 2014 UTC
Version:                 2.0.0.beta.7
VCS revision:            git revision
Python version:          3.6.8
Agent running as:        root
Agent log:               /var/logs/scalyr-agent/agent.log
ServerHost:              test_machine
Compression algorithm:   deflate
Compression level:       9

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
Last requests:                             Last requests on some workers is not successful, see below for more info.
Health check:                              Good
Total responses with errors:               10 (see '/var/logs/scalyr-agent/agent.log' for details)

Api keys statistics
-------------------
Api key ID: 0
    Bytes uploaded successfully:               6000
    Last successful communication with Scalyr: Never
    Last attempt:                              Fri Sep  5 23:13:13 2014 UTC
    Failed copy response statuses:
        worker1_1:
            Last copy response status:         error
            Last copy response:                Some weird stuff
        worker1_2:
            Last copy response status:         error
            Last copy response:                Some weird stuff
    Total responses with errors:               10 (see '/var/logs/scalyr-agent/agent.log' for details)
    Files:
        /var/logs/cron/logrotate.log
        /var/logs/tomcat6/catalina.log

Api key ID: 1
    Bytes uploaded successfully:               4000
    Last successful communication with Scalyr: Fri Sep  5 23:13:13 2014 UTC
    Last attempt:                              Fri Sep  5 23:13:13 2014 UTC
    Files:
        /var/logs/cron/ohno.log

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

    def test_status_to_dict(self):
        result = self.status.to_dict()

        # Simple value on the OverallStats object
        self.assertEqual(result["user"], "root")
        self.assertEqual(result["version"], "2.0.0.beta.7")
        self.assertEqual(result["revision"], "git revision")

        # Verify nested status objects are recursively serialized to simple native types
        config_status = result["config_status"]
        self.assertEqual(config_status["status"], "Good")
        self.assertEqual(config_status["last_error"], None)
        self.assertEqual(config_status["last_check_time"], 1409958853)

        copying_manager_status = result["copying_manager_status"]
        self.assertEqual(copying_manager_status["last_attempt_size"], 10000)
        self.assertEqual(copying_manager_status["log_matchers"][0]["is_glob"], False)
        self.assertEqual(
            copying_manager_status["log_matchers"][0]["log_path"],
            "/var/logs/tomcat6/access.log",
        )

        monitor_manager_status = result["monitor_manager_status"]
        self.assertEqual(monitor_manager_status["total_alive_monitors"], 2)
        self.assertEqual(monitor_manager_status["monitors_status"][0]["errors"], 2)
        self.assertEqual(monitor_manager_status["monitors_status"][0]["is_alive"], True)
        self.assertEqual(
            monitor_manager_status["monitors_status"][0]["monitor_name"],
            "linux_process_metrics(agent)",
        )

        # Verify dict contains only simple types - JSON.dumps would fail if it doesn't
        result_json = json.dumps(result)
        self.assertEqual(json.loads(result_json), result)

    def test_health_status(self):
        output = io.StringIO()
        report_status(output, self.status, self.time)
        expected_output = "Health check:                              Good\n"
        self.assertTrue(expected_output in output.getvalue())

    def test_health_status_bad(self):
        self.status.copying_manager_status.health_check_result = (
            "Some workers has failed, see below for more info."
        )
        output = io.StringIO()
        report_status(output, self.status, self.time)
        expected_output = "Health check:                              Some workers has failed, see below for more info.\n"
        self.assertTrue(expected_output in output.getvalue())


class AgentMainStatusHandlerTestCase(ScalyrTestCase):
    def setUp(self):
        super(AgentMainStatusHandlerTestCase, self).setUp()

        self.data_path = tempfile.mkdtemp(suffix="agent-data-path")
        self.status_format_file = os.path.join(self.data_path, STATUS_FORMAT_FILE)

        default_paths = mock.Mock()
        default_paths.agent_data_path = self.data_path
        default_paths.agent_log_path = "agent.log"

        config_file = os.path.join(BASE_DIR, "fixtures/configs/agent1.json")
        config = Configuration(config_file, default_paths, None)
        config.parse()

        self.agent = ScalyrAgent(PlatformController())
        self.agent._ScalyrAgent__config = config
        self.agent._ScalyrAgent__escalator = mock.Mock()
        self.agent._ScalyrAgent__escalator.is_user_change_required = mock.Mock(
            return_value=False
        )

        self.original_generate_status = self.agent._ScalyrAgent__generate_status

    def tearDown(self):
        super(AgentMainStatusHandlerTestCase, self).setUp()

        self.agent._ScalyrAgent__generate_status = self.original_generate_status

    def test_report_status_to_file_no_format_specified(self):
        # No format is provided, should default to "text"
        status_file = self.agent._ScalyrAgent__report_status_to_file()
        content = self._read_status_file(status_file)

        self.assertTrue("Current time:" in content)
        self.assertTrue("ServerHost:" in content)
        self.assertTrue("Agent configuration:" in content)

    def test_report_status_to_file_text_format_specified(self):
        # "text" format is explicitly provided
        self._write_status_format_file("text")

        status_file = self.agent._ScalyrAgent__report_status_to_file()
        content = self._read_status_file(status_file)

        self.assertTrue("Current time:" in content)
        self.assertTrue("ServerHost:" in content)
        self.assertTrue("Agent configuration:" in content)

    def test_report_status_to_file_invalid_format_specified(self):
        # invalid format is explicitly provided, should fall back to text
        self._write_status_format_file("invalid")

        status_file = self.agent._ScalyrAgent__report_status_to_file()
        content = self._read_status_file(status_file)

        self.assertTrue("Current time:" in content)
        self.assertTrue("ServerHost:" in content)
        self.assertTrue("Agent configuration:" in content)

    def test_report_status_to_file_json_format_specified(self):
        # "json" format is explicitly provided
        self._write_status_format_file("json")

        status_file = self.agent._ScalyrAgent__report_status_to_file()
        content = self._read_status_file(status_file)

        self.assertFalse("Current time:" in content)
        self.assertFalse("ServerHost:" in content)
        self.assertFalse("Agent configuration:" in content)

        parsed = json.loads(content)
        self.assertTrue("config_status" in parsed)
        self.assertTrue("user" in parsed)
        self.assertTrue("scalyr_server" in parsed)

    def test__find_health_result_in_status_data_json_format_good(self):
        def mock_generate_status(*args, **kwargs):
            result = self.original_generate_status(*args, **kwargs)
            result.copying_manager_status = CopyingManagerStatus()
            result.copying_manager_status.health_check_result = "Good"
            return result

        self.agent._ScalyrAgent__generate_status = mock_generate_status

        self._write_status_format_file("json")

        status_file = self.agent._ScalyrAgent__report_status_to_file()
        content = self._read_status_file(status_file)
        self.assertTrue(content.startswith("{") and content.endswith("}"))

        result = self.agent._ScalyrAgent__find_health_result_in_status_data(content)
        self.assertEqual(result, "Good")

    def test__find_health_result_in_status_data_text_format_good(self):
        def mock_generate_status(*args, **kwargs):
            result = self.original_generate_status(*args, **kwargs)
            result.copying_manager_status = ShardedCopyingManagerStatus()
            result.copying_manager_status.total_errors = 0
            result.copying_manager_status.health_check_result = "Good"
            return result

        self.agent._ScalyrAgent__generate_status = mock_generate_status

        self._write_status_format_file("text")

        status_file = self.agent._ScalyrAgent__report_status_to_file()
        content = self._read_status_file(status_file)
        self.assertFalse(content.startswith("{") and content.endswith("}"))

        result = self.agent._ScalyrAgent__find_health_result_in_status_data(content)
        self.assertEqual(result, "Good")

    def test__detailed_status_correct_exit_return_code_is_returned(self):
        def mock_generate_status_wrapper(health_check_result):
            def mock_generate_status(*args, **kwargs):
                result = self.original_generate_status(*args, **kwargs)
                result.copying_manager_status = ShardedCopyingManagerStatus()
                result.copying_manager_status.total_errors = 0
                result.copying_manager_status.health_check_result = health_check_result
                return result

            return mock_generate_status

        # status_format=text, health_check=False, health_result="Good" - should return 0
        self._write_status_format_file("text")

        self.agent._ScalyrAgent__generate_status = mock_generate_status_wrapper("Good")
        status_file = self.agent._ScalyrAgent__report_status_to_file()
        self.assertTrue(status_file)
        content = self._read_status_file(status_file)
        self.assertFalse(content.startswith("{") and content.endswith("}"))

        return_code = self.agent._ScalyrAgent__detailed_status(
            self.data_path,
            status_format="text",
            health_check=False,
            zero_status_file=False,
        )
        self.assertEqual(return_code, 0)

        # status_format=text, health_check=True, health_result="Good" - should return 0
        self.agent._ScalyrAgent__generate_status = mock_generate_status_wrapper("Good")
        status_file = self.agent._ScalyrAgent__report_status_to_file()
        self.assertTrue(status_file)
        content = self._read_status_file(status_file)
        self.assertFalse(content.startswith("{") and content.endswith("}"))

        return_code = self.agent._ScalyrAgent__detailed_status(
            self.data_path,
            status_format="text",
            health_check=True,
            zero_status_file=False,
        )
        self.assertEqual(return_code, 0)

        # status_format=text, health_check=False, health_result="Bad" - should return 2
        self._write_status_format_file("text")

        self.agent._ScalyrAgent__generate_status = mock_generate_status_wrapper("Bad")
        status_file = self.agent._ScalyrAgent__report_status_to_file()
        self.assertTrue(status_file)
        content = self._read_status_file(status_file)
        self.assertFalse(content.startswith("{") and content.endswith("}"))

        return_code = self.agent._ScalyrAgent__detailed_status(
            self.data_path,
            status_format="text",
            health_check=False,
            zero_status_file=False,
        )
        self.assertEqual(return_code, 2)

        # status_format=text, health_check=True, health_result="Bad" - should return 2
        self._write_status_format_file("text")

        self.agent._ScalyrAgent__generate_status = mock_generate_status_wrapper("Bad")
        status_file = self.agent._ScalyrAgent__report_status_to_file()
        self.assertTrue(status_file)

        return_code = self.agent._ScalyrAgent__detailed_status(
            self.data_path,
            status_format="text",
            health_check=True,
            zero_status_file=False,
        )
        self.assertEqual(return_code, 2)

        # status_format=json, health_check=False, health_result="Bad" - should return 2
        self._write_status_format_file("json")

        self.agent._ScalyrAgent__generate_status = mock_generate_status_wrapper("Bad")
        status_file = self.agent._ScalyrAgent__report_status_to_file()
        self.assertTrue(status_file)
        content = self._read_status_file(status_file)
        self.assertTrue(content.startswith("{") and content.endswith("}"))

        return_code = self.agent._ScalyrAgent__detailed_status(
            self.data_path,
            status_format="json",
            health_check=False,
            zero_status_file=False,
        )
        self.assertEqual(return_code, 2)

        # status_format=json, health_check=True, health_result="Bad" - should return 2
        self._write_status_format_file("json")

        self.agent._ScalyrAgent__generate_status = mock_generate_status_wrapper("Bad")
        status_file = self.agent._ScalyrAgent__report_status_to_file()
        self.assertTrue(status_file)
        content = self._read_status_file(status_file)
        self.assertTrue(content.startswith("{") and content.endswith("}"))

        return_code = self.agent._ScalyrAgent__detailed_status(
            self.data_path,
            status_format="json",
            health_check=True,
            zero_status_file=False,
        )
        self.assertEqual(return_code, 2)

        # status_format=text, health_check=False, health_result="" - should return 0
        self._write_status_format_file("text")

        self.agent._ScalyrAgent__generate_status = mock_generate_status_wrapper(None)
        status_file = self.agent._ScalyrAgent__report_status_to_file()
        self.assertTrue(status_file)
        content = self._read_status_file(status_file)
        self.assertFalse(content.startswith("{") and content.endswith("}"))

        return_code = self.agent._ScalyrAgent__detailed_status(
            self.data_path,
            status_format="text",
            health_check=False,
            zero_status_file=False,
        )
        self.assertEqual(return_code, 0)

        # status_format=text, health_check=True, health_result="" - should return 3
        self._write_status_format_file("text")

        self.agent._ScalyrAgent__generate_status = mock_generate_status_wrapper(None)
        status_file = self.agent._ScalyrAgent__report_status_to_file()
        self.assertTrue(status_file)
        content = self._read_status_file(status_file)
        self.assertFalse(content.startswith("{") and content.endswith("}"))

        return_code = self.agent._ScalyrAgent__detailed_status(
            self.data_path,
            status_format="text",
            health_check=True,
            zero_status_file=False,
        )
        self.assertEqual(return_code, 3)

        # status_format=json, health_check=False, health_result="" - should return 0
        self._write_status_format_file("json")

        self.agent._ScalyrAgent__generate_status = mock_generate_status_wrapper(None)
        status_file = self.agent._ScalyrAgent__report_status_to_file()
        self.assertTrue(status_file)
        content = self._read_status_file(status_file)
        self.assertTrue(content.startswith("{") and content.endswith("}"))

        return_code = self.agent._ScalyrAgent__detailed_status(
            self.data_path,
            status_format="json",
            health_check=False,
            zero_status_file=False,
        )
        self.assertEqual(return_code, 0)

        # status_format=json, health_check=True, health_result="" - should return 3
        self._write_status_format_file("json")

        self.agent._ScalyrAgent__generate_status = mock_generate_status_wrapper(None)
        status_file = self.agent._ScalyrAgent__report_status_to_file()
        self.assertTrue(status_file)
        content = self._read_status_file(status_file)
        self.assertTrue(content.startswith("{") and content.endswith("}"))

        return_code = self.agent._ScalyrAgent__detailed_status(
            self.data_path,
            status_format="json",
            health_check=True,
            zero_status_file=False,
        )
        self.assertEqual(return_code, 3)

    def _write_status_format_file(self, status_format):
        with open(self.status_format_file, "w") as fp:
            fp.write(status_format.strip())

    def _read_status_file(self, status_file_path):
        with open(status_file_path, "r") as fp:
            content = fp.read()

        return content
