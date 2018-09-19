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
import time

__author__ = 'czerwin@scalyr.com'

import atexit
import os
import shutil
import tempfile
import unittest
import sys

from scalyr_agent.scalyr_client import EventSequencer
from scalyr_agent.line_matcher import LineMatcher
from scalyr_agent.log_processing import LogFileIterator, LogLineSampler, LogLineRedacter, LogFileProcessor, LogMatcher
from scalyr_agent.log_processing import FileSystem
from scalyr_agent import json_lib
from scalyr_agent.json_lib import JsonObject
from scalyr_agent.json_lib import JsonArray
from scalyr_agent.util import md5_digest
from scalyr_agent.configuration import Configuration, BadConfiguration
from scalyr_agent.platform_controller import DefaultPaths

from scalyr_agent.test_base import ScalyrTestCase


class TestLogFileIterator(ScalyrTestCase):
    def setUp(self):
        self.__tempdir = tempfile.mkdtemp()
        self.__file_system = FileSystem()
        self.__path = os.path.join(self.__tempdir, 'text.txt')
        self.__fake_time = 10

        self.write_file(self.__path, '')

        log_config = {'path': self.__path}
        log_config = DEFAULT_CONFIG.parse_log_config(log_config)

        self.log_file = LogFileIterator(self.__path, DEFAULT_CONFIG, log_config, file_system=self.__file_system)
        self.log_file.set_parameters(max_line_length=5, page_size=20)
        self.scan_for_new_bytes()

    def tearDown(self):
        self.log_file.close()
        shutil.rmtree(self.__tempdir)

    def readline(self, time_advance=10):
        self.__fake_time += time_advance

        return self.log_file.readline(current_time=self.__fake_time)

    def mark(self, position, time_advance=10):
        self.__fake_time += time_advance
        self.log_file.mark(position, current_time=self.__fake_time)

    def scan_for_new_bytes(self, time_advance=10):
        self.__fake_time += time_advance
        self.log_file.scan_for_new_bytes(current_time=self.__fake_time)

    def test_initial_scan(self):
        self.append_file(self.__path,
                         'L1\n',
                         'L2\n')

        result = self.readline()

        self.assertEquals(result.line, 'L1\n')

    def test_continue_through_matcher(self):

        log_config = {'path': self.__path, 'lineGroupers': JsonArray(DEFAULT_CONTINUE_THROUGH)}
        log_config = DEFAULT_CONFIG.parse_log_config(log_config)
        matcher = LineMatcher.create_line_matchers(log_config, 100, 60)
        self.log_file.set_line_matcher(matcher)
        self.log_file.set_parameters(100, 100)

        expected = "--multi\n--continue\n--some more\n"
        expected_next = "the end\n"
        self.append_file(self.__path,
                         expected,
                         expected_next)

        self.assertEquals(expected, self.readline().line)
        self.assertEquals(expected_next, self.readline().line)

    def test_continue_past_matcher(self):
        log_config = {'path': self.__path, 'lineGroupers': JsonArray(DEFAULT_CONTINUE_PAST)}
        log_config = DEFAULT_CONFIG.parse_log_config(log_config)
        matcher = LineMatcher.create_line_matchers(log_config, 100, 60)
        self.log_file.set_line_matcher(matcher)
        self.log_file.set_parameters(100, 100)

        expected = "--multi\\\n--continue\\\n--some more\n"
        expected_next = "the end\n"
        self.append_file(self.__path,
                         expected,
                         expected_next)

        self.assertEquals(expected, self.readline().line)
        self.assertEquals(expected_next, self.readline().line)

    def test_halt_before_matcher(self):
        log_config = {'path': self.__path, 'lineGroupers': JsonArray(DEFAULT_HALT_BEFORE)}
        log_config = DEFAULT_CONFIG.parse_log_config(log_config)
        matcher = LineMatcher.create_line_matchers(log_config, 100, 60)
        self.log_file.set_line_matcher(matcher)
        self.log_file.set_parameters(100, 100)

        expected = "--begin\n--continue\n"
        expected_next = "the end\n"
        self.append_file(self.__path,
                         expected, "--end\n",
                         expected_next)

        self.assertEquals(expected, self.readline().line)
        self.assertEquals("--end\n", self.readline().line)
        self.assertEquals(expected_next, self.readline().line)

    def test_halt_with_matcher(self):
        log_config = {'path': self.__path, 'lineGroupers': JsonArray(DEFAULT_HALT_WITH)}
        log_config = DEFAULT_CONFIG.parse_log_config(log_config)
        matcher = LineMatcher.create_line_matchers(log_config, 100, 60)
        self.log_file.set_line_matcher(matcher)
        self.log_file.set_parameters(100, 100)

        expected = "--start\n--continue\n--stop\n"
        expected_next = "the end\n"
        self.append_file(self.__path,
                         expected,
                         expected_next)

        self.assertEquals(expected, self.readline().line)
        self.assertEquals(expected_next, self.readline().line)

    def test_multiple_line_groupers(self):
        log_config = {'path': self.__path,
                      'lineGroupers': JsonArray(DEFAULT_CONTINUE_THROUGH, DEFAULT_CONTINUE_PAST, DEFAULT_HALT_BEFORE,
                                                DEFAULT_HALT_WITH)}
        log_config = DEFAULT_CONFIG.parse_log_config(log_config)
        matcher = LineMatcher.create_line_matchers(log_config, 100, 60)
        self.log_file.set_line_matcher(matcher)
        self.log_file.set_parameters(200, 200)
        expected = ["--multi\n--continue\n--some more\n",
                    "single line\n",
                    "multi\\\n--continue\\\n--some more\n",
                    "single line\n",
                    "--begin\n--continue\n",
                    "--end\n",
                    "--start\n--continue\n--stop\n",
                    "the end\n"]

        self.append_file(self.__path, ''.join(expected))

        for line in expected:
            self.assertEquals(line, self.readline().line)

    def test_multiple_line_grouper_options(self):
        log_config = {'path': self.__path,
                      'lineGroupers': JsonArray( JsonObject({'start': '^--multi', 'continueThrough': "^--", 'continuePast': '\n'}) )
                                       }
        self.assertRaises( BadConfiguration, DEFAULT_CONFIG.parse_log_config, log_config )

    def test_insufficient_line_grouper_options(self):
        log_config = {'path': self.__path,
                      'lineGroupers': JsonArray( JsonObject({'start': '^--multi'}) )
                                       }
        self.assertRaises( BadConfiguration, DEFAULT_CONFIG.parse_log_config, log_config )

    def test_multiple_scans(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n',
                         'L003\n',
                         'L004\n',
                         'L005\n',
                         'L006\n')

        self.assertEquals(self.readline().line, 'L001\n')
        self.assertEquals(self.log_file.page_reads, 1)
        self.assertEquals(self.readline().line, 'L002\n')
        self.assertEquals(self.readline().line, 'L003\n')
        self.assertEquals(self.readline().line, 'L004\n')
        self.assertEquals(self.readline().line, 'L005\n')
        self.assertEquals(self.readline().line, 'L006\n')
        self.assertEquals(self.log_file.page_reads, 2)

    def test_no_more_content(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n')

        self.assertEquals(self.readline().line, 'L001\n')
        self.assertEquals(self.readline().line, 'L002\n')
        self.assertEquals(self.readline().line, '')

    def test_more_bytes_added(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n')

        self.assertEquals(self.readline().line, 'L001\n')
        self.assertEquals(self.readline().line, 'L002\n')
        self.assertEquals(self.readline().line, '')

        self.append_file(self.__path,
                         'L03\n',
                         'L04\n')
        _, first_sequence_number = self.log_file.get_sequence()

        self.scan_for_new_bytes()

        self.assertEquals(self.readline().line, 'L03\n')
        self.assertEquals(self.readline().line, 'L04\n')
        self.assertEquals(self.readline().line, '')

        _, second_sequence_number = self.log_file.get_sequence()
        self.assertTrue(second_sequence_number > first_sequence_number)

    def test_deleted_file(self):
        # Since it cannot keep file handles open when they are deleted, win32 cannot handle this case:
        if sys.platform == 'win32':
            return

        _, first_sequence_number = self.log_file.get_sequence()

        self.append_file(self.__path,
                         'L001\n',
                         'L002\n')
        self.delete_file(self.__path)

        self.scan_for_new_bytes()

        self.assertEquals(self.readline().line, 'L001\n')
        self.assertEquals(self.readline().line, 'L002\n')
        self.assertEquals(self.readline().line, '')
        self.assertFalse(self.log_file.at_end)

        _, second_sequence_number = self.log_file.get_sequence()
        self.assertTrue(second_sequence_number > first_sequence_number)

        self.scan_for_new_bytes(time_advance=60 * 11)
        self.assertTrue(self.log_file.at_end)

    def test_losing_read_access(self):
        # Since it cannot keep file handles open when their permissions are changed, win32 cannot handle this case:
        if sys.platform == 'win32':
            return

        self.append_file(self.__path,
                         'L001\n',
                         'L002\n')
        restore_access = self.remove_read_access()
        os.chmod(self.__tempdir, 0)
        self.scan_for_new_bytes()

        self.assertEquals(self.readline().line, 'L001\n')
        self.assertEquals(self.readline().line, 'L002\n')
        self.assertEquals(self.readline().line, '')
        self.assertFalse(self.log_file.at_end)

        self.scan_for_new_bytes(time_advance=60 * 11)
        self.assertTrue(self.log_file.at_end)
        restore_access()

    def test_rotated_file_with_truncation(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n')

        self.assertEquals(self.readline().line, 'L001\n')
        self.assertEquals(self.readline().line, 'L002\n')
        self.assertEquals(self.readline().line, '')

        _, first_sequence_number = self.log_file.get_sequence()

        self.truncate_file(self.__path)
        self.append_file(self.__path,
                         'L003\n')
        self.scan_for_new_bytes()

        self.assertEquals(self.readline().line, 'L003\n')
        self.assertEquals(self.readline().line, '')

        _, second_sequence_number = self.log_file.get_sequence()
        self.assertTrue(second_sequence_number > first_sequence_number)

    def test_rotating_log_file_with_move(self):
        # Since it cannot keep file handles open when they are deleted/moved, win32 cannot handle this case:
        if sys.platform == 'win32':
            return

        self.append_file(self.__path,
                         'L001\n')

        self.assertEquals(self.readline().line, 'L001\n')
        self.assertEquals(self.readline().line, '')

        _, first_sequence_number = self.log_file.get_sequence()

        self.append_file(self.__path,
                         'L002\n',
                         'L003\n')
        self.move_file(self.__path, self.__path + '.1')
        self.write_file(self.__path,
                        'L004\n',
                        'L005\n')
        self.scan_for_new_bytes()

        self.assertEquals(self.readline().line, 'L002\n')

        _, second_sequence_number = self.log_file.get_sequence()
        self.assertTrue(second_sequence_number > first_sequence_number)

        _, first_sequence_number = self.log_file.get_sequence()
        self.assertEquals(self.readline().line, 'L003\n')
        _, second_sequence_number = self.log_file.get_sequence()
        self.assertTrue(second_sequence_number > first_sequence_number)

        _, first_sequence_number = self.log_file.get_sequence()
        self.assertEquals(self.readline().line, 'L004\n')
        _, second_sequence_number = self.log_file.get_sequence()
        self.assertTrue(second_sequence_number > first_sequence_number)

        self.assertEquals(self.readline().line, 'L005\n')
        self.assertEquals(self.readline().line, '')

        self.mark(self.log_file.tell())
        self.assertEquals(self.log_file.get_open_files_count(), 1)

    def test_rotated_file_with_truncation_and_deletion(self):
        # This tests an old bug that caused us problems in production.  Basically, it tests
        # what happens if you truncate a file while you were in the middle of reading it, with
        # new content after it.
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n',
                         'L003\n',
                         'L004\n',
                         'L005\n',
                         'L006\n',
                         'L007\n',
                         'L008\n')
        self.scan_for_new_bytes()

        self.assertEquals(self.readline().line, 'L001\n')
        self.assertEquals(self.readline().line, 'L002\n')

        self.truncate_file(self.__path)
        self.delete_file(self.__path)
        self.write_file(self.__path,
                        'L009\n',
                        'L010\n',
                        'L011\n',
                        'L012\n')
        self.scan_for_new_bytes()

        self.assertEquals(self.readline().line, 'L003\n')
        self.assertEquals(self.readline().line, 'L004\n')
        self.assertEquals(self.readline().line, 'L009\n')
        self.assertEquals(self.readline().line, 'L010\n')
        self.assertEquals(self.readline().line, 'L011\n')
        self.assertEquals(self.readline().line, 'L012\n')
        self.assertEquals(self.readline().line, '')

    def test_holes_in_file(self):
        # Since it cannot keep file handles open when they are moved/deleted, win32 cannot handle this case:
        if sys.platform == 'win32':
            return

        # This is a more general case of the rotated_file_with_truncation_and_deletion.
        # It essentially creates holes in the virtual file that the __fill_buffer code most correctly
        # deal with.
        # We do this by rotating the log file 3 times.
        # The names of where we rotate the log file to.
        first_portion = os.path.join(self.__tempdir, 'first.txt')
        second_portion = os.path.join(self.__tempdir, 'second.txt')
        third_portion = os.path.join(self.__tempdir, 'third.txt')

        # First rotate.  We need the scan_for_new_bytes to make sure the LogFileIterator notices this file and
        # remembers its file handle.
        self.append_file(self.__path, 'L001\n', 'L002\n')
        self.scan_for_new_bytes()
        self.move_file(self.__path, first_portion)

        self.write_file(self.__path, 'L003\n', 'L004\n')
        self.scan_for_new_bytes()
        self.move_file(self.__path, second_portion)

        self.write_file(self.__path, 'L005\n', 'L006\n')
        self.scan_for_new_bytes()
        self.move_file(self.__path, third_portion)

        self.write_file(self.__path, 'L007\n')

        self.scan_for_new_bytes()
        original_position = self.log_file.tell()

        # Read through massively rotated file and verify all of the parts are there.
        self.assertEquals(self.readline().line, 'L001\n')

        self.assertEquals(self.readline().line, 'L002\n')
        self.assertEquals(self.readline().line, 'L003\n')
        _, first_sequence_number = self.log_file.get_sequence()

        self.assertEquals(self.readline().line, 'L004\n')
        self.assertEquals(self.readline().line, 'L005\n')
        hole_position = self.log_file.tell()
        self.assertEquals(self.readline().line, 'L006\n')
        self.assertEquals(self.readline().line, 'L007\n')
        self.assertEquals(self.readline().line, '')

        # Now we go back to the begin and read it over again, but this time, remove a few of the portions
        # by truncating them.  In particular, we remove the first_portion to test what happens when we seek to
        # an invalid byte offset.  Also, remove_third_portion to test that we correctly jump offset even after
        # a good chunk of data.
        self.truncate_file(first_portion)
        self.truncate_file(third_portion)

        self.log_file.seek(original_position)

        self.assertEquals(self.readline().line, 'L003\n')
        _, second_sequence_number = self.log_file.get_sequence()
        self.assertTrue(second_sequence_number == first_sequence_number)

        self.assertEquals(self.readline().line, 'L004\n')
        self.assertEquals(self.readline().line, 'L007\n')
        self.assertEquals(self.readline().line, '')

        # We should also have the same number of bytes that should have been returned for the entire file.
        self.assertEquals(self.log_file.bytes_between_positions(original_position, self.log_file.tell()), 35)

        # The buffer should hold L003 to L007.  We next test that if we try to seek to a position that should
        # already be in the buffer but isn't because it is a hole, we get the next line.  Also verify that we
        # did really test this case by making sure no new pages were read into cache.
        page_reads = self.log_file.page_reads

        self.log_file.seek(hole_position)
        self.assertEquals(self.readline().line, 'L007\n')
        self.assertEquals(self.readline().line, '')

        self.assertEquals(self.log_file.page_reads, page_reads)

    def test_partial_line(self):
        self.append_file(self.__path, 'L001')
        self.assertEquals(self.readline(time_advance=1).line, '')

        self.scan_for_new_bytes(time_advance=1)
        self.assertEquals(self.readline(time_advance=1).line, '')

        self.scan_for_new_bytes(time_advance=4)
        self.assertEquals(self.readline().line, 'L001')

    def test_set_position_with_valid_mark(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n')

        position = self.log_file.tell()
        self.assertEquals(self.readline().line, 'L001\n')
        self.assertEquals(self.readline().line, 'L002\n')
        _, first_sequence_number = self.log_file.get_sequence()

        self.log_file.seek(position)
        self.assertEquals(self.readline().line, 'L001\n')
        self.assertEquals(self.readline().line, 'L002\n')
        _, second_sequence_number = self.log_file.get_sequence()
        self.assertTrue(second_sequence_number == first_sequence_number)

    def test_reuse_position_object_with_tell(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n')

        position = self.log_file.tell()
        original = position
        self.assertEquals(self.readline().line, 'L001\n')
        position = self.log_file.tell(dest=position)
        self.assertIs(original, position)
        self.assertEquals(self.readline().line, 'L002\n')

        self.log_file.seek(position)
        self.assertEquals(self.readline().line, 'L002\n')

    def test_mark_does_not_move_position(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n',
                         'L003\n')

        self.assertEquals(self.readline().line, 'L001\n')
        self.assertEquals(self.readline().line, 'L002\n')
        position = self.log_file.tell()
        self.mark(self.log_file.tell())

        self.assertEquals(self.readline().line, 'L003\n')

        self.log_file.seek(position)
        self.assertEquals(self.readline().line, 'L003\n')

    def test_set_invalid_position_after_mark(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n')
        position = self.log_file.tell()

        self.assertEquals(self.readline().line, 'L001\n')

        self.mark(self.log_file.tell())

        self.assertEquals(self.readline().line, 'L002\n')

        self.assertRaises(Exception, self.log_file.seek, position)

    def test_checkpoint(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n',
                         'L003\n',
                         'L004\n')

        self.assertEquals(self.readline().line, 'L001\n')
        self.mark(self.log_file.tell())
        self.assertEquals(self.readline().line, 'L002\n')

        saved_checkpoint = self.log_file.get_mark_checkpoint()

        self.assertTrue('sequence_id' in saved_checkpoint)
        self.assertTrue('sequence_number' in saved_checkpoint)

        log_config = {'path': self.__path}
        log_config = DEFAULT_CONFIG.parse_log_config(log_config)
        self.log_file = LogFileIterator(self.__path, DEFAULT_CONFIG, log_config, file_system=self.__file_system,
                                        checkpoint=saved_checkpoint)
        self.log_file.set_parameters(max_line_length=5, page_size=20)

        self.scan_for_new_bytes()
        self.assertEquals(self.readline().line, 'L002\n')
        self.assertEquals(self.readline().line, 'L003\n')
        self.assertEquals(self.readline().line, 'L004\n')

    def test_initial_checkpoint(self):
        self.write_file(self.__path,
                        'L001\n',
                        'L002\n',
                        'L003\n',
                        'L004\n')

        log_config = {'path': self.__path}
        log_config = DEFAULT_CONFIG.parse_log_config(log_config)
        self.log_file = LogFileIterator(self.__path, DEFAULT_CONFIG, log_config, file_system=self.__file_system,
                                        checkpoint=LogFileIterator.create_checkpoint(10))
        self.log_file.set_parameters(max_line_length=5, page_size=20)

        self.scan_for_new_bytes()
        self.assertEquals(self.readline().line, 'L003\n')
        self.assertEquals(self.readline().line, 'L004\n')

    def test_exceeding_maximum_line_length(self):
        self.append_file(self.__path,
                         'L00001\n',
                         'L002\n')
        self.assertEquals(self.readline().line, 'L0000')
        self.assertEquals(self.readline().line, '1\n')
        self.assertEquals(self.readline().line, 'L002\n')

    def test_availabe_bytes(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n',
                         'L003\n',
                         'L004\n')

        self.scan_for_new_bytes()
        self.assertEquals(self.log_file.available, 20L)
        self.assertEquals(self.readline().line, 'L001\n')
        self.assertEquals(self.log_file.available, 15L)
        self.assertEquals(self.readline().line, 'L002\n')
        self.assertEquals(self.readline().line, 'L003\n')
        self.assertEquals(self.readline().line, 'L004\n')
        self.assertEquals(self.log_file.available, 0L)

    def test_skip_to_end(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n',
                         'L003\n',
                         'L004\n',
                         'L005\n',
                         'L006\n')
        self.scan_for_new_bytes()
        _, first_sequence_number = self.log_file.get_sequence()
        self.assertEquals(self.log_file.available, 30L)

        self.assertEquals(self.log_file.advance_to_end(), 30L)
        _, second_sequence_number = self.log_file.get_sequence()
        self.assertEqual(30L, second_sequence_number)

        self.append_file(self.__path,
                         'L007\n',
                         'L008\n')

        self.assertEquals(self.readline().line, 'L007\n')
        self.assertEquals(self.readline().line, 'L008\n')

    def test_skip_to_end_with_buffer(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n',
                         'L003\n')
        self.scan_for_new_bytes()
        self.assertEquals(self.log_file.available, 15L)

        self.assertEquals(self.log_file.advance_to_end(), 15L)

        self.append_file(self.__path,
                         'L004\n',
                         'L005\n')

        self.assertEquals(self.readline().line, 'L004\n')
        self.assertEquals(self.readline().line, 'L005\n')

    def test_move_position_after_skip_to_end(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n',
                         'L003\n')
        self.scan_for_new_bytes()
        position = self.log_file.tell()

        self.assertEquals(self.log_file.available, 15L)

        self.assertEquals(self.log_file.advance_to_end(), 15L)

        self.append_file(self.__path,
                         'L004\n',
                         'L005\n')

        self.assertEquals(self.readline().line, 'L004\n')
        self.assertEquals(self.readline().line, 'L005\n')

        self.log_file.seek(position)
        self.assertEquals(self.readline().line, 'L001\n')

    def test_bytes_between_positions(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n',
                         'L003\n',
                         'L004\n')
        pos1 = self.log_file.tell()
        self.assertEquals(self.readline().line, 'L001\n')
        self.assertEquals(self.readline().line, 'L002\n')
        pos2 = self.log_file.tell()

        self.assertEquals(self.log_file.bytes_between_positions(pos1, pos2), 10)

    def test_scan_for_new_bytes(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n',
                         'L003\n',
                         'L004\n')
        self.log_file.scan_for_new_bytes()
        self.assertEquals(self.log_file.available, 20L)
        self.append_file(self.__path,
                         'L005\n',
                         'L006\n')
        self.log_file.scan_for_new_bytes()
        self.assertEquals(self.log_file.available, 30L)

        self.move_file(self.__path, self.__path + '.1')
        self.write_file(self.__path,
                        'L007\n',
                        'L008\n')
        self.log_file.scan_for_new_bytes()
        self.assertEquals(self.log_file.available, 40L)

    def test_prepare_for_inactivity_closes_old_file_handles(self):
        self.append_file(self.__path, "some lines of text\n")

        open_count = self.log_file.get_open_files_count()
        self.assertEquals(1, open_count)

        modification_time = os.path.getmtime(self.__path)
        modification_time -= DEFAULT_CONFIG.close_old_files_duration_in_seconds + 100
        os.utime(self.__path, (modification_time, modification_time))

        self.log_file.scan_for_new_bytes()
        self.log_file.prepare_for_inactivity()

        open_count = self.log_file.get_open_files_count()
        self.assertEquals(0, open_count)

    def test_last_modification_time(self):
        known_time = time.time()
        os.utime(self.__path, (known_time, known_time))
        self.log_file.scan_for_new_bytes()
        # The numbers might not be perfect because some file systems do not return a mod time with fractional secs.
        self.assertTrue(abs(known_time - self.log_file.last_modification_time) < 1)

    def write_file(self, path, *lines):
        contents = ''.join(lines)
        file_handle = open(path, 'wb')
        file_handle.write(contents)
        file_handle.close()

    def append_file(self, path, *lines):
        contents = ''.join(lines)
        file_handle = open(path, 'ab')
        file_handle.write(contents)
        file_handle.close()

    def delete_file(self, path):
        self.log_file.prepare_for_inactivity()
        os.remove(path)

    def move_file(self, original_path, new_path):
        self.log_file.prepare_for_inactivity()
        os.rename(original_path, new_path)

    def remove_read_access(self):
        # To simulate losing access to the log file, we just disable access to the whole directory.
        # This is a bit of a cheap hack, but just wanted to make sure this test case is covered.
        self.log_file.prepare_for_inactivity()
        os.chmod(self.__tempdir, 0)

        def restore_callback():
            # we just put back all permissions to restore.
            os.chmod(self.__tempdir, 0777)

        return restore_callback

    def truncate_file(self, path):
        file_handle = open(path, 'w')
        file_handle.truncate(0)
        file_handle.close()


class TestLogLineRedactor(ScalyrTestCase):
    def _run_case(self, redactor, line, expected_line, expected_redaction):
        (result_line, redacted) = redactor.process_line(line)
        self.assertEquals(result_line, expected_line)
        self.assertEquals(redacted, expected_redaction)

    def test_basic_redaction(self):
        redactor = LogLineRedacter('/var/fake_log')
        redactor.add_redaction_rule('password', 'fake')

        self._run_case(redactor, "auth=password", "auth=fake", True)
        self._run_case(redactor, "another line password", "another line fake", True)
        self._run_case(redactor, "do not touch", "do not touch", False)

    def test_multiple_redactions_in_line(self):
        redactor = LogLineRedacter('/var/fake_log')
        redactor.add_redaction_rule('password', 'fake')

        self._run_case(redactor, "auth=password foo=password", "auth=fake foo=fake", True)

    def test_regular_expression_redaction(self):
        redactor = LogLineRedacter('/var/fake_log')
        redactor.add_redaction_rule('password=.*', 'password=fake')

        self._run_case(redactor, "login attempt password=czerwin", "login attempt password=fake", True)

    def test_regular_expression_with_capture_group(self):
        redactor = LogLineRedacter('/var/fake_log')
        redactor.add_redaction_rule('secret(.*)=.*', 'secret\\1=fake')

        self._run_case(redactor, "foo secretoption=czerwin", "foo secretoption=fake", True)

    def test_unicode_redactions(self):
        redacter = LogLineRedacter('/var/fake_log')
        # redaction rules are created as unicode, to cause conflict with a utf-8 string
        redacter.add_redaction_rule(u'(.*)', u'bb\\1bb')

        # build the utf8 string
        utf8_string = unichr(8230).encode('utf-8')
        expected = 'bb' + utf8_string + 'bb'

        # go go go
        self._run_case(redacter, utf8_string, expected, True)

    def test_multiple_redactions2(self):
        redactor = LogLineRedacter('/var/fake_log')
        redactor.add_redaction_rule('secret(.*)=.*', 'secret\\1=fake')

        self._run_case(redactor, "foo password=steve secretoption=czerwin", "foo password=steve secretoption=fake",
                       True)
        self._run_case(redactor, "foo password=steve secretoption=czerwin", "foo password=steve secretoption=fake",
                       True)

    def test_customer_case(self):
        redactor = LogLineRedacter('/var/fake_log')
        redactor.add_redaction_rule(
            "(access_token|ccNumber|ccSecurityCode|ccExpirationMonth|ccExpirationYear|pwdField|passwordConfirm|"
            "challengeAnswer|code|taxVat|password[0-9]?|pwd|newpwd[0-9]?Field|currentField|security_answer[0-9]|"
            "tinnumber)=[^&]*", "")

        self._run_case(redactor, "[11/May/2012:16:20:54 -0400] \"GET /api2/profiles/api_contractor?"
                                 "access_token=E|foo&catId=10179&mode=basic HTTP/1.1\" 200 2045",
                       "[11/May/2012:16:20:54 -0400] \"GET /api2/profiles/api_contractor?"
                       "&catId=10179&mode=basic HTTP/1.1\" 200 2045", True)

        self._run_case(redactor, "[11/May/2012:16:20:54 -0400] \"GET /api2/profiles/api_contractor?"
                                 "access_token=E|foo&newpwd5Field=10179&mode=basic HTTP/1.1\" 200 2045",
                       "[11/May/2012:16:20:54 -0400] \"GET /api2/profiles/api_contractor?&&mode=basic"
                       " HTTP/1.1\" 200 2045", True)

    def test_basic_redaction_hash_no_salt(self):
        redactor = LogLineRedacter('/var/fake_log')
        redactor.add_redaction_rule('(password)', '\\H1')

        self._run_case(redactor, "auth=password", "auth={}".format(md5_digest("password")), True)
        self._run_case(
            redactor, "another line password",
            "another line {}".format(md5_digest("password")),
            True
        )

    def test_basic_redaction_hash_with_salt(self):
        redactor = LogLineRedacter('/var/fake_log')
        redactor.add_redaction_rule('(password)', '\\H1', hash_salt="himalayan-salt")

        self._run_case(
            redactor,
            "auth=password",
            "auth={}".format(md5_digest("password" + "himalayan-salt")),
            True
        )
        self._run_case(
            redactor, "another line password",
            "another line {}".format(md5_digest("password" + "himalayan-salt")),
            True
        )

    def test_multiple_redactions_in_line_with_hash(self):
        redactor = LogLineRedacter('/var/fake_log')
        redactor.add_redaction_rule('(password)', '\\H1')

        self._run_case(
            redactor,
            "auth=password foo=password", "auth={} foo={}".format(
                md5_digest("password"), md5_digest("password")),
            True
        )

    def test_single_regular_expression_redaction_with_hash(self):
        redactor = LogLineRedacter('/var/fake_log')
        redactor.add_redaction_rule('secret(.*)=([a-z]+).*', 'secret\\1=\\H2')
        self._run_case(
            redactor,
            "sometext.... secretoption=czerwin",
            "sometext.... secretoption={}".format(md5_digest("czerwin")),
            True
        )

    def test_multiple_regular_expression_redaction_with_hash_single_group(self):
        redactor = LogLineRedacter('/var/fake_log')
        redactor.add_redaction_rule('secret(.*?)=([a-z]+\s?)', 'secret\\1=\\H2')
        self._run_case(
            redactor,
            "sometext.... secretoption=czerwin moretextsecretbar=xxx andsecret123=saurabh",
            "sometext.... secretoption=%smoretextsecretbar=%sandsecret123=%s" % (
                md5_digest("czerwin "),
                md5_digest("xxx "),
                md5_digest("saurabh"),
            ),
            True
        )

    def test_multiple_regular_expression_redaction_with_hash_single_group_order_flipped(self):
        redactor = LogLineRedacter('/var/fake_log')
        redactor.add_redaction_rule('secret(.*?)=([a-z]+\s?)', 'secret\\2=\\H1')
        self._run_case(
            redactor,
            "sometext.... secretoption=czerwin andsecret123=saurabh",
            "sometext.... secretczerwin =%sandsecretsaurabh=%s" % (
                md5_digest("option"),
                md5_digest("123"),
            ),
            True
        )

    def test_single_regular_expression_redaction_with_hash_no_indicator(self):
        redactor = LogLineRedacter('/var/fake_log')
        redactor.add_redaction_rule(
            'secret(.*)=([a-z]+).*', 'secret\\1=\\2')
        self._run_case(
            redactor,
            "sometext.... secretoption=czerwin",
            "sometext.... secretoption=czerwin",
            True
        )

    def test_basic_group_non_hash_case(self):
        redactor = LogLineRedacter('/var/fake_log')
        redactor.add_redaction_rule('userInfo=([^ ]+) [^ ]+', 'userInfo=\\1')
        self._run_case(
            redactor,
            "userInfo=saurabh abcd1234 ",
            "userInfo=saurabh ",
            True
        )

    def test_basic_group_hash_case(self):
        redactor = LogLineRedacter('/var/fake_log')
        redactor.add_redaction_rule('userInfo=([^ ]+) [^ ]+', 'userInfo=\\H1')
        self._run_case(
            redactor,
            "userInfo=saurabh abcd1234",
            "userInfo={}".format(md5_digest("saurabh")),
            True
        )


class TestLogLineSampler(ScalyrTestCase):
    class TestableLogLineSampler(LogLineSampler):
        """
        A subclass of LogLineSampler that allows us to fix the generated random numbers to help with testing.
        """

        def __init__(self):
            super(TestLogLineSampler.TestableLogLineSampler, self).__init__('/fakefile')
            self.__pending_numbers = []

        def _get_next_random(self):
            if len(self.__pending_numbers) > 0:
                return self.__pending_numbers.pop(0)
            else:
                return 0

        def insert_next_number(self, random_number):
            self.__pending_numbers.append(random_number)

    def setUp(self):
        self.sampler = TestLogLineSampler.TestableLogLineSampler()

    def test_no_sampling_rules(self):
        sampler = self.sampler

        self.assertEquals(sampler.process_line('One line\n'), 1.0)

    def test_all_pass_rule(self):
        sampler = self.sampler
        sampler.add_rule('INFO', 1.0)

        self.assertEquals(sampler.process_line('INFO Here is a line\n'), 1.0)

    def test_no_pass_rule(self):
        sampler = self.sampler
        sampler.add_rule('INFO', 0.0)

        self.assertTrue(sampler.process_line('INFO Here is a line\n') is None)

    def test_multiple_rules(self):
        sampler = self.sampler
        sampler.add_rule('ERROR', 1.0)
        sampler.add_rule('INFO', 0.0)

        self.assertTrue(sampler.process_line('INFO Here is a line\n') is None)
        self.assertEquals(sampler.process_line('Error Another\n'), 1.0)
        self.assertEquals(sampler.process_line('One more\n'), 1.0)

    def test_rule_with_sampling(self):
        sampler = self.sampler

        sampler.add_rule('INFO', 0.2)
        sampler.insert_next_number(0.4)
        sampler.insert_next_number(0.1)

        self.assertTrue(sampler.process_line('INFO Another\n') is None)
        self.assertEquals(sampler.process_line('INFO Here is a line\n'), 0.2)


class TestLogFileProcessor(ScalyrTestCase):
    def setUp(self):
        self.__tempdir = tempfile.mkdtemp()
        self.__file_system = FileSystem()
        self.__path = os.path.join(self.__tempdir, 'text.txt')
        self.__fake_time = 10
        self.log_processor = self._create_processor()

    def _create_processor(self, close_when_staleness_exceeds=None):
        # Create the processor to test.  We have it do one scan of an empty
        # file so that when we next append lines to it, it will notice it.
        # For now, we create one that does not have any log attributes and only
        # counts the bytes of events messages as the cost.
        self.write_file(self.__path, '')
        log_config = {'path': self.__path}
        log_config = DEFAULT_CONFIG.parse_log_config(log_config)
        log_processor = LogFileProcessor(self.__path, DEFAULT_CONFIG, log_config, file_system=self.__file_system,
                                         log_attributes={}, close_when_staleness_exceeds=close_when_staleness_exceeds)
        (completion_callback, buffer_full) = log_processor.perform_processing(
            TestLogFileProcessor.TestAddEventsRequest(), current_time=self.__fake_time)
        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))
        return log_processor

    def test_basic_usage(self):
        log_processor = self.log_processor
        self.append_file(self.__path, 'First line\nSecond line\n')

        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = log_processor.perform_processing(
            events, current_time=self.__fake_time)

        self.assertEquals(len(events.threads), 1)

        status = log_processor.generate_status()
        self.assertEquals(23L, status.total_bytes_pending)
        self.assertEquals(0L, status.total_bytes_copied)

        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))
        self.assertEquals(2, events.total_events())
        self.assertEquals(events.get_message(0), 'First line\n')
        self.assertEquals(events.get_message(1), 'Second line\n')

        status = log_processor.generate_status()
        self.assertEquals(0L, status.total_bytes_pending)
        self.assertEquals(23L, status.total_bytes_copied)

        # Add some more text to make sure it appears.
        self.append_file(self.__path, 'Third line\n')

        log_processor.scan_for_new_bytes(current_time=self.__fake_time)

        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = log_processor.perform_processing(events, current_time=self.__fake_time)

        status = log_processor.generate_status()
        self.assertEquals(11L, status.total_bytes_pending)
        self.assertEquals(23L, status.total_bytes_copied)

        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))
        self.assertEquals(events.get_message(0), 'Third line\n')

        status = log_processor.generate_status()
        self.assertEquals(0L, status.total_bytes_pending)
        self.assertEquals(34L, status.total_bytes_copied)

    def test_max_log_offset_size_within_max_log_offset_size_no_checkpoint(self):
        # with no checkpoint, the LogFileProcessor should use max_log_offset_size
        # as the maximum readback distance.  This test checks we log messages
        # within that size
        extra = {'max_log_offset_size': 20,
                 'max_existing_log_offset_size': 10}

        config = _create_configuration(extra)

        log_config = {'path': self.__path}
        self._set_new_log_processor(config, log_config, None)
        self.log_processor.set_max_log_offset_size(20)

        expected = "a string of 20bytes\n"
        self.append_file(self.__path, expected)

        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = self.log_processor.perform_processing(
            events, current_time=self.__fake_time)

        self.assertEquals(1, events.total_events())
        self.assertEquals(expected, events.get_message(0))

    def test_max_log_offset_size_over_max_log_offset_size_no_checkpoint(self):
        # with no checkpoint, the LogFileProcessor should use max_log_offset_size
        # as the maximum readback distance. This test checks we skip to the end of
        # the file if the max_log_offset_size is exceeded
        extra = {'max_log_offset_size': 20,
                 'max_existing_log_offset_size': 30}
        config = _create_configuration(extra)

        log_config = {'path': self.__path}
        self._set_new_log_processor(config, log_config)
        self.log_processor.set_max_log_offset_size(20)

        expected = "a string of 21 bytes\n"
        self.append_file(self.__path, expected)

        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = self.log_processor.perform_processing(
            events, current_time=self.__fake_time)

        self.assertEquals(0, events.total_events())

    def test_max_log_offset_size_within_max_log_offset_size_no_pending_files(self):
        # If a checkpoint doesn't contain any pending files, then we haven't seen
        # this file before and, the LogFileProcessor should use max_log_offset_size
        # as the maximum readback distance.  This test checks we log messages
        # within that size
        extra = {'max_log_offset_size': 20,
                 'max_existing_log_offset_size': 10}

        config = _create_configuration(extra)

        log_config = {'path': self.__path}

        checkpoint = {'initial_position': 0}

        self._set_new_log_processor(config, log_config, checkpoint)
        self.log_processor.set_max_log_offset_size(20)

        expected = "a string of 20bytes\n"
        self.append_file(self.__path, expected)

        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = self.log_processor.perform_processing(
            events, current_time=self.__fake_time)

        self.assertEquals(1, events.total_events())
        self.assertEquals(expected, events.get_message(0))

    def test_max_log_offset_size_over_max_log_offset_size_no_pending_files(self):
        # If a checkpoint doesn't contain any pending files, then we haven't seen
        # this file before and, the LogFileProcessor should use max_log_offset_size
        # as the maximum readback distance.  This test checks we skip to the end
        # of the file if max_log_offset_size is exceeded
        extra = {'max_log_offset_size': 20,
                 'max_existing_log_offset_size': 30}
        config = _create_configuration(extra)

        log_config = {'path': self.__path}
        checkpoint = {'initial_position': 0}
        self._set_new_log_processor(config, log_config, checkpoint)
        self.log_processor.set_max_log_offset_size(20)

        expected = "a string of 21 bytes\n"
        self.append_file(self.__path, expected)

        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = self.log_processor.perform_processing(
            events, current_time=self.__fake_time)

        self.assertEquals(0, events.total_events())

    def test_max_existing_log_offset_size_within_max_log_offset_size(self):
        # If a checkpoint contains pending files, then we have seen
        # this file before and, the LogFileProcessor should use max_existing_log_offset_size
        # as the maximum readback distance.  This test checks we log messages within
        # that size
        self.append_file(self.__path, "some random bytes\n")
        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = self.log_processor.perform_processing(
            events, current_time=self.__fake_time)
        self.assertEquals(1, events.total_events())

        checkpoint = self.log_processor.get_checkpoint()

        extra = {'max_log_offset_size': 10,  # set to low value so test will fail if this is used
                 'max_existing_log_offset_size': 20}
        config = _create_configuration(extra)

        log_config = {'path': self.__path}

        self._set_new_log_processor(config, log_config, checkpoint)

        expected = "a string of 20bytes\n"
        self.append_file(self.__path, expected)
        self.log_processor.scan_for_new_bytes()

        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = self.log_processor.perform_processing(
            events, current_time=self.__fake_time)

        self.assertEquals(1, events.total_events())
        self.assertEquals(expected, events.get_message(0))

    def test_max_existing_log_offset_size_over_max_existing_log_offset_size(self):
        # If a checkpoint contains pending files, then we have seen
        # this file before and, the LogFileProcessor should use max_existing_log_offset_size
        # as the maximum readback distance.  This test checks we skip to the end
        # of the file if max_log_offset_size is exceeded
        self.append_file(self.__path, "some random bytes\n")
        self.log_processor.scan_for_new_bytes()
        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = self.log_processor.perform_processing(
            events, current_time=self.__fake_time)
        self.assertEquals(1, events.total_events())

        checkpoint = self.log_processor.get_checkpoint()

        extra = {'max_log_offset_size': 100,  # set to high value to test will fail if this is used
                 'max_existing_log_offset_size': 20}
        config = _create_configuration(extra)

        log_config = {'path': self.__path}

        self._set_new_log_processor(config, log_config, checkpoint)

        expected = "a string of 21 bytes\n"
        self.append_file(self.__path, expected)
        self.log_processor.scan_for_new_bytes()

        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = self.log_processor.perform_processing(
            events, current_time=self.__fake_time)

        self.assertEquals(0, events.total_events())

    def test_max_log_offset_size_set_to_max_existing_log_offset_size_after_perform_processing(self):
        extra = {'max_log_offset_size': 20,
                 'max_existing_log_offset_size': 30}

        config = _create_configuration(extra)

        log_config = {'path': self.__path}
        self._set_new_log_processor(config, log_config, checkpoint=None)
        self.log_processor.set_max_log_offset_size(20)

        expected = "a string of 20bytes\n"
        self.append_file(self.__path, expected)

        self.log_processor.set_max_log_offset_size(extra['max_log_offset_size'])
        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = self.log_processor.perform_processing(
            events, current_time=self.__fake_time)

        self.assertEquals(1, events.total_events())
        self.assertEquals(expected, events.get_message(0))

        expected = "a string of almost 30 bytes\n"
        self.append_file(self.__path, expected)
        self.log_processor.scan_for_new_bytes()

        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = self.log_processor.perform_processing(
            events, current_time=self.__fake_time)

        self.assertEquals(1, events.total_events())
        self.assertEquals(expected, events.get_message(0))

    def test_fail_and_retry(self):
        log_processor = self.log_processor
        self.append_file(self.__path, 'First line\nSecond line\n')

        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = log_processor.perform_processing(
            events, current_time=self.__fake_time)

        self.assertEquals(2, events.total_events())
        self.assertEquals(events.get_message(0), 'First line\n')
        self.assertEquals(events.get_message(1), 'Second line\n')

        self.assertFalse(completion_callback(LogFileProcessor.FAIL_AND_RETRY))

        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = log_processor.perform_processing(events, current_time=self.__fake_time)

        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))
        self.assertEquals(2, events.total_events())
        self.assertEquals(events.get_message(0), 'First line\n')
        self.assertEquals(events.get_message(1), 'Second line\n')

    def test_fail_and_drop(self):
        log_processor = self.log_processor
        self.append_file(self.__path, 'First line\nSecond line\n')

        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = log_processor.perform_processing(
            events, current_time=self.__fake_time)

        self.assertEquals(2, events.total_events())
        self.assertEquals(events.get_message(0), 'First line\n')
        self.assertEquals(events.get_message(1), 'Second line\n')

        self.assertFalse(completion_callback(LogFileProcessor.FAIL_AND_DROP))

        # Add some more text to make sure it appears.
        self.append_file(self.__path, 'Third line\n')

        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = log_processor.perform_processing(events, current_time=self.__fake_time)

        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))
        self.assertEquals(1, events.total_events())
        self.assertEquals(events.get_message(0), 'Third line\n')

    def _set_new_log_processor(self, config, log_config, checkpoint=None):
        # create a new log processer and do an initial scan, because we need a line grouper
        log_config = config.parse_log_config(log_config)
        self.log_processor = LogFileProcessor(self.__path, config, log_config, file_system=self.__file_system,
                                              log_attributes={}, checkpoint=checkpoint)
        self.write_file(self.__path, '')
        (completion_callback, buffer_full) = self.log_processor.perform_processing(
            TestLogFileProcessor.TestAddEventsRequest(), current_time=self.__fake_time)
        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))

    def test_grouping_rules(self):
        log_config = {'path': self.__path, 'lineGroupers': JsonArray(DEFAULT_CONTINUE_THROUGH)}
        self._set_new_log_processor(DEFAULT_CONFIG, log_config)
        expected = "--multi\n--continue\n--some more\n"
        last_line = "the end\n"

        self.append_file(self.__path, expected + last_line)

        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = self.log_processor.perform_processing(events,
                                                                                   current_time=self.__fake_time)

        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))
        self.assertEquals(expected, events.get_message(0))

    def test_grouping_and_sampling_rules(self):
        log_config = {'path': self.__path, 'lineGroupers': JsonArray(DEFAULT_CONTINUE_THROUGH)}
        self._set_new_log_processor(DEFAULT_CONFIG, log_config)
        expected = "--multi\n--continue\n--some more\n"
        last_line = "the end\n"

        # pass any line that has continue and drop any other lines
        self.log_processor.add_sampler('continue', 1)
        self.log_processor.add_sampler('.*', 0)

        self.append_file(self.__path, expected + last_line)

        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = self.log_processor.perform_processing(events,
                                                                                   current_time=self.__fake_time)

        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))
        self.assertEquals(expected, events.get_message(0))

    def test_sampling_rule(self):
        log_processor = self.log_processor
        log_processor.add_sampler('INFO', 0)
        log_processor.add_sampler('ERROR', 1)

        self.append_file(self.__path, 'INFO First line\nERROR Second line\n')

        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = log_processor.perform_processing(events, current_time=self.__fake_time)

        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))
        self.assertEquals(events.get_message(0), 'ERROR Second line\n')

    def test_redaction_rule(self):
        log_processor = self.log_processor
        log_processor.add_redacter('password=[^&]+', 'password=foo')

        self.append_file(self.__path, 'GET /foo&password=FakePassword&start=true\n')

        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = log_processor.perform_processing(events, current_time=self.__fake_time)

        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))
        self.assertEquals(events.get_message(0), 'GET /foo&password=foo&start=true\n')

    def test_redacting_utf8(self):

        # build this manually following a similar process to the main agent, because this will create
        # redaction rules that are unicode strings
        path = self.__path
        extra = {'logs': [
            {
                'path': path,
                'redaction_rules': [{'match_expression': 'aa(.*)aa', 'replacement': 'bb\\1bb'}]
            }
        ]
        }

        config = _create_configuration(extra)
        log_config = {}
        for entry in config.log_configs:
            if entry['path'] == path:
                log_config = entry.copy()

        log_config = config.parse_log_config(log_config)
        log_processor = LogFileProcessor(path, config, log_config, file_system=self.__file_system)
        for rule in log_config['redaction_rules']:
            log_processor.add_redacter(rule['match_expression'], rule['replacement'])
        log_processor.perform_processing(TestLogFileProcessor.TestAddEventsRequest(), current_time=self.__fake_time)

        # create a utf8 string that will cause conflict when matched/replaced against a unicode string
        utf8_string = (u'aa' + unichr(8230) + u'aa').encode("utf-8")
        self.append_file(self.__path, utf8_string + "\n")

        # read the log
        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = log_processor.perform_processing(events, current_time=self.__fake_time)

        # make sure everything is good
        expected = ('bb' + unichr(8230) + 'bb\n').encode("utf-8")
        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))
        self.assertEquals(events.get_message(0), expected)

    def test_signals_deletion(self):
        log_processor = self.log_processor

        # Delete the file.
        os.remove(self.__path)

        # We won't signal that the file processor should be deleted until 10 mins have passed.
        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = log_processor.perform_processing(events, current_time=self.__fake_time)

        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))
        self.assertEquals(0, events.total_events())

        self.__fake_time += 9 * 60
        (completion_callback, buffer_full) = log_processor.perform_processing(events, current_time=self.__fake_time)

        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))

        self.__fake_time += 62
        (completion_callback, buffer_full) = log_processor.perform_processing(events, current_time=self.__fake_time)

        self.assertTrue(completion_callback(LogFileProcessor.SUCCESS))

    def test_signals_deletion_due_to_staleness(self):
        log_processor = self._create_processor(close_when_staleness_exceeds=300)

        # Have to manually set the modification time to the fake time so we are comparing apples to apples.
        os.utime(self.__path, (self.__fake_time, self.__fake_time))

        # The processor won't signal it is ready to be removed until 5 mins have passed.
        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = log_processor.perform_processing(events, current_time=self.__fake_time)

        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))
        self.assertEquals(0, events.total_events())

        self.__fake_time += 4 * 60
        (completion_callback, buffer_full) = log_processor.perform_processing(events, current_time=self.__fake_time)

        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))

        self.__fake_time += 62
        (completion_callback, buffer_full) = log_processor.perform_processing(events, current_time=self.__fake_time)

        self.assertTrue(completion_callback(LogFileProcessor.SUCCESS))

    def test_log_attributes(self):
        vals = {'path': self.__path, 'attributes': JsonObject({'host': 'scalyr-1'})}
        log_config = DEFAULT_CONFIG.parse_log_config(vals)
        log_processor = LogFileProcessor(self.__path, DEFAULT_CONFIG, log_config, file_system=self.__file_system,
                                         log_attributes=vals['attributes'])
        log_processor.perform_processing(TestLogFileProcessor.TestAddEventsRequest(), current_time=self.__fake_time)

        self.append_file(self.__path, 'First line\nSecond line\n')

        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = log_processor.perform_processing(events, current_time=self.__fake_time)

        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))
        self.assertEquals(events.total_events(), 2)
        self.assertEquals('scalyr-1', events.events[0].attrs['host'])
        self.assertEquals('scalyr-1', events.events[1].attrs['host'])

    def test_unique_id(self):
        first_thread_id = LogFileProcessor.generate_unique_thread_id()
        self.assertTrue(first_thread_id.startswith('log_'))
        sequence = int(first_thread_id[4:])
        self.assertTrue(sequence > 0)
        self.assertEquals(first_thread_id, 'log_%d' % sequence)
        self.assertEquals(LogFileProcessor.generate_unique_thread_id(), 'log_%d' % (sequence + 1))

    def test_thread_id_fails_to_be_added(self):
        log_processor = self.log_processor
        self.append_file(self.__path, 'First line\nSecond line\n')

        # Make sure if adding the thread id in fails, then unread the lines and reset everything to normal.
        # We can see if it is normal by making sure the lines are read in the next successful call.
        events = TestLogFileProcessor.TestAddEventsRequest(thread_limit=0)
        (completion_callback, buffer_full) = log_processor.perform_processing(
            events, current_time=self.__fake_time)

        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))
        self.assertEquals(0, events.total_events())
        self.assertEquals(len(events.threads), 0)

        # Now have a succuessful call and make sure we get the lines.
        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = log_processor.perform_processing(
            events, current_time=self.__fake_time)

        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))
        self.assertEquals(2, events.total_events())
        self.assertEquals(events.get_message(0), 'First line\n')
        self.assertEquals(events.get_message(1), 'Second line\n')
        self.assertEquals(len(events.threads), 1)

    def test_sequence_id_and_number(self):
        log_processor = self.log_processor
        self.append_file(self.__path, 'First line\n')

        events = TestLogFileProcessor.TestAddEventsRequest()

        (completion_callback, buffer_full) = log_processor.perform_processing(
            events, current_time=self.__fake_time)

        self.assertEquals(1, events.total_events())
        first_sid, first_sn, sd = events.get_sequence(0)

        self.assertTrue(first_sid != None)
        self.assertTrue(first_sn != None)
        self.assertEquals(None, sd)

    def test_sequence_delta(self):
        log_processor = self.log_processor
        second_line = 'second line\n'
        expected_delta = len(second_line)
        self.append_file(self.__path, 'First line\n')
        self.append_file(self.__path, second_line)

        events = TestLogFileProcessor.TestAddEventsRequest()

        (completion_callback, buffer_full) = log_processor.perform_processing(
            events, current_time=self.__fake_time)

        self.assertEquals(2, events.total_events())
        first_sid, first_sn, sd = events.get_sequence(0)

        second_sid, second_sn, sd = events.get_sequence(1)
        self.assertEquals(None, second_sid)
        self.assertEquals(None, second_sn)
        self.assertEquals(expected_delta, sd)

    def test_sequence_reset(self):
        config = _create_configuration({'max_sequence_number': 20})

        log_config = {'path': self.__path}
        log_config = config.parse_log_config(log_config)

        log_processor = LogFileProcessor(self.__path, config, log_config, file_system=self.__file_system,
                                         log_attributes={})
        self.write_file(self.__path, '')
        (completion_callback, buffer_full) = log_processor.perform_processing(
            TestLogFileProcessor.TestAddEventsRequest(), current_time=self.__fake_time)
        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))

        first_line = 'the first line\n'
        second_line = 'second line\n'

        self.append_file(self.__path, first_line)
        self.append_file(self.__path, second_line)
        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = log_processor.perform_processing(
            events, current_time=self.__fake_time)
        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))

        self.assertEquals(2, events.total_events())

        first_sid, _, _ = events.get_sequence(0)

        third_line = 'third line\n'
        self.append_file(self.__path, third_line)

        log_processor.scan_for_new_bytes(current_time=self.__fake_time)

        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = log_processor.perform_processing(
            events, current_time=self.__fake_time)
        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))

        self.assertEquals(1, events.total_events())

        third_sid, third_sn, third_sd = events.get_sequence(0)

        self.assertNotEqual(first_sid, third_sid)
        self.assertNotEqual(None, third_sid)
        self.assertNotEqual(None, third_sn)
        self.assertEqual(None, third_sd)

    def test_sequence_id_is_string(self):
        # test if UUID is a string, to make sure it can be handled by json
        log_processor = self.log_processor
        self.append_file(self.__path, 'First line\n')

        events = TestLogFileProcessor.TestAddEventsRequest()

        (completion_callback, buffer_full) = log_processor.perform_processing(
            events, current_time=self.__fake_time)

        self.assertEquals(1, events.total_events())
        first_sid, _, _ = events.get_sequence(0)
        self.assertTrue(isinstance(first_sid, basestring))

    def write_file(self, path, *lines):
        contents = ''.join(lines)
        file_handle = open(path, 'wb')
        file_handle.write(contents)
        file_handle.close()

    def append_file(self, path, *lines):
        contents = ''.join(lines)
        file_handle = open(path, 'ab')
        file_handle.write(contents)
        file_handle.close()

    class TestAddEventsRequest(object):
        def __init__(self, limit=10, thread_limit=10):
            self.events = []
            self.__limit = limit
            self.__thread_limit = thread_limit
            self.threads = {}
            self.__event_sequencer = EventSequencer()

        def add_event(self, event, timestamp=None, sequence_id=None, sequence_number=None):
            if len(self.events) < self.__limit:
                self.__event_sequencer.add_sequence_fields(event, sequence_id, sequence_number)
                self.events.append(event)
                return True
            else:
                return False

        def position(self):
            return [len(self.events), dict(self.threads)]

        def set_position(self, position):
            self.events = self.events[0:position[0]]
            self.threads = position[1]

        def add_thread(self, thread_id, thread_name):
            if self.__thread_limit == len(self.threads):
                return False
            self.threads[thread_id] = thread_name
            return True

        def get_message(self, index):
            """Returns the message field from an events object."""
            return self.events[index].message

        def get_sequence(self, index):
            return (self.events[index].sequence_id, self.events[index].sequence_number,
                    self.events[index].sequence_number_delta)

        def total_events(self):
            return len(self.events)

        def increment_timing_data(self, **key_values):
            pass


