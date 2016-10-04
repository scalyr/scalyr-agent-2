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

import time
import unittest

import pdb

from cStringIO import StringIO
from scalyr_agent.line_matcher import LineMatcher
from scalyr_agent.line_matcher import LineMatcherCollection
from scalyr_agent.line_matcher import ContinueThrough
from scalyr_agent.line_matcher import ContinuePast
from scalyr_agent.line_matcher import HaltBefore
from scalyr_agent.line_matcher import HaltWith

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
        self.start_pattern = "^[^\\s]"
        self.continuation_pattern = "^[\\s]+at"

    def test_continue_through( self ):
        expected = "java.lang.Exception\n    at com.foo.bar(bar.java:123)\n    at com.foo.baz(baz.java:123)\n"
        expected_next = "next line\n"
        line = make_string( expected + expected_next )

        matcher = ContinueThrough( self.start_pattern, self.continuation_pattern )
        current_time = time.time()
        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )

        actual = line.readline()
        self.assertEqual( expected_next, actual )

    def test_first_line_match_second_line_no_match( self ):
        expected = "java.lang.Exception\n"
        expected_next = "haha Not a java.lang.Exception\n"

        line = make_string( expected + expected_next )
        matcher = ContinueThrough( self.start_pattern, self.continuation_pattern )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )

        actual = line.readline()
        self.assertEqual( expected, actual )

    def test_partial_first_line_match( self ):
        expected = "java.lang.Exception\n"
        expected_next = "    at com.foo.bar(bar.java:123)\n"
        expected_last = "Another line\n"

        line = make_string( expected )
        matcher = ContinueThrough( self.start_pattern, self.continuation_pattern )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )

        line = append_string( line, expected_next + expected_last )

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected + expected_next, actual )

        actual = line.readline()
        self.assertEqual( expected_last, actual )

    def test_partial_multiline_match( self ):
        expected = "java.lang.Exception\n    at com.foo.bar(bar.java:123)\n    at com.foo.baz(baz.java:456)\n"
        expected_last = "Another line\n"

        line = make_string( expected )
        matcher = ContinueThrough( self.start_pattern, self.continuation_pattern )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )

        line = append_string( line, expected_last )

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )
        
        actual = line.readline()
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

        actual = line.readline()
        self.assertEqual( line1, actual )

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

        actual = line.readline()
        self.assertEqual( expected_next, actual )

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

        actual = line.readline()
        self.assertEqual( expected_next, actual )


    def test_too_long_matching_start( self ):
        expected = "java.lang."
        line = make_string( expected + "Exception\n" )

        matcher = ContinueThrough( self.start_pattern, self.continuation_pattern, max_line_length = 10 )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = line.readline()
        self.assertEqual( "Exception\n", actual )

    def test_too_long_after_matching_continue( self ):
        expected = "java.lang.Exception\n    at com"
        remainder = ".foo.baz(baz.java:123)\n"
        line = make_string( expected + remainder )

        matcher = ContinueThrough( self.start_pattern, self.continuation_pattern, max_line_length = 30 )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = line.readline()
        self.assertEqual( remainder, actual )

