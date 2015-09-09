# Copyright 2015 Scalyr Inc.
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
import os
import tempfile
import errno
import threading

__author__ = 'czerwin@scalyr.com'


from scalyr_agent.platform_posix import StatusReporter, PidfileManager

from scalyr_agent.test_base import ScalyrTestCase


class TestStatusReporter(ScalyrTestCase):
    def setUp(self):
        self.receiver = StatusReporter()
        self.sender = StatusReporter(duplicate_reporter=self.receiver)

    def tearDown(self):
        self.receiver.close()
        self.sender.close()

    def test_basic_status(self):
        self.sender.report_status('My status')
        self.assertEquals(self.receiver.read_status(timeout=5.0), 'My status')

    def test_status_with_newlines(self):
        self.sender.report_status('My status\nAnother one\n')
        self.assertEquals(self.receiver.read_status(timeout=5.0), 'My status\nAnother one\n')

    def test_timeout_exceeded(self):
        self.assertEquals(self.receiver.read_status(timeout=0.0, timeout_status='timeout'), 'timeout')

    def test_no_timeout(self):
        self.sender.report_status('My status')
        self.assertEquals(self.receiver.read_status(), 'My status')


class TestPidfileManager(ScalyrTestCase):
    def setUp(self):
        self.__pidfile_name = self._create_tempfile_name()

        self.__test_manager = PidfileManager(self.__pidfile_name)
        """@type: PidfileManager"""
        self.__logged_messages = []

    def test_read_pid_no_existing_pidfile(self):
        self.assertIsNone(self.__test_manager.read_pid())

    def test_write_pid_no_existing_pidfile(self):
        my_pid = os.getpid()
        self.__test_manager.write_pid(pid=my_pid)
        self.assertEquals(self.__test_manager.read_pid(), my_pid)

    def test_read_pid_existing_pidfile_with_stale_pid(self):
        self._write_pid(pid=self._find_unused_pid())
        self.assertIsNone(self.__test_manager.read_pid())

    def test_read_pid_command_matching(self):
        self.__test_manager.set_options(check_command_line=True)
        my_pid = os.getpid()
        self.__test_manager.write_pid(pid=my_pid, command_line='foo')
        # Test the case where the command comes back the same as what we originally wrote.
        self.assertEquals(self.__test_manager.read_pid(command_line='foo'), my_pid)
        # Test the case where the command comes back different as what we originally wrote.
        self.assertNotEqual(self.__test_manager.read_pid(command_line='bar'), my_pid)

    def test_read_pid_not_matching_command(self):
        self.__test_manager.set_options(check_command_line=False)
        my_pid = os.getpid()
        self.__test_manager.write_pid(pid=my_pid, command_line='foo')
        # Test the case where the command comes back the same as what we originally wrote.
        self.assertEquals(self.__test_manager.read_pid(command_line='foo'), my_pid)
        # Test the case where the command comes back different as what we originally wrote.
        self.assertEquals(self.__test_manager.read_pid(command_line='bar'), my_pid)

    def test_logger(self):
        def log_it(message):
            self.__logged_messages.append(message)
        self.__test_manager.set_options(debug_logger=log_it)
        self.__test_manager.read_pid()
        self.assertGreater(len(self.__logged_messages), 0)

    def test_write_pid_detects_new_agent_during_write(self):
        self.__test_manager = InstrumentedPidfileManager(self.__pidfile_name)
        self.__test_manager.simulate_block()

        other_agent_is_alive = [False]

        def attempt_to_write_pid():
            other_agent_is_alive[0] = not self.__test_manager.write_pid(pid=-1)

        thread = threading.Thread(target=attempt_to_write_pid)
        thread.start()

        self.__test_manager.wait_until_blocked()
        my_pid = os.getpid()
        self._write_pid(my_pid)
        self.__test_manager.simulate_unblock()

        thread.join()

        self.assertTrue(other_agent_is_alive)
        self.assertEquals(self.__test_manager.read_pid(), my_pid)

    def _create_tempfile_name(self):
        handle, name = tempfile.mkstemp()

        tmp_fp = os.fdopen(handle)
        tmp_fp.close()

        if os.path.isfile(name):
            os.unlink(name)
        return name

    def _write_pid(self, pid):
        manager = PidfileManager(self.__pidfile_name)
        manager.write_pid(pid=pid)

    def _find_unused_pid(self):
        result = 10000
        while True:
            try:
                os.kill(result, 0)
            except OSError, e:
                # ESRCH indicates the process is not running, in which case we ignore the pidfile.
                if e.errno == errno.ESRCH:
                    return result
            result += 1


class InstrumentedPidfileManager(PidfileManager):
    def __init__(self, pidfile):
        self.__is_blocking = False
        self.__is_blocking_condition = threading.Condition()
        self.__unblock = True
        self.__unblock_condition = threading.Condition()

        PidfileManager.__init__(self, pidfile)

    def _lock_pidfile(self):
        self.__is_blocking_condition.acquire()
        self.__is_blocking = True
        self.__is_blocking_condition.notifyAll()
        self.__is_blocking_condition.release()

        self.__unblock_condition.acquire()
        try:
            while True:
                if self.__unblock:
                    return
                self.__unblock_condition.wait()
        finally:
            self.__unblock_condition.release()

    def _unlock_pidfile(self):
        return

    def wait_until_blocked(self):
        self.__is_blocking_condition.acquire()
        try:
            while True:
                if self.__is_blocking:
                    return
                self.__is_blocking_condition.wait()
        finally:
            self.__is_blocking_condition.release()

    def simulate_unblock(self):
        self.__unblock_condition.acquire()
        self.__unblock = True
        self.__unblock_condition.notifyAll()
        self.__unblock_condition.release()

    def simulate_block(self):
        self.__unblock_condition.acquire()
        self.__unblock = False
        self.__unblock_condition.release()

# Disable these tests on non-POSIX
if os.name != 'posix':
    TestStatusReporter = None
    TestPidfileManager = None