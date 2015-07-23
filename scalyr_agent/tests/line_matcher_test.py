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
# author: Imron Alston <imron@imralsoftware.com>

__author__ = 'imron@imralsoftware.com'

import re
import time
import unittest

from cStringIO import StringIO
from scalyr_agent.line_matcher import LineMatcher
from scalyr_agent.line_matcher import ContinueThrough

def make_string( string ):
    line = StringIO()
    line.write( string )
    line.seek( 0 )
    return line

def append_string( line, string ):
    offset = line.tell()
    line.seek( 0, 2 )
    line.write( string )
    line.seek( offset )
    return line

class SingleLineMatcherTestCase( unittest.TestCase ):

    def test_single_line( self ):
        expected = "Hello World\n"
        line = make_string( expected )

        line_matcher = LineMatcher()
        actual = line_matcher.readline( line, time.time() )
        self.assertEqual( expected, actual )


    def test_single_line_partial( self ):
        expected = "Hello World"
        line = make_string( expected )

        line_matcher = LineMatcher()
        actual = line_matcher.readline( line, time.time() )
        self.assertEqual( '', actual )

        line = append_string( line, "\n" )

        actual = line_matcher.readline( line, time.time() )
        self.assertEqual( expected + "\n", actual )

    def test_single_line_partial_timeout( self ):
        expected = "Hello World"
        line = make_string( expected )

        line_matcher = LineMatcher( line_completion_wait_time = 5 )
        current_time = time.time() - 6
        actual = line_matcher.readline( line, current_time )
        self.assertEqual( '', actual )

        actual = line_matcher.readline( line, time.time() )
        self.assertEqual( expected, actual )

    def test_single_line_partial_too_long( self ):
        expected = "Hello World"
        line = make_string( expected + " How are you today" )

        line_matcher = LineMatcher( max_line_length=11 )
        current_time = time.time()
        actual = line_matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

class ContinueThroughTestCase( unittest.TestCase ):

    def setUp( self ):
        self.start_pattern = re.compile( "^[^\\s]" )
        self.continuation_pattern = re.compile( "^[\\s]+at" )

    def test_continue_through( self ):
        expected = "java.lang.Exception\n    at com.foo.bar(bar.java:123)\n    at com.foo.baz(baz.java:123)\n"
        expected_next = "next line\n"
        line = make_string( expected + expected_next + expected_next )

        matcher = ContinueThrough( self.start_pattern, self.continuation_pattern )
        current_time = time.time()
        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected_next, actual )

    def test_first_line_match_second_line_no_match( self ):
        expected = "java.lang.Exception\n"
        expected_next = "haha Not a java.lang.Exception\n"

        line = make_string( expected + expected_next + expected_next )
        matcher = ContinueThrough( self.start_pattern, self.continuation_pattern )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )
        actual = matcher.readline( line, current_time )
        self.assertEqual( expected_next, actual )

    def test_partial_first_line_match( self ):
        expected = "java.lang.Exception\n"
        expected_next = "    at com.foo.bar(bar.java:123)\n"
        expected_last = "Another line\n"

        line = make_string( expected )
        matcher = ContinueThrough( self.start_pattern, self.continuation_pattern )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )

        line = append_string( line, expected_next + expected_last + expected_last )

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected + expected_next, actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected_last, actual )

    def test_partial_multiline_match( self ):
        expected = "java.lang.Exception\n    at com.foo.bar(bar.java:123)\n    at com.foo.baz(baz.java:456)\n"
        expected_last = "Another line\n"

        line = make_string( expected )
        matcher = ContinueThrough( self.start_pattern, self.continuation_pattern )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )

        line = append_string( line, expected_last + expected_last )

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )
        
        actual = matcher.readline( line, current_time )
        self.assertEqual( expected_last, actual )

    def test_no_match( self ):
        line1 = "   starts with a space\n"
        line2 = "   also starts with a space\n"
        line = make_string( line1 + line2 )
        matcher = ContinueThrough( self.start_pattern, self.continuation_pattern )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )
        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )

    def test_timeout_after_matching_start( self ):
        expected = "java.lang.Exception\n"
        line = make_string( expected )

        matcher = ContinueThrough( self.start_pattern, self.continuation_pattern, line_completion_wait_time = 5 )
        current_time = time.time()
        actual = matcher.readline( line, current_time - 6 )
        self.assertEqual( '', actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        expected_next = "  starts with a space\n"
        line = append_string( line, expected_next )
        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )

    def test_timeout_after_matching_continue( self ):
        expected = "java.lang.Exception\n    at com.foo.bar(bar.java:123)\n"
        line = make_string( expected )

        matcher = ContinueThrough( self.start_pattern, self.continuation_pattern, line_completion_wait_time = 5 )
        current_time = time.time()
        actual = matcher.readline( line, current_time - 6 )
        self.assertEqual( '', actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        expected_next = "  starts with a space\n"
        line = append_string( line, expected_next )
        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )


    def test_too_long_matching_start( self ):
        expected = "java.lang."
        line = make_string( expected + "Exception\n" )

        matcher = ContinueThrough( self.start_pattern, self.continuation_pattern, max_line_length = 10 )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        line = append_string( line, "next line\n" )
        actual = matcher.readline( line, current_time )
        self.assertEqual( "Exception\n", actual )

    def test_too_long_after_matching_continue( self ):
        self.assertTrue( False )