class TestLogMatcher(ScalyrTestCase):
    def setUp(self):
        self.__config = _create_configuration()

        self.__tempdir = tempfile.mkdtemp()
        self.__file_system = FileSystem()
        self.__path_one = os.path.join(self.__tempdir, 'text.txt')
        self.__path_two = os.path.join(self.__tempdir, 'text_two.txt')
        self.__glob_one = os.path.join(self.__tempdir, '*.txt')
        self.__glob_two = os.path.join(self.__tempdir, '*two.txt')

        self._create_file(self.__path_one)
        self._create_file(self.__path_two)

        self.__fake_time = 10

    def test_matches_glob(self):
        matcher = LogMatcher(self.__config, self._create_log_config(self.__glob_one))
        processors = matcher.find_matches(dict(), dict())
        self.assertEquals(len(processors), 2)

        self._close_processors(processors)

    def test_matches_restricted_glob(self):
        matcher = LogMatcher(self.__config, self._create_log_config(self.__glob_two))
        processors = matcher.find_matches(dict(), dict())
        self.assertEquals(len(processors), 1)

        self._close_processors(processors)

    def test_ignores_stale_file(self):
        staleness_threshold = 300  # 5 mins
        current_time = time.time()
        stale_time = current_time - staleness_threshold - 10

        self._set_mod_date(self.__path_one, current_time)
        self._set_mod_date(self.__path_two, stale_time)

        matcher = LogMatcher(self.__config, self._create_log_config(self.__glob_one, ignore_stale_files=True,
                                                                    staleness_threshold_secs=staleness_threshold))
        processors = matcher.find_matches(dict(), dict())
        self.assertEquals(len(processors), 1)

        self._close_processors(processors)

    def test_rename_string_basename(self):
        config = self._create_log_config(self.__path_one)
        config['rename_logfile'] = "/scalyr/test/$BASENAME"

        matcher = LogMatcher(self.__config, config)

        processors = matcher.find_matches(dict(), dict())
        self.assertEquals(len(processors), 1)

        attrs = processors[0]._LogFileProcessor__base_event.attrs

        self.assertEquals("/scalyr/test/text.txt", attrs['logfile'])
        self.assertEquals(self.__path_one, attrs['original_file'])

    def test_rename_string_basename_no_ext(self):
        config = self._create_log_config(self.__path_one)
        config['rename_logfile'] = "/scalyr/test/$BASENAME_NO_EXT.huzzah"

        matcher = LogMatcher(self.__config, config)

        processors = matcher.find_matches(dict(), dict())
        self.assertEquals(len(processors), 1)

        attrs = processors[0]._LogFileProcessor__base_event.attrs

        self.assertEquals("/scalyr/test/text.huzzah", attrs['logfile'])
        self.assertEquals(self.__path_one, attrs['original_file'])

    def test_rename_string_path(self):
        config = self._create_log_config(self.__path_one)
        config['rename_logfile'] = "/scalyr/test/$PATH2/$PATH1/log.log"

        path = self.__path_one.split(os.sep)

        matcher = LogMatcher(self.__config, config)

        processors = matcher.find_matches(dict(), dict())
        self.assertEquals(len(processors), 1)

        attrs = processors[0]._LogFileProcessor__base_event.attrs

        self.assertEquals("/scalyr/test/%s/%s/log.log" % (path[2], path[1]), attrs['logfile'])
        self.assertEquals(self.__path_one, attrs['original_file'])

    def test_rename_string_invalid_path(self):
        config = self._create_log_config(self.__path_one)
        config['rename_logfile'] = "/scalyr/test/$PATH2/$PATH10/log.log"

        path = self.__path_one.split(os.sep)

        matcher = LogMatcher(self.__config, config)

        processors = matcher.find_matches(dict(), dict())
        self.assertEquals(len(processors), 1)

        attrs = processors[0]._LogFileProcessor__base_event.attrs

        self.assertEquals(self.__path_one, attrs['logfile'])
        self.assertFalse('original_file' in attrs)

    def test_rename_regex(self):
        config = self._create_log_config(self.__path_one)
        config['rename_logfile'] = JsonObject(
            {
                'match': '/(.*)/.*/(.*)',
                'replacement': '/scalyr/test/\\1/\\2'
            }
        )

        matcher = LogMatcher(self.__config, config)

        processors = matcher.find_matches(dict(), dict())
        self.assertEquals(len(processors), 1)

        attrs = processors[0]._LogFileProcessor__base_event.attrs

        # the temp directory is auto-generated, so it's not possible to
        # assert the actual path, we can however match the pre-folder and file name

        self.assertEquals(
            "text.txt", attrs['logfile'].split("/")[-1]
        )

        self.assertEqual(
            ["scalyr", "test"],
            attrs['logfile'].split("/")[1:3]
        )

        self.assertEquals(self.__path_one, attrs['original_file'])

    def test_rename_regex_invalid_match(self):
        config = self._create_log_config(self.__path_one)
        config['rename_logfile'] = JsonObject({'match': '/(.*)/.*/(.*[)', 'replacement': '/scalyr/test/\\1/\\2'})

        matcher = LogMatcher(self.__config, config)

        processors = matcher.find_matches(dict(), dict())
        self.assertEquals(len(processors), 1)

        attrs = processors[0]._LogFileProcessor__base_event.attrs

        self.assertEquals(self.__path_one, attrs['logfile'])
        self.assertFalse('original_file' in attrs)

    def test_rename_regex_invalid_replacement(self):
        config = self._create_log_config(self.__path_one)
        config['rename_logfile'] = JsonObject({'match': '/(.*)/.*/(.*)', 'replacement': '/scalyr/test/\\3/\\2'})

        matcher = LogMatcher(self.__config, config)

        processors = matcher.find_matches(dict(), dict())
        self.assertEquals(len(processors), 1)

        attrs = processors[0]._LogFileProcessor__base_event.attrs

        self.assertEquals(self.__path_one, attrs['logfile'])
        self.assertFalse('original_file' in attrs)

    def test_rename_regex_empty(self):
        config = self._create_log_config(self.__path_one)

        matcher = LogMatcher(self.__config, config)

        processors = matcher.find_matches(dict(), dict())
        self.assertEquals(len(processors), 1)

        attrs = processors[0]._LogFileProcessor__base_event.attrs

        self.assertEquals(self.__path_one, attrs['logfile'])
        self.assertFalse('original_file' in attrs)

    def _close_processors(self, processors):
        for x in processors:
            x.close()

    def _set_mod_date(self, file_path, mod_time):
        os.utime(file_path, (mod_time, mod_time))

    def _create_file(self, file_path):
        fp = open(file_path, 'w')
        fp.close()

    def _create_log_config(self, path, ignore_stale_files=False, staleness_threshold_secs=None):
        return dict(
            path=path, attributes=dict(), lineGroupers=[], redaction_rules=[], sampling_rules=[],
            exclude=[], ignore_stale_files=ignore_stale_files,
            staleness_threshold_secs=staleness_threshold_secs
        )


