# Copyright 2019 Scalyr Inc.
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

from __future__ import unicode_literals
from __future__ import absolute_import

from __future__ import print_function
import datetime
import os
import re
import tempfile
from uuid import UUID

from scalyr_agent.log_watcher import LogWatcher

from scalyr_agent.builtin_monitors.journald_monitor import JournaldMonitor
from scalyr_agent.test_base import BaseScalyrLogCaptureTestCase

import mock

from scalyr_agent.test_util import ScalyrTestUtils
from scalyr_agent.util import FakeClock


def empty():
    pass


class JournaldMonitorTest(BaseScalyrLogCaptureTestCase):
    def test_format_msg_default(self):
        def fake_init(self):
            pass

        with mock.patch.object(JournaldMonitor, "_initialize", fake_init):
            with mock.patch.object(JournaldMonitor, "__init__", fake_init):
                monitor = JournaldMonitor()  # pylint: disable=no-value-for-parameter
                msg = monitor.format_msg(
                    'Test message: {key: value} !@#$%^&*() "wawawa"', None
                )
                self.assertEqual(
                    'details "Test message: {key: value} !@#$%^&*() \\"wawawa\\""', msg
                )

    def test_format_msg_extra_fields_default(self):
        def fake_init(self):
            pass

        with mock.patch.object(JournaldMonitor, "_initialize", fake_init):
            with mock.patch.object(JournaldMonitor, "__init__", fake_init):
                monitor = JournaldMonitor()  # pylint: disable=no-value-for-parameter
                msg = monitor.format_msg(
                    'Test message: {key: value} !@#$%^&*() "wawawa"',
                    None,
                    extra_fields={"key": "value"},
                )
                self.assertEqual(
                    'details "Test message: {key: value} !@#$%^&*() \\"wawawa\\"" key="value"',
                    msg,
                )
                msg = monitor.format_msg(
                    'Test message: {key: value} !@#$%^&*() "wawawa"',
                    None,
                    extra_fields={"key": "value", "key1": "value1", "key2": "value2"},
                )
                self.assertEqual(
                    msg,
                    'details "Test message: {key: value} !@#$%^&*() \\"wawawa\\"" key="value" key1="value1" key2="value2"',
                )

    def test_format_msg_emit_raw_details(self):
        def fake_init(self):
            pass

        with mock.patch.object(JournaldMonitor, "_initialize", fake_init):
            with mock.patch.object(JournaldMonitor, "__init__", fake_init):
                monitor = JournaldMonitor()  # pylint: disable=no-value-for-parameter
                msg = monitor.format_msg(
                    'Test message: {key: value} !@#$%^&*() "wawawa"',
                    {"emit_raw_details": True},
                )
                self.assertEqual(
                    'details Test message: {key: value} !@#$%^&*() "wawawa"', msg
                )

    def test_format_msg_extra_fields_emit_raw_details(self):
        def fake_init(self):
            pass

        with mock.patch.object(JournaldMonitor, "_initialize", fake_init):
            with mock.patch.object(JournaldMonitor, "__init__", fake_init):
                monitor = JournaldMonitor()  # pylint: disable=no-value-for-parameter
                msg = monitor.format_msg(
                    'Test message: {key: value} !@#$%^&*() "wawawa"',
                    {"emit_raw_details": True},
                    extra_fields={"key": "value"},
                )
                self.assertEqual(
                    'details Test message: {key: value} !@#$%^&*() "wawawa" key="value"',
                    msg,
                )
                msg = monitor.format_msg(
                    'Test message: {key: value} !@#$%^&*() "wawawa"',
                    {"emit_raw_details": True},
                    extra_fields={"key": "value", "key1": "value1", "key2": "value2"},
                )
                self.assertEqual(
                    msg,
                    'details Test message: {key: value} !@#$%^&*() "wawawa" key="value" key1="value1" key2="value2"',
                )

    def test_format_msg_detect_escaped_strings(self):
        def fake_init(self):
            pass

        with mock.patch.object(JournaldMonitor, "_initialize", fake_init):
            with mock.patch.object(JournaldMonitor, "__init__", fake_init):
                monitor = JournaldMonitor()  # pylint: disable=no-value-for-parameter
                msg = monitor.format_msg(
                    '"Test message: {key: value} !@#$%^&*() "wawawa""',
                    {"detect_escaped_strings": True},
                )
                self.assertEqual(
                    'details "Test message: {key: value} !@#$%^&*() "wawawa""', msg
                )

    def test_format_msg_extra_fields_detect_escaped_strings(self):
        def fake_init(self):
            pass

        with mock.patch.object(JournaldMonitor, "_initialize", fake_init):
            with mock.patch.object(JournaldMonitor, "__init__", fake_init):
                monitor = JournaldMonitor()  # pylint: disable=no-value-for-parameter
                msg = monitor.format_msg(
                    '"Test message: {key: value} !@#$%^&*() "wawawa""',
                    {"detect_escaped_strings": True},
                    extra_fields={"key": '"value"'},
                )
                self.assertEqual(
                    'details "Test message: {key: value} !@#$%^&*() "wawawa"" key="value"',
                    msg,
                )
                msg = monitor.format_msg(
                    '"Test message: {key: value} !@#$%^&*() "wawawa""',
                    {"detect_escaped_strings": True},
                    extra_fields={
                        "key": '"value"',
                        "key1": "value1",
                        "key2": '"value2"',
                    },
                )
                self.assertEqual(
                    msg,
                    'details "Test message: {key: value} !@#$%^&*() "wawawa"" key="value" key1="value1" key2="value2"',
                )

    @mock.patch(
        "scalyr_agent.builtin_monitors.journald_monitor.verify_systemd_library_is_available",
        side_effect=empty,
    )
    def test_write_to_disk_emit_raw_details(self, verify):
        fake_journal = {
            "_AUDIT_LOGINUID": 1000,
            "_CAP_EFFECTIVE": "0",
            "_SELINUX_CONTEXT": "unconfined_u:unconfined_r:unconfined_t:s0-s0:c0.c1023",
            "_GID": 1000,
            "CODE_LINE": 1,
            "_HOSTNAME": "...",
            "_SYSTEMD_SESSION": 52,
            "_SYSTEMD_OWNER_UID": 1000,
            "MESSAGE": 'testing 1,2,3 "test"',
            # '__MONOTONIC_TIMESTAMP':
            # journal.Monotonic(timestamp=datetime.timedelta(2, 76200, 811585), bootid=UUID('958b7e26-df4c-453a-a0f9-a8406cb508f2')),
            "SYSLOG_IDENTIFIER": "python3",
            "_UID": 1000,
            "_EXE": "/usr/bin/python3",
            "_PID": 7733,
            "_COMM": "...",
            "CODE_FUNC": "<module>",
            "CODE_FILE": "<doctest journal.rst[4]>",
            "_SOURCE_REALTIME_TIMESTAMP": datetime.datetime(
                2015, 9, 5, 13, 17, 4, 944355
            ),
            # '__CURSOR': 's=...',
            "_BOOT_ID": UUID("958b7e26-df4c-453a-a0f9-a8406cb508f2"),
            "_CMDLINE": "/usr/bin/python3 ...",
            "_MACHINE_ID": UUID("263bb31e-3e13-4062-9bdb-f1f4518999d2"),
            "_SYSTEMD_SLICE": "user-1000.slice",
            "_AUDIT_SESSION": 52,
            "__REALTIME_TIMESTAMP": datetime.datetime(2015, 9, 5, 13, 17, 4, 945110),
            "_SYSTEMD_UNIT": "session-52.scope",
            "_SYSTEMD_CGROUP": "/user.slice/user-1000.slice/session-52.scope",
            "_TRANSPORT": "journal",
        }

        def fake_pending_entries(self):
            self._journal = [fake_journal]
            return True

        with mock.patch.object(
            JournaldMonitor, "_has_pending_entries", fake_pending_entries
        ):
            journal_directory = tempfile.mkdtemp(suffix="journal")
            fake_clock = FakeClock()
            manager_poll_interval = 30
            manager, _ = ScalyrTestUtils.create_test_monitors_manager(
                config_monitors=[
                    {
                        "module": "scalyr_agent.builtin_monitors.journald_monitor",
                        "journal_path": journal_directory,
                    }
                ],
                extra_toplevel_config={
                    "user_agent_refresh_interval": manager_poll_interval,
                    "agent_log_path": journal_directory,
                    "journald_logs": [
                        {
                            "journald_unit": ".*",
                            "parser": "journaldParser",
                            "emit_raw_details": True,
                        }
                    ],
                },
                null_logger=True,
                fake_clock=fake_clock,
            )
            monitor = manager.monitors[0]
            monitor.log_manager.set_log_watcher(LogWatcher())

            monitor.gather_sample()

            self.assertLogFileContainsLineRegex(
                "....\\-..\\-.. ..\\:..\\:..\\....."
                + re.escape(
                    ' [journald_monitor()] details testing 1,2,3 "test" boot_id="958b7e26-df4c-453a-a0f9-a8406cb508f2" machine_id="263bb31e-3e13-4062-9bdb-f1f4518999d2" pid="7733" timestamp="2015-09-05 13:17:04.944355" unit="session-52.scope"'
                ),
                file_path=os.path.join(journal_directory, "journald_monitor.log"),
            )

            manager.stop_manager(wait_on_join=False)

    @mock.patch(
        "scalyr_agent.builtin_monitors.journald_monitor.verify_systemd_library_is_available",
        side_effect=empty,
    )
    def test_write_to_disk_extra_emit_raw_details(self, verify):
        fake_journal = {
            "_AUDIT_LOGINUID": 1000,
            "_CAP_EFFECTIVE": "0",
            "_SELINUX_CONTEXT": "unconfined_u:unconfined_r:unconfined_t:s0-s0:c0.c1023",
            "_GID": 1000,
            "CODE_LINE": 1,
            "_HOSTNAME": "...",
            "_SYSTEMD_SESSION": 52,
            "_SYSTEMD_OWNER_UID": 1000,
            "MESSAGE": 'testing 1,2,3 "test"',
            # '__MONOTONIC_TIMESTAMP':
            # journal.Monotonic(timestamp=datetime.timedelta(2, 76200, 811585), bootid=UUID('958b7e26-df4c-453a-a0f9-a8406cb508f2')),
            "SYSLOG_IDENTIFIER": "python3",
            "_UID": 1000,
            "_EXE": "/usr/bin/python3",
            "_PID": 7733,
            "_COMM": "...",
            "CODE_FUNC": "<module>",
            "CODE_FILE": "<doctest journal.rst[4]>",
            "_SOURCE_REALTIME_TIMESTAMP": datetime.datetime(
                2015, 9, 5, 13, 17, 4, 944355
            ),
            # '__CURSOR': 's=...',
            "_BOOT_ID": UUID("958b7e26-df4c-453a-a0f9-a8406cb508f2"),
            "_CMDLINE": "/usr/bin/python3 ...",
            "_MACHINE_ID": UUID("263bb31e-3e13-4062-9bdb-f1f4518999d2"),
            "_SYSTEMD_SLICE": "user-1000.slice",
            "_AUDIT_SESSION": 52,
            "__REALTIME_TIMESTAMP": datetime.datetime(2015, 9, 5, 13, 17, 4, 945110),
            "_SYSTEMD_UNIT": "session-52.scope",
            "_SYSTEMD_CGROUP": "/user.slice/user-1000.slice/session-52.scope",
            "_TRANSPORT": "journal",
        }

        def fake_pending_entries(self):
            self._journal = [fake_journal]
            return True

        with mock.patch.object(
            JournaldMonitor, "_has_pending_entries", fake_pending_entries
        ):
            journal_directory = tempfile.mkdtemp(suffix="journal")
            fake_clock = FakeClock()
            manager_poll_interval = 30
            manager, _ = ScalyrTestUtils.create_test_monitors_manager(
                config_monitors=[
                    {
                        "module": "scalyr_agent.builtin_monitors.journald_monitor",
                        "journal_path": journal_directory,
                        "journal_fields": {"_TRANSPORT": "transport"},
                    }
                ],
                extra_toplevel_config={
                    "user_agent_refresh_interval": manager_poll_interval,
                    "agent_log_path": journal_directory,
                    "journald_logs": [
                        {
                            "journald_unit": ".*",
                            "parser": "journaldParser",
                            "emit_raw_details": True,
                        }
                    ],
                },
                null_logger=True,
                fake_clock=fake_clock,
            )
            monitor = manager.monitors[0]
            monitor.log_manager.set_log_watcher(LogWatcher())

            monitor.gather_sample()

            self.assertLogFileContainsLineRegex(
                "....\\-..\\-.. ..\\:..\\:..\\....."
                + re.escape(
                    ' [journald_monitor()] details testing 1,2,3 "test" transport="journal"'
                ),
                file_path=os.path.join(journal_directory, "journald_monitor.log"),
            )

            manager.stop_manager(wait_on_join=False)

    @mock.patch(
        "scalyr_agent.builtin_monitors.journald_monitor.verify_systemd_library_is_available",
        side_effect=empty,
    )
    def test_write_to_disk_default(self, verify):
        fake_journal = {
            "_AUDIT_LOGINUID": 1000,
            "_CAP_EFFECTIVE": "0",
            "_SELINUX_CONTEXT": "unconfined_u:unconfined_r:unconfined_t:s0-s0:c0.c1023",
            "_GID": 1000,
            "CODE_LINE": 1,
            "_HOSTNAME": "...",
            "_SYSTEMD_SESSION": 52,
            "_SYSTEMD_OWNER_UID": 1000,
            "MESSAGE": 'testing 1,2,3 "test"',
            # '__MONOTONIC_TIMESTAMP':
            # journal.Monotonic(timestamp=datetime.timedelta(2, 76200, 811585), bootid=UUID('958b7e26-df4c-453a-a0f9-a8406cb508f2')),
            "SYSLOG_IDENTIFIER": "python3",
            "_UID": 1000,
            "_EXE": "/usr/bin/python3",
            "_PID": 7733,
            "_COMM": "...",
            "CODE_FUNC": "<module>",
            "CODE_FILE": "<doctest journal.rst[4]>",
            "_SOURCE_REALTIME_TIMESTAMP": datetime.datetime(
                2015, 9, 5, 13, 17, 4, 944355
            ),
            # '__CURSOR': 's=...',
            "_BOOT_ID": UUID("958b7e26-df4c-453a-a0f9-a8406cb508f2"),
            "_CMDLINE": "/usr/bin/python3 ...",
            "_MACHINE_ID": UUID("263bb31e-3e13-4062-9bdb-f1f4518999d2"),
            "_SYSTEMD_SLICE": "user-1000.slice",
            "_AUDIT_SESSION": 52,
            "__REALTIME_TIMESTAMP": datetime.datetime(2015, 9, 5, 13, 17, 4, 945110),
            "_SYSTEMD_UNIT": "session-52.scope",
            "_SYSTEMD_CGROUP": "/user.slice/user-1000.slice/session-52.scope",
            "_TRANSPORT": "journal",
        }

        def fake_pending_entries(self):
            self._journal = [fake_journal]
            return True

        with mock.patch.object(
            JournaldMonitor, "_has_pending_entries", fake_pending_entries
        ):
            journal_directory = tempfile.mkdtemp(suffix="journal")
            fake_clock = FakeClock()
            manager_poll_interval = 30
            manager, _ = ScalyrTestUtils.create_test_monitors_manager(
                config_monitors=[
                    {
                        "module": "scalyr_agent.builtin_monitors.journald_monitor",
                        "journal_path": journal_directory,
                    }
                ],
                extra_toplevel_config={
                    "user_agent_refresh_interval": manager_poll_interval,
                    "agent_log_path": journal_directory,
                },
                null_logger=True,
                fake_clock=fake_clock,
            )
            monitor = manager.monitors[0]
            monitor.log_manager.set_log_watcher(LogWatcher())

            monitor.gather_sample()

            self.assertLogFileContainsLineRegex(
                "....\\-..\\-.. ..\\:..\\:..\\....."
                + re.escape(
                    ' [journald_monitor()] details "testing 1,2,3 \\"test\\"" boot_id="958b7e26-df4c-453a-a0f9-a8406cb508f2" machine_id="263bb31e-3e13-4062-9bdb-f1f4518999d2" pid="7733" timestamp="2015-09-05 13:17:04.944355" unit="session-52.scope"'
                ),
                file_path=os.path.join(journal_directory, "journald_monitor.log"),
            )

            manager.stop_manager(wait_on_join=False)

    @mock.patch(
        "scalyr_agent.builtin_monitors.journald_monitor.verify_systemd_library_is_available",
        side_effect=empty,
    )
    def test_write_to_disk_extra_default(self, verify):
        fake_journal = {
            "_AUDIT_LOGINUID": 1000,
            "_CAP_EFFECTIVE": "0",
            "_SELINUX_CONTEXT": "unconfined_u:unconfined_r:unconfined_t:s0-s0:c0.c1023",
            "_GID": 1000,
            "CODE_LINE": 1,
            "_HOSTNAME": "...",
            "_SYSTEMD_SESSION": 52,
            "_SYSTEMD_OWNER_UID": 1000,
            "MESSAGE": 'testing 1,2,3 "test"',
            # '__MONOTONIC_TIMESTAMP':
            # journal.Monotonic(timestamp=datetime.timedelta(2, 76200, 811585), bootid=UUID('958b7e26-df4c-453a-a0f9-a8406cb508f2')),
            "SYSLOG_IDENTIFIER": "python3",
            "_UID": 1000,
            "_EXE": "/usr/bin/python3",
            "_PID": 7733,
            "_COMM": "...",
            "CODE_FUNC": "<module>",
            "CODE_FILE": "<doctest journal.rst[4]>",
            "_SOURCE_REALTIME_TIMESTAMP": datetime.datetime(
                2015, 9, 5, 13, 17, 4, 944355
            ),
            # '__CURSOR': 's=...',
            "_BOOT_ID": UUID("958b7e26-df4c-453a-a0f9-a8406cb508f2"),
            "_CMDLINE": "/usr/bin/python3 ...",
            "_MACHINE_ID": UUID("263bb31e-3e13-4062-9bdb-f1f4518999d2"),
            "_SYSTEMD_SLICE": "user-1000.slice",
            "_AUDIT_SESSION": 52,
            "__REALTIME_TIMESTAMP": datetime.datetime(2015, 9, 5, 13, 17, 4, 945110),
            "_SYSTEMD_UNIT": "session-52.scope",
            "_SYSTEMD_CGROUP": "/user.slice/user-1000.slice/session-52.scope",
            "_TRANSPORT": "journal",
        }

        def fake_pending_entries(self):
            self._journal = [fake_journal]
            return True

        with mock.patch.object(
            JournaldMonitor, "_has_pending_entries", fake_pending_entries
        ):
            journal_directory = tempfile.mkdtemp(suffix="journal")
            fake_clock = FakeClock()
            manager_poll_interval = 30
            manager, _ = ScalyrTestUtils.create_test_monitors_manager(
                config_monitors=[
                    {
                        "module": "scalyr_agent.builtin_monitors.journald_monitor",
                        "journal_path": journal_directory,
                        "journal_fields": {"_TRANSPORT": "transport"},
                    }
                ],
                extra_toplevel_config={
                    "user_agent_refresh_interval": manager_poll_interval,
                    "agent_log_path": journal_directory,
                },
                null_logger=True,
                fake_clock=fake_clock,
            )
            monitor = manager.monitors[0]
            monitor.log_manager.set_log_watcher(LogWatcher())

            monitor.gather_sample()

            self.assertLogFileContainsLineRegex(
                "....\\-..\\-.. ..\\:..\\:..\\....."
                + re.escape(
                    ' [journald_monitor()] details "testing 1,2,3 \\"test\\"" transport="journal"'
                ),
                file_path=os.path.join(journal_directory, "journald_monitor.log"),
            )

            manager.stop_manager(wait_on_join=False)

    @mock.patch(
        "scalyr_agent.builtin_monitors.journald_monitor.verify_systemd_library_is_available",
        side_effect=empty,
    )
    def test_write_to_disk_detect_escaped_strings(self, verify):
        fake_journal = {
            "_AUDIT_LOGINUID": 1000,
            "_CAP_EFFECTIVE": "0",
            "_SELINUX_CONTEXT": "unconfined_u:unconfined_r:unconfined_t:s0-s0:c0.c1023",
            "_GID": 1000,
            "CODE_LINE": 1,
            "_HOSTNAME": "...",
            "_SYSTEMD_SESSION": 52,
            "_SYSTEMD_OWNER_UID": 1000,
            "MESSAGE": '"testing 1,2,3 "test""',
            # '__MONOTONIC_TIMESTAMP':
            # journal.Monotonic(timestamp=datetime.timedelta(2, 76200, 811585), bootid=UUID('958b7e26-df4c-453a-a0f9-a8406cb508f2')),
            "SYSLOG_IDENTIFIER": "python3",
            "_UID": 1000,
            "_EXE": "/usr/bin/python3",
            "_PID": 7733,
            "_COMM": "...",
            "CODE_FUNC": "<module>",
            "CODE_FILE": "<doctest journal.rst[4]>",
            "_SOURCE_REALTIME_TIMESTAMP": datetime.datetime(
                2015, 9, 5, 13, 17, 4, 944355
            ),
            # '__CURSOR': 's=...',
            "_BOOT_ID": UUID("958b7e26-df4c-453a-a0f9-a8406cb508f2"),
            "_CMDLINE": "/usr/bin/python3 ...",
            "_MACHINE_ID": UUID("263bb31e-3e13-4062-9bdb-f1f4518999d2"),
            "_SYSTEMD_SLICE": "user-1000.slice",
            "_AUDIT_SESSION": 52,
            "__REALTIME_TIMESTAMP": datetime.datetime(2015, 9, 5, 13, 17, 4, 945110),
            "_SYSTEMD_UNIT": "session-52.scope",
            "_SYSTEMD_CGROUP": "/user.slice/user-1000.slice/session-52.scope",
            "_TRANSPORT": "journal",
        }

        def fake_pending_entries(self):
            self._journal = [fake_journal]
            return True

        with mock.patch.object(
            JournaldMonitor, "_has_pending_entries", fake_pending_entries
        ):
            journal_directory = tempfile.mkdtemp(suffix="journal")
            fake_clock = FakeClock()
            manager_poll_interval = 30
            manager, _ = ScalyrTestUtils.create_test_monitors_manager(
                config_monitors=[
                    {
                        "module": "scalyr_agent.builtin_monitors.journald_monitor",
                        "journal_path": journal_directory,
                    }
                ],
                extra_toplevel_config={
                    "user_agent_refresh_interval": manager_poll_interval,
                    "agent_log_path": journal_directory,
                    "journald_logs": [
                        {
                            "journald_unit": ".*",
                            "parser": "journaldParser",
                            "detect_escaped_strings": True,
                        }
                    ],
                },
                null_logger=True,
                fake_clock=fake_clock,
            )
            monitor = manager.monitors[0]
            monitor.log_manager.set_log_watcher(LogWatcher())

            monitor.gather_sample()

            self.assertLogFileContainsLineRegex(
                "....\\-..\\-.. ..\\:..\\:..\\....."
                + re.escape(
                    ' [journald_monitor()] details "testing 1,2,3 "test"" boot_id="958b7e26-df4c-453a-a0f9-a8406cb508f2" machine_id="263bb31e-3e13-4062-9bdb-f1f4518999d2" pid="7733" timestamp="2015-09-05 13:17:04.944355" unit="session-52.scope"'
                ),
                file_path=os.path.join(journal_directory, "journald_monitor.log"),
            )

            manager.stop_manager(wait_on_join=False)

    @mock.patch(
        "scalyr_agent.builtin_monitors.journald_monitor.verify_systemd_library_is_available",
        side_effect=empty,
    )
    def test_write_to_disk_extra_detect_escaped_strings(self, verify):
        fake_journal = {
            "_AUDIT_LOGINUID": 1000,
            "_CAP_EFFECTIVE": "0",
            "_SELINUX_CONTEXT": "unconfined_u:unconfined_r:unconfined_t:s0-s0:c0.c1023",
            "_GID": 1000,
            "CODE_LINE": 1,
            "_HOSTNAME": "...",
            "_SYSTEMD_SESSION": 52,
            "_SYSTEMD_OWNER_UID": 1000,
            "MESSAGE": '"testing 1,2,3 "test""',
            # '__MONOTONIC_TIMESTAMP':
            # journal.Monotonic(timestamp=datetime.timedelta(2, 76200, 811585), bootid=UUID('958b7e26-df4c-453a-a0f9-a8406cb508f2')),
            "SYSLOG_IDENTIFIER": "python3",
            "_UID": 1000,
            "_EXE": "/usr/bin/python3",
            "_PID": 7733,
            "_COMM": "...",
            "CODE_FUNC": "<module>",
            "CODE_FILE": "<doctest journal.rst[4]>",
            "_SOURCE_REALTIME_TIMESTAMP": datetime.datetime(
                2015, 9, 5, 13, 17, 4, 944355
            ),
            # '__CURSOR': 's=...',
            "_BOOT_ID": UUID("958b7e26-df4c-453a-a0f9-a8406cb508f2"),
            "_CMDLINE": "/usr/bin/python3 ...",
            "_MACHINE_ID": UUID("263bb31e-3e13-4062-9bdb-f1f4518999d2"),
            "_SYSTEMD_SLICE": "user-1000.slice",
            "_AUDIT_SESSION": 52,
            "__REALTIME_TIMESTAMP": datetime.datetime(2015, 9, 5, 13, 17, 4, 945110),
            "_SYSTEMD_UNIT": "session-52.scope",
            "_SYSTEMD_CGROUP": "/user.slice/user-1000.slice/session-52.scope",
            "_TRANSPORT": '"journal"',
        }

        def fake_pending_entries(self):
            self._journal = [fake_journal]
            return True

        with mock.patch.object(
            JournaldMonitor, "_has_pending_entries", fake_pending_entries
        ):
            journal_directory = tempfile.mkdtemp(suffix="journal")
            fake_clock = FakeClock()
            manager_poll_interval = 30
            manager, _ = ScalyrTestUtils.create_test_monitors_manager(
                config_monitors=[
                    {
                        "module": "scalyr_agent.builtin_monitors.journald_monitor",
                        "journal_path": journal_directory,
                        "journal_fields": {"_TRANSPORT": "transport"},
                    }
                ],
                extra_toplevel_config={
                    "user_agent_refresh_interval": manager_poll_interval,
                    "agent_log_path": journal_directory,
                    "journald_logs": [
                        {
                            "journald_unit": ".*",
                            "parser": "journaldParser",
                            "detect_escaped_strings": True,
                        }
                    ],
                },
                null_logger=True,
                fake_clock=fake_clock,
            )
            monitor = manager.monitors[0]
            monitor.log_manager.set_log_watcher(LogWatcher())

            monitor.gather_sample()

            self.assertLogFileContainsLineRegex(
                "....\\-..\\-.. ..\\:..\\:..\\....."
                + re.escape(
                    ' [journald_monitor()] details "testing 1,2,3 "test"" transport="journal"'
                ),
                file_path=os.path.join(journal_directory, "journald_monitor.log"),
            )

            manager.stop_manager(wait_on_join=False)
