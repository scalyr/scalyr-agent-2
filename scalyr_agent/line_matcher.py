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

    def _readline( self, file_like ):
        """
        """
        line = file_like.readline( self._max_line_length )
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

    def _readline( self, file_like ):

        line = None
        partial = False
        for matcher in self.__matchers:
            offset = file_like.tell()
            line, partial = matcher._readline( file_like )
            if line:
                break
            file_like.seek( offset )
        
        if not line:
            line, partial =  LineMatcher._readline( self, file_like )
            
        return line, partial

class LineGrouper( LineMatcher ):
    def __init__( self, start_pattern, continuation_pattern, max_line_length = 5*1024, line_completion_wait_time=5*60 ):
        LineMatcher.__init__( self, max_line_length, line_completion_wait_time )
        self._start_pattern = start_pattern
        self._continuation_pattern = continuation_pattern


class ContinueThrough( LineGrouper ):
    """
    """
    def _readline( self, file_like ):
        start_offset = file_like.tell()

        line = ''
        partial = False
        start_line, partial = LineGrouper._readline( self, file_like )

        if partial:
            return start_line, partial

        start = self._start_pattern.match( start_line )
        if start:
            next_offset = file_like.tell()
            next_line, next_partial = LineGrouper._readline( self, file_like )
            if next_line:
                cont = self._continuation_pattern.match( next_line )
                if cont:
                    line = start_line
                    while cont:
                        line += next_line
                        next_offset = file_like.tell()
                        next_line, partial = LineGrouper._readline( self, file_like )
                        cont = self._continuation_pattern.match( next_line )

                    file_like.seek( next_offset )

                    if not next_line:
                        partial = True

                else:
                    file_like.seek( next_offset )
                    line = start_line
            else:
                line = start_line
                partial = True
        else:
            file_like.seek( start_offset )
            line, partial = '', False

        return line, partial
            

        

class ContinuePast( LineGrouper ):
    """
    """
    pass
    
class HaltBefore( LineGrouper ):
    """
    """
    pass

class HaltWith( LineGrouper ):
    """
    """
    pass
