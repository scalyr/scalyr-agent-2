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
#

from __future__ import absolute_import

from io import open

import os
import mock
import six

from scalyr_agent.test_base import BaseScalyrLogCaptureTestCase

__all__ = [
    'LogCaptureClassTestCase'
]


class LogCaptureClassTestCase(BaseScalyrLogCaptureTestCase):
    """
    Test class which verified BaseScalyrLogCaptureTestCase works correctly.
    """
    def test_assertLogFileContainsAndDoesntContainLineRegex(self):
        # Log files should have been created in setUp()
        self.assertTrue(os.path.isfile(self.agent_log_path))
        self.assertTrue(os.path.isfile(self.agent_debug_log_path))

        # Write some data to the file and verify assertLogFileContainsLineRegex works correctly
        with open(self.agent_log_path, 'w') as fp:
            fp.write(six.text_type('line 1\nline 2\nline 3'))

        # file_path argument explicitly provided
        self.assertLogFileContainsLineRegex(r'line 1', self.agent_log_path)
        self.assertLogFileContainsLineRegex(r'line 2', self.agent_log_path)
        self.assertLogFileContainsLineRegex(r'line \d+', self.agent_log_path)

        # file_path argument not provided, should default to agent log path
        self.assertLogFileContainsLineRegex(r'line 1')
        self.assertLogFileContainsLineRegex(r'line 2')
        self.assertLogFileContainsLineRegex(r'line \d+')

        self.assertRaises(AssertionError, self.assertLogFileContainsLineRegex,
                          r'line 1\nline 2', self.agent_log_path)
        self.assertRaises(AssertionError, self.assertLogFileContainsLineRegex,
                          r'line 4', self.agent_log_path)
        self.assertRaises(AssertionError, self.assertLogFileContainsLineRegex,
                          r'line \d+\d+', self.agent_log_path)

        self.assertLogFileDoesntContainsLineRegex(r'line 1\nline 2', self.agent_log_path)
        self.assertLogFileDoesntContainsLineRegex(r'line 4', self.agent_log_path)
        self.assertLogFileDoesntContainsLineRegex(r'line \d+\d+', self.agent_log_path)

    def test_assertLogFileContainsAndDoesntContainRegex(self):
        # Log files should have been created in setUp()
        self.assertTrue(os.path.isfile(self.agent_log_path))
        self.assertTrue(os.path.isfile(self.agent_debug_log_path))

        # Write some data to the file and verify assertLogFileContainsRegex works correctly
        with open(self.agent_log_path, 'w') as fp:
            fp.write(six.text_type('line 1\nline 2\nline 3'))

        self.assertLogFileContainsRegex(r'line 1\nline 2', self.agent_log_path)
        self.assertLogFileContainsRegex(r'line 1\nline 2\nline 3', self.agent_log_path)
        self.assertLogFileContainsRegex(r'line 1\nline 2\nline \d+', self.agent_log_path)

        self.assertRaises(AssertionError, self.assertLogFileContainsRegex,
                          r'line 4', self.agent_log_path)
        self.assertRaises(AssertionError, self.assertLogFileContainsRegex,
                          r'line 1\nline 3', self.agent_log_path)

        self.assertLogFileDoesntContainsRegex(r'line 4', self.agent_log_path)
        self.assertLogFileDoesntContainsRegex(r'line 1\n line 3', self.agent_log_path)

    @mock.patch('scalyr_agent.test_base.print')
    def tearDown(self, mock_print):
        test_name = self._testMethodName

        # NOTE: We only perform those checks for "test_assertLogFileContainsLineRegex" test to avoid
        # overhead for each test method on this class
        if test_name != 'test_assertLogFileContainsAndDoesntContainLineRegex':
            super(LogCaptureClassTestCase, self).tearDown()
            return

        # Verify directory generated by the test is deleted as part of tearDown cleanup
        # if an assertion has not failed and verify no messages with log paths are printed
        self.assertTrue(os.path.isdir(self.logs_directory))

        self.assertEqual(len(mock_print.call_args_list), 0)

        self._BaseScalyrLogCaptureTestCase__assertion_failed = False
        super(LogCaptureClassTestCase, self).tearDown()

        self.assertFalse(os.path.isdir(self.logs_directory))
        self.assertEqual(len(mock_print.call_args_list), 0)

        # Verify path to the files is printed if the assertion fails
        self._BaseScalyrLogCaptureTestCase__assertion_failed = True
        super(LogCaptureClassTestCase, self).tearDown()

        self.assertEqual(len(mock_print.call_args_list), 2)

        print_message_1 = mock_print.call_args_list[0][0][0]
        print_message_2 = mock_print.call_args_list[1][0][0]

        expected_msg_1 = 'Storing agent log file for test "test_assertLogFile'
        expected_msg_2 = 'Storing agent debug log file for test "test_assertLogFile'

        self.assertTrue(expected_msg_1 in print_message_1)
        self.assertTrue(expected_msg_2 in print_message_2)