def _create_configuration(extra=None):
    """Creates a blank configuration file with default values for testing.

    @return: The configuration object
    @rtype: Configuration
    """
    config_dir = tempfile.mkdtemp()
    config_file = os.path.join(config_dir, 'agentConfig.json')
    config_fragments_dir = os.path.join(config_dir, 'configs.d')
    os.makedirs(config_fragments_dir)

    fp = open(config_file, 'w')
    fp.write(json_lib.serialize(JsonObject(extra, api_key='fake')))
    fp.close()

    default_paths = DefaultPaths('/var/log/scalyr-agent-2', '/etc/scalyr-agent-2/agent.json',
                                 '/var/lib/scalyr-agent-2')

    config = Configuration(config_file, default_paths)
    config.parse()

    # we need to delete the config dir when done
    atexit.register(shutil.rmtree, config_dir)

    return config


DEFAULT_CONFIG = _create_configuration()

DEFAULT_CONTINUE_THROUGH = JsonObject({'start': '^--multi',
                                       'continueThrough': "^--"
                                       })
DEFAULT_CONTINUE_PAST = JsonObject({'start': r'\\$',
                                    'continuePast': r"\\$"
                                    })
DEFAULT_HALT_BEFORE = JsonObject({'start': "^--begin",
                                  'haltBefore': "^--end"
                                  })
DEFAULT_HALT_WITH = JsonObject({'start': "^--start",
                                'haltWith': "^--stop"
                                })
if __name__ == '__main__':
    unittest.main()
