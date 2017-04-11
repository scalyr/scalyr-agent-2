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
import fcntl

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

    # read pid no existing file
    # read pid not finished writing
    # read pid with lock
    # read pid with lock not held
    # read pid of old format no pid
    # read pid of old format with pid

    # write pid no existing
    # write pid with existing
    # try to write pid with someone holding lock
    # try to write pid with someone with the legacy format with active pid

    def test_read_pid_no_existing_pidfile(self):
        self.assertIsNone(self.__test_manager.read_pid())

    def test_read_pid_write_not_finished(self):
        self._write_pidfile_contents('12345')
        self.assertIsNone(self.__test_manager.read_pid())

    def test_read_pid_pidfile_empty(self):
        self._write_pidfile_contents('')
        self.assertIsNone(self.__test_manager.read_pid())

    def test_read_pid_locked_format_with_agent_running(self):
        release_lock = self._write_pidfile_contents('%s locked\n' % os.getpid(), hold_lock=True)
        self.assertEquals(os.getpid(), self.__test_manager.read_pid())
        release_lock()

    def test_read_pid_with_agent_running(self):
        release_lock = self._write_pidfile_contents('%s\n' % os.getpid(), hold_lock=True)
        self.assertEquals(os.getpid(), self.__test_manager.read_pid())
        release_lock()

    def test_read_pid_locked_format_with_agent_gone_without_delete(self):
        self._write_pidfile_contents('%s locked\n' % os.getpid(), hold_lock=False)
        self.assertIsNone(self.__test_manager.read_pid())

    def test_read_pid_with_agent_gone_without_delete(self):
        self._write_pidfile_contents('%s\n' % os.getpid(), hold_lock=False)
        self.assertIsNone(self.__test_manager.read_pid())

    def test_read_pid_old_format_pid_not_running(self):
        self._write_pidfile_contents('%s command\n' % self._find_unused_pid(), hold_lock=False)
        self.assertIsNone(self.__test_manager.read_pid())

    def test_read_pid_old_format_pid_running(self):
        self._write_pidfile_contents('%s command\n' % os.getpid(), hold_lock=False)
        self.assertEquals(os.getpid(), self.__test_manager.read_pid())

    def test_write_pid_no_existing(self):
        self.assertIsNotNone(self.__test_manager.create_writer().write_pid(pid=1234))
        self.assertEquals('1234\n', self._read_pidfile_contents())

    def test_write_pid_lock_format_with_existing_but_not_running(self):
        self._write_pidfile_contents('%s locked\n' % os.getpid(), hold_lock=False)
        self.assertIsNotNone(self.__test_manager.create_writer().write_pid(pid=1234))
        self.assertEquals('1234\n', self._read_pidfile_contents())

    def test_write_pid_with_existing_but_not_running(self):
        self._write_pidfile_contents('%s\n' % os.getpid(), hold_lock=False)
        self.assertIsNotNone(self.__test_manager.create_writer().write_pid(pid=1234))
        self.assertEquals('1234\n', self._read_pidfile_contents())

    def test_write_pid_lock_format_while_already_running(self):
        releaser = self._write_pidfile_contents('%s locked\n' % os.getpid(), hold_lock=True)
        self.assertIsNone(self.__test_manager.create_writer().write_pid(pid=1234))
        releaser()

    def test_write_pid_while_already_running(self):
        releaser = self._write_pidfile_contents('%s\n' % os.getpid(), hold_lock=True)
        self.assertIsNone(self.__test_manager.create_writer().write_pid(pid=1234))
        releaser()

    def test_write_pid_while_legacy_agent_running(self):
        self._write_pidfile_contents('%s command\n' % os.getpid(), hold_lock=False)
        self.assertIsNone(self.__test_manager.create_writer().write_pid(pid=1234))

    def test_release_after_write_pid(self):
        release_lock = self.__test_manager.create_writer().write_pid(pid=1234)
        release_lock()

        self.assertFalse(os.path.isfile(self.__pidfile_name))

        release_lock = self.__test_manager.create_writer().write_pid(pid=1234)
        self.assertIsNotNone(release_lock)
        release_lock()

    def test_acquire_then_write_pid(self):
        writer = self.__test_manager.create_writer()
        release_lock = writer.acquire_pid_lock()
        self.assertIsNotNone(release_lock)

        release_lock = writer.write_pid(pid=1234)
        self.assertIsNotNone(release_lock)

        self.assertEquals('1234\n', self._read_pidfile_contents())
        release_lock()

    def test_logger(self):
        def log_it(message):
            self.__logged_messages.append(message)

        self.__test_manager.set_options(logger=log_it)
        self.__test_manager.read_pid()
        self.assertGreater(len(self.__logged_messages), 0)

    def test_debug_logger(self):
        def log_it(message):
            self.__logged_messages.append(message)

        self.__test_manager.set_options(debug_logger=log_it)
        self.__test_manager.read_pid()
        self.assertGreater(len(self.__logged_messages), 0)

    def _create_tempfile_name(self):
        handle, name = tempfile.mkstemp()

        tmp_fp = os.fdopen(handle)
        tmp_fp.close()

        if os.path.isfile(name):
            os.unlink(name)
        return name

    def _write_pidfile_contents(self, contents, hold_lock=False):
        fp = open(self.__pidfile_name, 'w')
        if len(contents) > 0:
            fp.write(contents)
            fp.flush()

        def release_it():
            fcntl.flock(fp, fcntl.LOCK_UN)
            fp.close()

        if hold_lock:
            fcntl.flock(fp, fcntl.LOCK_EX)
            return release_it
        else:
            fp.close()
            return None

    def _read_pidfile_contents(self):
        fp = open(self.__pidfile_name, 'r')
        result = fp.read()
        fp.close()
        return result


    # def _write_pid(self, pid):
    #     manager = PidfileManager(self.__pidfile_name)
    #     manager.write_pid(pid=pid)
    #
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

# Disable these tests on non-POSIX
if os.name != 'posix':
    TestStatusReporter = None
    TestPidfileManager = None
