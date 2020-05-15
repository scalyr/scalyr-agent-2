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

from __future__ import absolute_import
from __future__ import print_function

import os
import io
import sys
import unittest
from io import open

import mock

BASE_DIR = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))

MODULE_PATH = os.path.abspath(
    os.path.join(BASE_DIR, "../../../scalyr_agent/third_party/tcollector/collectors/0")
)
FIXTURES_DIR = os.path.abspath(os.path.join(BASE_DIR, "../fixtures/diskstats"))
sys.path.append(MODULE_PATH)

# pylint: disable=import-error
# type: ignore
from iostat import parse_and_print_metrics
from iostat import FIELDS_DISK


class IOStatTcollectorTestCase(unittest.TestCase):
    @mock.patch("iostat.time.time", mock.Mock(return_value=100))
    def test_verify_proc_diskstats_parsing_kernel_pre_4_18(self):
        file_path = os.path.join(FIXTURES_DIR, "kernel_pre_4.18.txt")
        output_file_sucess = io.StringIO()
        output_file_error = io.StringIO()
        f_diskstats = None

        try:
            f_diskstats = open(file_path, "r")
            parse_and_print_metrics(f_diskstats, output_file_sucess, output_file_error)
        finally:
            if f_diskstats:
                f_diskstats.close()

        output_success = output_file_sucess.getvalue()
        output_error = output_file_error.getvalue()
        output_success_lines = output_success.strip().split("\n")

        self.assertEqual(output_error, "")
        self.assertOutputContainsAllFields(output_success)
        self.assertEqual(
            output_success_lines[0], "iostat.disk.read_requests 100 446216 dev=hda"
        )
        self.assertEqual(
            output_success_lines[-1], "iostat.part.write_sectors 100 38030 dev=hda1"
        )

    @mock.patch("iostat.time.time", mock.Mock(return_value=104))
    def test_verify_proc_diskstats_parsing_kernel_post_4_18(self):
        file_path = os.path.join(FIXTURES_DIR, "kernel_post_4.18.txt")
        output_file_sucess = io.StringIO()
        output_file_error = io.StringIO()
        f_diskstats = None

        try:
            f_diskstats = open(file_path, "r")
            parse_and_print_metrics(f_diskstats, output_file_sucess, output_file_error)
        finally:
            if f_diskstats:
                f_diskstats.close()

        output_success = output_file_sucess.getvalue()
        output_error = output_file_error.getvalue()
        output_success_lines = output_success.strip().split("\n")

        self.assertEqual(output_error, "")
        self.assertOutputContainsAllFields(output_success)
        self.assertEqual(
            output_success_lines[0], "iostat.disk.read_requests 104 446216 dev=hda"
        )
        self.assertEqual(
            output_success_lines[-1],
            "iostat.disk.msec_weighted_total 104 23705160 dev=hda",
        )

    @mock.patch("iostat.time.time", mock.Mock(return_value=101))
    def test_verify_proc_diskstats_parsing_kernel_4_4(self):
        file_path = os.path.join(FIXTURES_DIR, "kernel_4.4.0.txt")
        output_file_sucess = io.StringIO()
        output_file_error = io.StringIO()
        f_diskstats = None

        try:
            f_diskstats = open(file_path, "r")
            parse_and_print_metrics(f_diskstats, output_file_sucess, output_file_error)
        finally:
            if f_diskstats:
                f_diskstats.close()

        output_success = output_file_sucess.getvalue()
        output_error = output_file_error.getvalue()
        output_success_lines = output_success.strip().split("\n")

        self.assertEqual(output_error, "")
        self.assertOutputContainsAllFields(output_success)
        self.assertEqual(
            output_success_lines[0], "iostat.disk.read_requests 101 5 dev=loop0"
        )
        self.assertEqual(
            output_success_lines[-1], "iostat.disk.msec_weighted_total 101 44 dev=sdb"
        )

    @mock.patch("iostat.time.time", mock.Mock(return_value=102))
    def test_verify_proc_diskstats_parsing_kernel_5_5(self):
        file_path = os.path.join(FIXTURES_DIR, "kernel_5.5.7.txt")
        output_file_sucess = io.StringIO()
        output_file_error = io.StringIO()
        f_diskstats = None

        try:
            f_diskstats = open(file_path, "r")
            parse_and_print_metrics(f_diskstats, output_file_sucess, output_file_error)
        finally:
            if f_diskstats:
                f_diskstats.close()

        output_success = output_file_sucess.getvalue()
        output_error = output_file_error.getvalue()
        output_success_lines = output_success.strip().split("\n")

        self.assertEqual(output_error, "")
        self.assertOutputContainsAllFields(output_success)
        self.assertEqual(
            output_success_lines[0], "iostat.disk.read_requests 102 475618 dev=nvme0n1"
        )
        self.assertEqual(
            output_success_lines[-1],
            "iostat.part.msec_weighted_total 102 343377888 dev=dm-3",
        )

    @mock.patch("iostat.time.time", mock.Mock(return_value=101))
    def test_verify_proc_diskstats_parsing_invalid_content(self):
        file_path = os.path.join(FIXTURES_DIR, "invalid.txt")
        output_file_sucess = io.StringIO()
        output_file_error = io.StringIO()
        f_diskstats = None

        try:
            f_diskstats = open(file_path, "r")
            parse_and_print_metrics(f_diskstats, output_file_sucess, output_file_error)
        finally:
            if f_diskstats:
                f_diskstats.close()

        output_success = output_file_sucess.getvalue()
        output_error = output_file_error.getvalue().strip()

        self.assertEqual(
            output_error, "Cannot parse /proc/diskstats line:  3    0   hda 446216"
        )
        self.assertEqual(output_success, "")

    def assertOutputContainsAllFields(self, output):
        # Verify that all the fields from FIELDS_DISK list are present in the output
        seen = 0
        for field_name in FIELDS_DISK:
            if field_name in output:
                seen += 1

        if seen != len(FIELDS_DISK):
            raise AssertionError(
                "Expected %s fields, got %s" % (len(FIELDS_DISK), seen)
            )
