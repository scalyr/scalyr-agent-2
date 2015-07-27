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
# Line Matching abstraction to allow for single and multi-line processing
# of log files.
# See here for a more detailed description of each log type:
# https://www.scalyr.com/help/parsing-logs#multiline
#
# author: Imron Alston <imron@imralsoftware.com>
import sys

__author__ = 'imron@imralsoftware.com'


class LineMatcher(object):
    """
    """

    def __init__( self , max_line_length=5*1024, line_completion_wait_time=5*60 ):
        self._max_line_length = max_line_length
        self.__line_completion_wait_time = line_completion_wait_time
        self.__partial_line_time = None

    def readline( self, file_like, current_time ):
        original_offset = file_like.tell()

        line, partial = self._readline( file_like )

        if len( line ) == 0:
            self.__partial_line_time = None
            return line

        # If we have a partial line then we should only
        # return it if sufficient time has passed.
        if partial and len( line ) < self._max_line_length:

            if self.__partial_line_time is None:
                self.__partial_line_time = current_time

            if current_time - self.__partial_line_time < self.__line_completion_wait_time:
                # We aren't going to return it so reset buffer back to the original spot.
                file_like.seek( original_offset )
                return ''
        else:
            self.__partial_line_time = None

        return line

    def _readline( self, file_like, max_length=0 ):
        """
        """
        if max_length == 0:
            max_length = self._max_line_length

        line = file_like.readline( max_length )
        partial = len( line) > 0 and line[-1] != '\n' and line[-1] != '\r'
        return line, partial

class LineMatcherCollection( LineMatcher ):
    """
    """
    def __init__( self, max_line_length, line_completion_wait_time ):
        LineMatcher.__init__( self, max_line_length, line_complete_wait_time )
        self.__matchers = []
        self.__current_match = None

    def add_matcher( self, matcher ):
        self.__matchers.append( matcher )

    def _readline( self, file_like, max_length=0 ):

        if max_length == 0:
            max_length = self._max_line_length

        line = None
        partial = False
        for matcher in self.__matchers:
            offset = file_like.tell()
            line, partial = matcher._readline( file_like, max_length )
            if line:
                break
            file_like.seek( offset )
        
        if not line:
            line, partial =  LineMatcher._readline( self, file_like, max_length )
            
        return line, partial

class LineGrouper( LineMatcher ):
    def __init__( self, start_pattern, continuation_pattern, max_line_length = 5*1024, line_completion_wait_time=5*60 ):
        LineMatcher.__init__( self, max_line_length, line_completion_wait_time )
        self._start_pattern = start_pattern
        self._continuation_pattern = continuation_pattern

    def _readline( self, file_like, max_length=0 ):
        if max_length == 0:
            max_length = self._max_line_length

        start_offset = file_like.tell()

        line = ''
        partial = False
        start_line, partial = LineMatcher._readline( self, file_like, max_length )

        if partial:
            return start_line, partial

        start = self._start_line( start_line )
        if start:
            max_length -= len( start_line )
            next_offset = file_like.tell()
            next_line, next_partial = LineMatcher._readline( self, file_like, max_length )
            if next_line:
                cont = self._continue_line( next_line )
                if cont:
                    line = start_line
                    while cont and next_line and max_length > 0:
                        line += next_line
                        max_length -= len( next_line )
                        next_offset = file_like.tell()
                        next_line, partial = LineMatcher._readline( self, file_like, max_length )
                        cont = self._continue_line( next_line )

                    file_like.seek( next_offset )

                    partial = partial or cont

                else:
                    file_like.seek( start_offset )
                    line = ''
            else:
                line = start_line
                partial = True
        else:
            file_like.seek( start_offset )
            line, partial = '', False

        return line, partial

    def _continue_line( self, line ):
        return False

    def _start_line( self, line ):
        return self._start_pattern.search( line ) != None

class ContinueThrough( LineGrouper ):
    """
    """
    def _continue_line( self, line ):
        if not line:
            return True

        return self._continuation_pattern.search( line ) != None
            

class ContinuePast( LineGrouper ):
    """
    """
    def __init__( self, start_pattern, continuation_pattern, max_line_length = 5*1024, line_completion_wait_time=5*60 ):
        LineGrouper.__init__( self, start_pattern, continuation_pattern, max_line_length, line_completion_wait_time )
        self.__last_line = False
        self.__grouping = False

    def _start_line( self, line ):
        result = LineGrouper._start_line( self, line )
        self.__grouping = result
        self.__last_line = False

        return result

    def _continue_line( self, line ):
        if self.__last_line:
            self.__last_line = False
            return False

        match = self._continuation_pattern.search( line )
        result = True
        if self.__grouping:
            if not match:
                self.__grouping = False
                self.__last_line = True
        else:
            if not match:
                result = False

        return result
    
class HaltBefore( LineGrouper ):
    """
    """
    def _continue_line( self, line ):
        return self._continuation_pattern.search( line ) == None

class HaltWith( LineGrouper ):
    """
    """
    def __init__( self, start_pattern, continuation_pattern, max_line_length = 5*1024, line_completion_wait_time=5*60 ):
        LineGrouper.__init__( self, start_pattern, continuation_pattern, max_line_length, line_completion_wait_time )
        self.__last_line = False
        self.__grouping = False

    def _start_line( self, line ):
        result = LineGrouper._start_line( self, line )
        self.__last_line = False
        return result

    def _continue_line( self, line ):
        if self.__last_line:
            self.__last_line = False
            return False

        cont = self._continuation_pattern.search( line ) == None

        if not cont:
            self.__last_line = True
            cont = True
        return cont
        

