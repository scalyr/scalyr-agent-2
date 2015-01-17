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

import os
import shutil
import tempfile
import unittest

from scalyr_agent.log_processing import LogFileIterator, LogLineSampler, LogLineRedacter, LogFileProcessor
from scalyr_agent.log_processing import FileSystem


class TestLogFileIterator(unittest.TestCase):

    def setUp(self):
        self.__tempdir = tempfile.mkdtemp()
        self.__file_system = FileSystem()
        self.__path = os.path.join(self.__tempdir, 'text.txt')
        self.__fake_time = 10

        self.write_file(self.__path, '')
        self.log_file = LogFileIterator(self.__path, self.__file_system)
        self.log_file.set_parameters(max_line_length=5, page_size=20)
        self.mark(time_advance=0)

    def tearDown(self):
        shutil.rmtree(self.__tempdir)
        self.log_file.close()

    def readline(self, time_advance=10):
        self.__fake_time += time_advance

        return self.log_file.readline(current_time=self.__fake_time)

    def mark(self, time_advance=10):
        self.__fake_time += time_advance
        self.log_file.mark(current_time=self.__fake_time)

    def test_initial_scan(self):
        self.append_file(self.__path,
                         'L1\n',
                         'L2\n')

        result = self.readline()

        self.assertEquals(result, 'L1\n')

    def test_multiple_scans(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n',
                         'L003\n',
                         'L004\n',
                         'L005\n',
                         'L006\n')

        self.assertEquals(self.readline(), 'L001\n')
        self.assertEquals(self.log_file.page_reads, 1)
        self.assertEquals(self.readline(), 'L002\n')
        self.assertEquals(self.readline(), 'L003\n')
        self.assertEquals(self.readline(), 'L004\n')
        self.assertEquals(self.readline(), 'L005\n')
        self.assertEquals(self.readline(), 'L006\n')
        self.assertEquals(self.log_file.page_reads, 2)

    def test_no_more_content(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n')

        self.assertEquals(self.readline(), 'L001\n')
        self.assertEquals(self.readline(), 'L002\n')
        self.assertEquals(self.readline(), '')

    def test_more_bytes_added(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n')

        self.assertEquals(self.readline(), 'L001\n')
        self.assertEquals(self.readline(), 'L002\n')
        self.assertEquals(self.readline(), '')

        self.append_file(self.__path,
                         'L03\n',
                         'L04\n')
        self.mark()

        self.assertEquals(self.readline(), 'L03\n')
        self.assertEquals(self.readline(), 'L04\n')
        self.assertEquals(self.readline(), '')

    def test_deleted_file(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n')
        self.delete_file(self.__path)
        self.mark()

        self.assertEquals(self.readline(), 'L001\n')
        self.assertEquals(self.readline(), 'L002\n')
        self.assertEquals(self.readline(), '')
        self.assertFalse(self.log_file.at_end)

        self.mark(time_advance=60*11)
        self.assertTrue(self.log_file.at_end)

    def test_rotated_file_with_truncation(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n')

        self.assertEquals(self.readline(), 'L001\n')
        self.assertEquals(self.readline(), 'L002\n')
        self.assertEquals(self.readline(), '')

        self.truncate_file(self.__path)
        self.append_file(self.__path,
                         'L003\n')
        self.mark()

        self.assertEquals(self.readline(), 'L003\n')
        self.assertEquals(self.readline(), '')

    def test_rotating_log_file_with_move(self):
        self.append_file(self.__path,
                         'L001\n')

        self.assertEquals(self.readline(), 'L001\n')
        self.assertEquals(self.readline(), '')

        self.append_file(self.__path,
                         'L002\n',
                         'L003\n')
        self.move_file(self.__path, self.__path + '.1')
        self.write_file(self.__path,
                        'L004\n',
                        'L005\n')
        self.mark()

        self.assertEquals(self.readline(), 'L002\n')
        self.assertEquals(self.readline(), 'L003\n')
        self.assertEquals(self.readline(), 'L004\n')
        self.assertEquals(self.readline(), 'L005\n')
        self.assertEquals(self.readline(), '')

        self.mark()
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
        self.mark()

        self.assertEquals(self.readline(), 'L001\n')
        self.assertEquals(self.readline(), 'L002\n')

        self.truncate_file(self.__path)
        self.delete_file(self.__path)
        self.write_file(self.__path,
                        'L009\n',
                        'L010\n',
                        'L011\n',
                        'L012\n')
        self.mark()

        self.assertEquals(self.readline(), 'L003\n')
        self.assertEquals(self.readline(), 'L004\n')
        self.assertEquals(self.readline(), 'L009\n')
        self.assertEquals(self.readline(), 'L010\n')
        self.assertEquals(self.readline(), 'L011\n')
        self.assertEquals(self.readline(), 'L012\n')
        self.assertEquals(self.readline(), '')

    def test_holes_in_file(self):
        # This is a more general case of the rotated_file_with_truncation_and_deletion.
        # It essentially creates holes in the virtual file that the __fill_buffer code most correctly
        # deal with.
        # We do this by rotating the log file 3 times.
        # The names of where we rotate the log file to.
        first_portion = os.path.join(self.__tempdir, 'first.txt')
        second_portion = os.path.join(self.__tempdir, 'second.txt')
        third_portion = os.path.join(self.__tempdir, 'third.txt')

        # First rotate.  We need the mark to make sure the LogFileIterator notices this file and remembers its
        # file handle.
        self.append_file(self.__path, 'L001\n', 'L002\n')
        self.mark()
        self.move_file(self.__path, first_portion)

        self.write_file(self.__path, 'L003\n', 'L004\n')
        self.mark()
        self.move_file(self.__path, second_portion)

        self.write_file(self.__path, 'L005\n', 'L006\n')
        self.mark()
        self.move_file(self.__path, third_portion)

        self.write_file(self.__path, 'L007\n')

        self.mark()
        original_position = self.log_file.tell()

        # Read through massively rotated file and verify all of the parts are there.
        self.assertEquals(self.readline(), 'L001\n')
        self.assertEquals(self.readline(), 'L002\n')
        self.assertEquals(self.readline(), 'L003\n')
        self.assertEquals(self.readline(), 'L004\n')
        self.assertEquals(self.readline(), 'L005\n')
        hole_position = self.log_file.tell()
        self.assertEquals(self.readline(), 'L006\n')
        self.assertEquals(self.readline(), 'L007\n')
        self.assertEquals(self.readline(), '')

        # Now we go back to the begin and read it over again, but this time, remove a few of the portions
        # by truncating them.  In particular, we remove the first_portion to test what happens when we seek to
        # an invalid byte offset.  Also, remove_third_portion to test that we correctly jump offset even after
        # a good chunk of data.
        self.truncate_file(first_portion)
        self.truncate_file(third_portion)

        self.log_file.seek(original_position)

        self.assertEquals(self.readline(), 'L003\n')
        self.assertEquals(self.readline(), 'L004\n')
        self.assertEquals(self.readline(), 'L007\n')
        self.assertEquals(self.readline(), '')

        # We should also have the same number of bytes that should have been returned for the entire file.
        self.assertEquals(self.log_file.bytes_between_positions(original_position, self.log_file.tell()), 35)

        # The buffer should hold L003 to L007.  We next test that if we try to seek to a position that should
        # already be in the buffer but isn't because it is a hole, we get the next line.  Also verify that we
        # did really test this case by making sure no new pages were read into cache.
        page_reads = self.log_file.page_reads

        self.log_file.seek(hole_position)
        self.assertEquals(self.readline(), 'L007\n')
        self.assertEquals(self.readline(), '')

        self.assertEquals(self.log_file.page_reads, page_reads)

    def test_partial_line(self):
        self.append_file(self.__path, 'L001')
        self.assertEquals(self.readline(), '')

        self.mark(time_advance=200)
        self.assertEquals(self.readline(), '')

        self.mark(time_advance=100)
        self.assertEquals(self.readline(), 'L001')

    def test_set_position_with_valid_mark(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n')

        position = self.log_file.tell()
        self.assertEquals(self.readline(), 'L001\n')
        self.assertEquals(self.readline(), 'L002\n')

        self.log_file.seek(position)
        self.assertEquals(self.readline(), 'L001\n')
        self.assertEquals(self.readline(), 'L002\n')

    def test_set_invalid_position_after_mark(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n')
        position = self.log_file.tell()

        self.mark()
        self.assertEquals(self.readline(), 'L001\n')
        self.assertEquals(self.readline(), 'L002\n')

        self.assertRaises(Exception, self.log_file.seek, position)

    def test_checkpoint(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n',
                         'L003\n',
                         'L004\n')

        self.assertEquals(self.readline(), 'L001\n')
        saved_checkpoint = self.log_file.get_checkpoint()
        self.log_file = LogFileIterator(self.__path, self.__file_system, checkpoint=saved_checkpoint)
        self.log_file.set_parameters(max_line_length=5, page_size=20)

        self.mark()
        self.assertEquals(self.readline(), 'L002\n')
        self.assertEquals(self.readline(), 'L003\n')
        self.assertEquals(self.readline(), 'L004\n')

    def test_initial_checkpoint(self):
        self.write_file(self.__path,
                        'L001\n',
                        'L002\n',
                        'L003\n',
                        'L004\n')

        self.log_file = LogFileIterator(self.__path, self.__file_system,
                                        checkpoint=LogFileIterator.create_checkpoint(10))
        self.log_file.set_parameters(max_line_length=5, page_size=20)

        self.mark()
        self.assertEquals(self.readline(), 'L003\n')
        self.assertEquals(self.readline(), 'L004\n')

    def test_exceeding_maximum_line_length(self):
        self.append_file(self.__path,
                         'L00001\n',
                         'L002\n')
        self.assertEquals(self.readline(), 'L0000')
        self.assertEquals(self.readline(), '1\n')
        self.assertEquals(self.readline(), 'L002\n')

    def test_availabe_bytes(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n',
                         'L003\n',
                         'L004\n')

        self.mark()
        self.assertEquals(self.log_file.available, 20L)
        self.assertEquals(self.readline(), 'L001\n')
        self.assertEquals(self.log_file.available, 15L)
        self.assertEquals(self.readline(), 'L002\n')
        self.assertEquals(self.readline(), 'L003\n')
        self.assertEquals(self.readline(), 'L004\n')
        self.assertEquals(self.log_file.available, 0L)

    def test_skip_to_end(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n',
                         'L003\n',
                         'L004\n',
                         'L005\n',
                         'L006\n')
        self.mark()
        self.assertEquals(self.log_file.available, 30L)

        self.assertEquals(self.log_file.advance_to_end(), 30L)

        self.append_file(self.__path,
                         'L007\n',
                         'L008\n')

        self.assertEquals(self.readline(), 'L007\n')
        self.assertEquals(self.readline(), 'L008\n')

    def test_skip_to_end_with_buffer(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n',
                         'L003\n')
        self.mark()
        self.assertEquals(self.log_file.available, 15L)

        self.assertEquals(self.log_file.advance_to_end(), 15L)

        self.append_file(self.__path,
                         'L004\n',
                         'L005\n')

        self.assertEquals(self.readline(), 'L004\n')
        self.assertEquals(self.readline(), 'L005\n')

    def test_bytes_between_positions(self):
        self.append_file(self.__path,
                         'L001\n',
                         'L002\n',
                         'L003\n',
                         'L004\n')
        pos1 = self.log_file.tell()
        self.assertEquals(self.readline(), 'L001\n')
        self.assertEquals(self.readline(), 'L002\n')
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

    def write_file(self, path, *lines):
        contents = ''.join(lines)
        file_handle = open(path, 'w')
        file_handle.write(contents)
        file_handle.close()

    def append_file(self, path, *lines):
        contents = ''.join(lines)
        file_handle = open(path, 'a')
        file_handle.write(contents)
        file_handle.close()

    def delete_file(self, path):
        os.remove(path)

    def move_file(self, original_path, new_path):
        os.rename(original_path, new_path)

    def truncate_file(self, path):
        file_handle = open(path, 'w')
        file_handle.truncate(0)
        file_handle.close()


class TestLogLineRedactor(unittest.TestCase):

    def run_test_case(self, redactor, line, expected_line, expected_redaction):
        (result_line, redacted) = redactor.process_line(line)
        self.assertEquals(result_line, expected_line)
        self.assertEquals(redacted, expected_redaction)

    def test_basic_redaction(self):
        redactor = LogLineRedacter('/var/fake_log')
        redactor.add_redaction_rule('password', 'fake')

        self.run_test_case(redactor, "auth=password", "auth=fake", True)
        self.run_test_case(redactor, "another line password", "another line fake", True)
        self.run_test_case(redactor, "do not touch", "do not touch", False)

    def test_multiple_redactions_in_line(self):
        redactor = LogLineRedacter('/var/fake_log')
        redactor.add_redaction_rule('password', 'fake')

        self.run_test_case(redactor, "auth=password foo=password", "auth=fake foo=fake", True)

    def test_regular_expression_redaction(self):
        redactor = LogLineRedacter('/var/fake_log')
        redactor.add_redaction_rule('password=.*', 'password=fake')

        self.run_test_case(redactor, "login attempt password=czerwin", "login attempt password=fake", True)

    def test_regular_expression_with_capture_group(self):
        redactor = LogLineRedacter('/var/fake_log')
        redactor.add_redaction_rule('secret(.*)=.*', 'secret\\1=fake')

        self.run_test_case(redactor, "foo secretoption=czerwin", "foo secretoption=fake", True)

    def test_multiple_redactions(self):
        redactor = LogLineRedacter('/var/fake_log')
        redactor.add_redaction_rule('secret(.*)=.*', 'secret\\1=fake')
        redactor.add_redaction_rule('password=.* ', '')

        self.run_test_case(redactor, "foo password=steve secretoption=czerwin", "foo secretoption=fake", True)

    def test_customer_case(self):
        redactor = LogLineRedacter('/var/fake_log')
        redactor.add_redaction_rule(
            "(access_token|ccNumber|ccSecurityCode|ccExpirationMonth|ccExpirationYear|pwdField|passwordConfirm|"
            "challengeAnswer|code|taxVat|password[0-9]?|pwd|newpwd[0-9]?Field|currentField|security_answer[0-9]|"
            "tinnumber)=[^&]*", "")

        self.run_test_case(redactor, "[11/May/2012:16:20:54 -0400] \"GET /api2/profiles/api_contractor?"
                           "access_token=E|foo&catId=10179&mode=basic HTTP/1.1\" 200 2045",
                           "[11/May/2012:16:20:54 -0400] \"GET /api2/profiles/api_contractor?"
                           "&catId=10179&mode=basic HTTP/1.1\" 200 2045", True)

        self.run_test_case(redactor, "[11/May/2012:16:20:54 -0400] \"GET /api2/profiles/api_contractor?"
                           "access_token=E|foo&newpwd5Field=10179&mode=basic HTTP/1.1\" 200 2045",
                           "[11/May/2012:16:20:54 -0400] \"GET /api2/profiles/api_contractor?&&mode=basic"
                           " HTTP/1.1\" 200 2045", True)


class TestLogLineSampler(unittest.TestCase):
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


class TestLogFileProcessor(unittest.TestCase):

    def setUp(self):
        self.__tempdir = tempfile.mkdtemp()
        self.__file_system = FileSystem()
        self.__path = os.path.join(self.__tempdir, 'text.txt')
        self.__fake_time = 10

        # Create the processor to test.  We have it do one scan of an empty
        # file so that when we next append lines to it, it will notice it.
        # For now, we create one that does not have any log attributes and only
        # counts the bytes of events messages as the cost.
        self.write_file(self.__path, '')
        self.log_processor = LogFileProcessor(self.__path, file_system=self.__file_system,
                                              log_attributes={})
        (completion_callback, buffer_full) = self.log_processor.perform_processing(
            TestLogFileProcessor.TestAddEventsRequest(), current_time=self.__fake_time)
        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))

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

    def test_log_attributes(self):
        log_processor = LogFileProcessor(self.__path, file_system=self.__file_system,
                                         log_attributes={'host': 'scalyr-1'})
        log_processor.perform_processing(TestLogFileProcessor.TestAddEventsRequest(), current_time=self.__fake_time)

        self.append_file(self.__path, 'First line\nSecond line\n')

        events = TestLogFileProcessor.TestAddEventsRequest()
        (completion_callback, buffer_full) = log_processor.perform_processing(events, current_time=self.__fake_time)

        self.assertFalse(completion_callback(LogFileProcessor.SUCCESS))
        self.assertEquals(events.total_events(), 2)
        self.assertEquals('scalyr-1', events.events[0]['attrs']['host'])
        self.assertEquals('scalyr-1', events.events[1]['attrs']['host'])

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

    def write_file(self, path, *lines):
        contents = ''.join(lines)
        file_handle = open(path, 'w')
        file_handle.write(contents)
        file_handle.close()

    def append_file(self, path, *lines):
        contents = ''.join(lines)
        file_handle = open(path, 'a')
        file_handle.write(contents)
        file_handle.close()

    class TestAddEventsRequest(object):
        def __init__(self, limit=10, thread_limit=10):
            self.events = []
            self.__limit = limit
            self.__thread_limit = thread_limit
            self.threads = {}

        def add_event(self, event):
            if len(self.events) < self.__limit:
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
            return self.events[index]['attrs']['message']

        def total_events(self):
            return len(self.events)

if __name__ == '__main__':
    unittest.main()