class ContinuePastTestCase( unittest.TestCase ):

    def setUp( self ):
        self.start_pattern = r"\\$"
        self.continuation_pattern = r"\\$"

    def test_continue_past( self ):
        expected = "This is a multiline \\\nstring with each line\\\nseparated by backslashes\n"
        expected_next = "next line\n"
        line = make_string( expected + expected_next )

        matcher = ContinuePast( self.start_pattern, self.continuation_pattern )
        current_time = time.time()
        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )

        actual = line.readline()
        self.assertEqual( expected_next, actual )

    def test_first_line_match_second_line_no_match( self ):
        expected = "multiline string \\\nthat ends here\n"
        expected_next = "single line string\n"

        line = make_string( expected + expected_next )
        matcher = ContinuePast( self.start_pattern, self.continuation_pattern )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )

        actual = line.readline()
        self.assertEqual( expected_next, actual )

    def test_partial_first_line_match( self ):
        expected = "start of a multiline\\\n"
        expected_next = "last line\n"
        expected_last = "Another line\n"

        line = make_string( expected )
        matcher = ContinuePast( self.start_pattern, self.continuation_pattern )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )

        line = append_string( line, expected_next + expected_last )

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected + expected_next, actual )

        actual = line.readline()
        self.assertEqual( expected_last, actual )

    def test_partial_multiline_match( self ):
        expected = "start of a multiline line\\\ncontinuation of a multiline line\\\nstill continuing\\\n"
        expected_last = "Another line\n"

        line = make_string( expected )
        matcher = ContinuePast( self.start_pattern, self.continuation_pattern )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )

        line = append_string( line, expected_last )

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected + expected_last, actual )
        
        actual = line.readline()
        self.assertEqual( '', actual )

    def test_no_match( self ):
        line1 = "single line\n"
        line2 = "another single  line\n"
        line = make_string( line1 + line2 )
        matcher = ContinuePast( self.start_pattern, self.continuation_pattern )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )
        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )

        actual = line.readline()
        self.assertEqual( line1, actual )

    def test_timeout_after_matching_start( self ):
        expected = "start of a multiline\\\n"
        line = make_string( expected )

        matcher = ContinuePast( self.start_pattern, self.continuation_pattern, line_completion_wait_time = 5 )
        current_time = time.time()
        actual = matcher.readline( line, current_time - 6 )
        self.assertEqual( '', actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = line.readline()
        self.assertEqual( '', actual )

    def test_timeout_after_matching_continue( self ):
        expected = "start of a multiline\\\ncontinuation of a multiline\\\n"
        line = make_string( expected )

        matcher = ContinuePast( self.start_pattern, self.continuation_pattern, line_completion_wait_time = 5 )
        current_time = time.time()
        actual = matcher.readline( line, current_time - 6 )
        self.assertEqual( '', actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = line.readline()
        self.assertEqual( '', actual )


    def test_too_long_matching_start( self ):
        expected = "start of a"
        line = make_string( expected + " multiline\\\n" )

        matcher = ContinuePast( self.start_pattern, self.continuation_pattern, max_line_length = 10 )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = line.readline()
        self.assertEqual( " multiline\\\n", actual )

    def test_too_long_after_matching_continue( self ):
        expected = "start of a multiline\\\ncontinuing\\\nthis line "
        remainder = "will be cut\n"
        line = make_string( expected + remainder )

        matcher = ContinuePast( self.start_pattern, self.continuation_pattern, max_line_length = 44 )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = line.readline()
        self.assertEqual( remainder, actual )

class HaltBeforeTestCase( unittest.TestCase ):

    def setUp( self ):
        self.start_pattern = r"^--begin"
        self.continuation_pattern = r"^--begin"

    def test_halt_before( self ):
        expected = "--begin\nThis is a multiline message\nThat will end when the\nnext one starts\n"
        expected_next = "--begin\n"
        line = make_string( expected + expected_next )

        matcher = HaltBefore( self.start_pattern, self.continuation_pattern )
        current_time = time.time()
        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )

        actual = line.readline()
        self.assertEqual( expected_next, actual )

    def test_first_line_match_second_line_no_match( self ):
        expected = "--begin\n"
        expected_next = "--begin\n"

        line = make_string( expected + expected_next )
        matcher = HaltBefore( self.start_pattern, self.continuation_pattern )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )

    def test_partial_first_line_match( self ):
        expected = "--begin\n"
        expected_next = "last line\n"
        expected_last = "--begin\n"

        line = make_string( expected )
        matcher = HaltBefore( self.start_pattern, self.continuation_pattern )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )

        line = append_string( line, expected_next + expected_last )

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected + expected_next, actual )

        actual = line.readline()
        self.assertEqual( expected_last, actual )

    def test_partial_multiline_match( self ):
        expected = "--begin\ncontinuation of a multiline line\nstill continuing\n"
        expected_last = "--begin\n"

        line = make_string( expected )
        matcher = HaltBefore( self.start_pattern, self.continuation_pattern )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )

        line = append_string( line, expected_last )

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )
        
        actual = line.readline()
        self.assertEqual( expected_last, actual )

    def test_no_match( self ):
        line1 = "single line\n"
        line2 = "another single  line\n"
        line = make_string( line1 + line2 )
        matcher = HaltBefore( self.start_pattern, self.continuation_pattern )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )
        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )

        actual = line.readline()
        self.assertEqual( line1, actual )

    def test_timeout_after_matching_start( self ):
        expected = "--begin\n"
        line = make_string( expected )

        matcher = HaltBefore( self.start_pattern, self.continuation_pattern, line_completion_wait_time = 5 )
        current_time = time.time()
        actual = matcher.readline( line, current_time - 6 )
        self.assertEqual( '', actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = line.readline()
        self.assertEqual( '', actual )

    def test_timeout_after_matching_continue( self ):
        expected = "--begin\nMultiline\n"
        line = make_string( expected )

        matcher = HaltBefore( self.start_pattern, self.continuation_pattern, line_completion_wait_time = 5 )
        current_time = time.time()
        actual = matcher.readline( line, current_time - 6 )
        self.assertEqual( '', actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = line.readline()
        self.assertEqual( '', actual )

    def test_too_long_matching_start( self ):
        expected = "--begin"

        line = make_string( expected + " multiline\n" )

        matcher = HaltBefore( self.start_pattern, self.continuation_pattern, max_line_length = 7 )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = line.readline()
        self.assertEqual( " multiline\n", actual )

    def test_too_long_after_matching_continue( self ):
        expected = "--begin\nmultiline\nthis line "
        remainder = "will be cut\n"
        line = make_string( expected + remainder )

        matcher = HaltBefore( self.start_pattern, self.continuation_pattern, max_line_length = 28 )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = line.readline()
        self.assertEqual( remainder, actual )

    def test_too_long_after_matching_partial_halt( self ):
        expected = "--begin\nmultiline\nmulti\n--beginthis line "
        remainder = "will be cut\n"
        line = make_string( expected + remainder )

        matcher = HaltBefore( self.start_pattern, self.continuation_pattern, max_line_length = 41 )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = line.readline()
        self.assertEqual( remainder, actual )

class HaltWithTestCase( unittest.TestCase ):

    def setUp( self ):
        self.start_pattern = r"^--begin"
        self.continuation_pattern = r"^--end"

    def test_halt_before( self ):
        expected = "--begin\nThis is a multiline message\nThat will end when the\nnext one starts\n--end\n"
        expected_next = "next line\n"
        line = make_string( expected + expected_next )

        matcher = HaltWith( self.start_pattern, self.continuation_pattern )
        current_time = time.time()
        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )

        actual = line.readline()
        self.assertEqual( expected_next, actual )

    def test_first_line_match_second_line_no_match( self ):
        expected = "--begin\n"
        expected_next = "--end\n"

        line = make_string( expected + expected_next )
        matcher = HaltWith( self.start_pattern, self.continuation_pattern )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected + expected_next, actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )


    def test_partial_first_line_match( self ):
        expected = "--begin\n"
        expected_next = "--end\n"
        expected_last = "next line\n"

        line = make_string( expected )
        matcher = HaltWith( self.start_pattern, self.continuation_pattern )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )

        line = append_string( line, expected_next + expected_last )

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected + expected_next, actual )

        actual = line.readline()
        self.assertEqual( expected_last, actual )

    def test_partial_multiline_match( self ):
        expected = "--begin\ncontinuation of a multiline line\nstill continuing\n"
        expected_end = "--end\n"

        line = make_string( expected )
        matcher = HaltWith( self.start_pattern, self.continuation_pattern )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )

        line = append_string( line, expected_end )

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected + expected_end, actual )
        
        actual = line.readline()
        self.assertEqual( '', actual )

    def test_no_match( self ):
        line1 = "single line\n"
        line2 = "another single  line\n"
        line = make_string( line1 + line2 )
        matcher = HaltWith( self.start_pattern, self.continuation_pattern )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )
        actual = matcher.readline( line, current_time )
        self.assertEqual( '', actual )

        actual = line.readline()
        self.assertEqual( line1, actual )

    def test_timeout_after_matching_start( self ):
        expected = "--begin\n"
        line = make_string( expected )

        matcher = HaltWith( self.start_pattern, self.continuation_pattern, line_completion_wait_time = 5 )
        current_time = time.time()
        actual = matcher.readline( line, current_time - 6 )
        self.assertEqual( '', actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = line.readline()
        self.assertEqual( '', actual )

    def test_timeout_after_matching_continue( self ):
        expected = "--begin\nMultiline\n"
        line = make_string( expected )

        matcher = HaltWith( self.start_pattern, self.continuation_pattern, line_completion_wait_time = 5 )
        current_time = time.time()
        actual = matcher.readline( line, current_time - 6 )
        self.assertEqual( '', actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = line.readline()
        self.assertEqual( '', actual )

    def test_too_long_matching_start( self ):
        expected = "--begin"

        line = make_string( expected + " multiline\n" )

        matcher = HaltWith( self.start_pattern, self.continuation_pattern, max_line_length = 7 )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = line.readline()
        self.assertEqual( " multiline\n", actual )

    def test_too_long_after_matching_continue( self ):
        expected = "--begin\nmultiline\nthis line "
        remainder = "will be cut\n"
        line = make_string( expected + remainder )

        matcher = HaltWith( self.start_pattern, self.continuation_pattern, max_line_length = 28 )
        current_time = time.time()

        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = line.readline()
        self.assertEqual( remainder, actual )

class LineMatcherCollectionTestCase( unittest.TestCase ):

    def continue_through( self, start="^--multi", cont="^--", length=1024, timeout=60 ):
        return ContinueThrough( start, cont, length, timeout )

    def continue_through_string( self ):
        return "--multi\n--next\n--last\n"

    def continue_past( self, start=r"\\$", cont=r"\\$", length=1024, timeout=60 ):
        return ContinuePast( start, cont, length, timeout )

    def continue_past_string( self ):
        return "continue past \\\nand past\\\nand stop\n"

    def halt_before( self, start="^--begin", cont="^--last", length=1024, timeout=60 ):
        return HaltBefore( start, cont, length, timeout )

    def halt_before_string( self ):
        return "--begin\nand halt before\nthe next line starting with the start pattern\n"

    def halt_with( self, start="^--start", cont="^--end", length=1024, timeout=60 ):
        return HaltWith( start, cont, length, timeout )

    def halt_with_string( self ):
        return "--start\nand stop after\nthe next line\n--end\n"

    def single_string( self ):
        return "a single line\n"

    def line_matcher_collection( self, length=1024, timeout=60 ):
        result = LineMatcherCollection( length, timeout )

        result.add_matcher( self.continue_through() )
        result.add_matcher( self.continue_past() )
        result.add_matcher( self.halt_before() )
        result.add_matcher( self.halt_with() )

        return result

    def test_continue_through( self ):

        matcher = self.line_matcher_collection()
        expected = self.continue_through_string()

        current_time = time.time()
        line = make_string( expected + self.single_string() )
        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = line.readline()
        self.assertEqual( self.single_string(), actual )

    def test_continue_past( self ):

        matcher = self.line_matcher_collection()
        expected = self.continue_past_string()

        current_time = time.time()
        line = make_string( expected + self.single_string() )
        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = line.readline()
        self.assertEqual( self.single_string(), actual )

    def test_halt_before( self ):

        matcher = self.line_matcher_collection()
        expected = self.halt_before_string()

        current_time = time.time()
        line = make_string( expected + "--last\n" )
        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = line.readline()
        self.assertEqual( "--last\n", actual )

    def test_halt_with( self ):

        matcher = self.line_matcher_collection()
        expected = self.halt_with_string()

        current_time = time.time()
        line = make_string( expected + self.single_string() )
        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = line.readline()
        self.assertEqual( self.single_string(), actual )

    def test_none( self ):
        matcher = self.line_matcher_collection()
        expected = self.single_string()

        current_time = time.time()
        line = make_string( expected )
        actual = matcher.readline( line, current_time )
        self.assertEqual( expected, actual )

        actual = line.readline()
        self.assertEqual( '', actual )

    def test_all( self ):
        matcher = self.line_matcher_collection()
        end_marker = "--last\n"
        expected = self.single_string() + self.halt_with_string() + self.halt_before_string() + end_marker + self.continue_past_string() + self.continue_through_string() + self.single_string()

        current_time = time.time()
        line = make_string( expected )
        actual = matcher.readline( line, current_time )
        self.assertEqual( self.single_string(), actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( self.halt_with_string(), actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( self.halt_before_string(), actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( end_marker, actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( self.continue_past_string(), actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( self.continue_through_string(), actual )

        actual = matcher.readline( line, current_time )
        self.assertEqual( self.single_string(), actual )

        actual = line.readline()
        self.assertEqual( '', actual )

    
    
