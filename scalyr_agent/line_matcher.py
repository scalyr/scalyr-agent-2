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
# author: Imron Alston <imron@scalyr.com>

import re

__author__ = 'imron@scalyr.com'


class LineMatcher(object):
    """ An abstraction for a Line Matcher.
    Reads an entire 'line' from a file like object (e.g. anything implementing Python's
    file interface such as StringIO).  By default it reads just a single line terminated
    by a newline, however subclasses can override the _readline method to provide their
    own definition of what a 'line' is.

    This class also handles partial lines and timeouts between reading a full line.
    """

    @staticmethod
    def create_line_matchers( log_config, max_line_length, line_completion_wait_time ):
        """Creates line matchers based on the config passed in
        see: https://www.scalyr.com/help/parsing-logs#multiline for more info

        If no lineGroupers attribute is found, then it defaults to a single line matcher

        @param log_config: A JsonObject containing the log config
        @param max_line_length: The maximum amount to read before returning a new line
        @param line_completion_wait_time: The maximum amount of time to wait
            if only a partial line is ready
        @return - a line matcher object based on the config
        """

        line_groupers = log_config['lineGroupers']

        #return a single line matcher if line_groupers is empty or None
        if not line_groupers:
            return LineMatcher( max_line_length, line_completion_wait_time )

        #build a line matcher collection
        result = LineMatcherCollection( max_line_length, line_completion_wait_time )
        for grouper in line_groupers:
            if "start" in grouper:
                if "continueThrough" in grouper:
                    matcher = ContinueThrough( grouper['start'], grouper['continueThrough'], max_line_length, line_completion_wait_time )
                    result.add_matcher( matcher )
                elif "continuePast" in grouper:
                    matcher = ContinuePast( grouper['start'], grouper['continuePast'], max_line_length, line_completion_wait_time )
                    result.add_matcher( matcher )
                elif "haltBefore" in grouper:
                    matcher = HaltBefore( grouper['start'], grouper['haltBefore'], max_line_length, line_completion_wait_time )
                    result.add_matcher( matcher )
                elif "haltWith" in grouper:
                    matcher = HaltWith( grouper['start'], grouper['haltWith'], max_line_length, line_completion_wait_time )
                    result.add_matcher( matcher )
                else:
                    raise Exception( 'Error, no continuation pattern found for line grouper: %s' % str( grouper ) )
            else:
                raise Exception( 'Error, no start pattern found for line grouper: %s' % str( grouper ) )
        return result

    def __init__( self , max_line_length=5*1024, line_completion_wait_time=5*60 ):
        self.max_line_length = max_line_length
        self.__line_completion_wait_time = line_completion_wait_time
        self.__partial_line_time = None

    def readline( self, file_like, current_time ):
        #save the original position
        original_offset = file_like.tell()

        #read a line, and whether or not this is a partial line from the file_like object
        line, partial = self._readline( file_like )

        if len( line ) == 0:
            self.__partial_line_time = None
            return line

        # If we have a partial line then we should only
        # return it if sufficient time has passed.
        if partial and len( line ) < self.max_line_length:

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
        """ Takes a file_like object (e.g. anything conforming to python's file interface
        and returns either a full line, or a partial line.
        @param file_like: a file like object (e.g. StringIO)
        @param max_length: the maximum length to read from the file_like object

        @returns - (string,bool) the content read from the file_like object and whether
        this is a partial line or not.
        """
        if max_length == 0:
            max_length = self.max_line_length

        line = file_like.readline( max_length )
        partial = len( line) > 0 and line[-1] != '\n' and line[-1] != '\r'
        return line, partial

class LineMatcherCollection( LineMatcher ):
    """ A group of line matchers.
    Returns the line from the first line matcher that returns a non-empty line,
    or a single newline terminated line if no matches are found.
    """
    def __init__( self, max_line_length=5*1024, line_completion_wait_time=5*60 ):
        LineMatcher.__init__( self, max_line_length, line_completion_wait_time )
        self.__matchers = []

    def add_matcher( self, matcher ):
        self.__matchers.append( matcher )

    def _readline( self, file_like, max_length=0 ):
        """ Takes a file_like object (e.g. anything conforming to python's file interface
        and checks all self.__matchers to see if any of them match.  If so then return the 
        first matching line, otherwise return a single newline terminated line from the input.

        @param file_like: a file like object (e.g. StringIO)
        @param max_length: the maximum length to read from the file_like object

        @returns - (string,bool) the content read from the file_like object and whether
        this is a partial line or not.
        """

        #default to our own max_line_length if no length has been specified
        if max_length == 0:
            max_length = self.max_line_length

        line = None
        partial = False
        for matcher in self.__matchers:
            offset = file_like.tell()
            #if we have a line, then break out of the loop
            line, partial = matcher._readline( file_like, max_length )
            if line:
                break

            #no match, so reset back to the original offset to prepare for the next line
            file_like.seek( offset )
        
        #if we didn't match any of self.__matchers, then check to see if there is a
        #single line waiting
        if not line:
            line, partial =  LineMatcher._readline( self, file_like, max_length )
            
        return line, partial

class LineGrouper( LineMatcher ):
    """ An abstraction for a LineMatcher that groups multiple lines as a single line.
    Most of the complexity of multiline matching is handled by this class, and subclasses
    are expected to override methods determining when a multiline begins, and whether the
    multiline should continue.
    """
    def __init__( self, start_pattern, continuation_pattern, max_line_length = 5*1024, line_completion_wait_time=5*60 ):
        LineMatcher.__init__( self, max_line_length, line_completion_wait_time )
        self._start_pattern = re.compile( start_pattern )
        self._continuation_pattern = re.compile( continuation_pattern )

    def _readline( self, file_like, max_length=0 ):
        """ Takes a file_like object (e.g. anything conforming to python's file interface
        and returns either a full line, or a partial line.
        @param file_like: a file like object (e.g. StringIO)
        @param max_length: the maximum length to read from the file_like object

        @returns - (string,bool) the content read from the file_like object and whether
        this is a partial line or not.  This function always returns either an empty string ''
        or a complete multi-line string.
        """
        # default to our own max_line_length if no max_length is specified
        if max_length == 0:
            max_length = self.max_line_length

        start_offset = file_like.tell()

        line = ''
        partial = False

        #read a single line of input from the file_like object
        start_line, partial = LineMatcher._readline( self, file_like, max_length )

        #early exit if is a partial line
        if partial:
            return start_line, partial

        #check to see if this line starts a multiline
        start = self._start_line( start_line )
        if start:
            max_length -= len( start_line )
            next_offset = file_like.tell()

            #read the next single line of input
            next_line, next_partial = LineMatcher._readline( self, file_like, max_length )
            if next_line and max_length - len(next_line) <= 0:
                line = start_line + next_line
                partial = False
            elif next_line:

                #see if we are continuing the line
                cont = self._continue_line( next_line )
                if cont:
                    line = start_line
                    # build up a multiline string by looping over all lines for as long as 
                    # the multiline continues, there is still more input in the file and we still have space in our buffer
                    line_max_reached = False

                    while cont and next_line and max_length > 0:
                        line += next_line
                        max_length -= len( next_line )
                        next_offset = file_like.tell()
                        if max_length > 0:
                            next_line, partial = LineMatcher._readline( self, file_like, max_length )
                            # Only check if this line is a continuation if we got the full line.
                            cont = not partial and self._continue_line( next_line )
                            line_max_reached = max_length - len(next_line) <= 0

                    if line_max_reached:
                        # Have to cover a very particular case.  If we reached line max, then no matter what, we add
                        # in the partial line because returning a string with len equal to max_length signals to the
                        # higher level code we hit the max.
                        line += next_line
                        next_offset = file_like.tell()

                    #the previous loop potentially needs to read one line past the end of a multi-line
                    #so reset the file position to the start of that line for future calls.
                    file_like.seek( next_offset )

                    # if we are here and cont is true, it means that we are in the middle of a multiline
                    # but there is no further input, so we have a partial line.
                    # partial = not line_max_reached and (partial or cont)
                    partial = partial or cont

                #first line matched, but the second line failed to continue the multiline
                else:
                    #check if we can match a single line
                    if self._match_single_line():
                        line = start_line
                    #otherwise reset the file position and return an empty line
                    else:
                        file_like.seek( start_offset )
                        line = ''

            # first line started a multiline and now we are waiting for the next line of
            # input, so return a partial line
            else:
                line = start_line
                partial = True

        #the line didn't start a multiline, so reset the file position and return an empty line
        else:
            file_like.seek( start_offset )
            line, partial = '', False

        return line, partial

    def _match_single_line( self ):
        """ Returns whether or not the grouper can match a single line based on the start_pattern.
        Defaults to false
        """
        return False

    def _continue_line( self, line ):
        """ Returns whether or not the grouper should continue matching a multiline.  Defaults to false
        @param line - the next line of input
        """
        return False

    def _start_line( self, line ):
        """ Returns whether or not the grouper should start matching a multiline.
        @param line - the next line of input
        @return bool - whether or not the start pattern finds a match in the input line
        """
        return self._start_pattern.search( line ) != None

class ContinueThrough( LineGrouper ):
    """  A ContinueThrough multiline grouper.
    If the start_pattern matches, then all consecutive lines matching the continuation pattern are included in the line.
    This is useful in cases such as a Java stack trace, where some indicator in the line (such as leading whitespace)
    indicates that it is an extension of the preceeding line.
    """

    def _continue_line( self, line ):
        """
        @param line - the next line of input
        @return bool - True if the line is empty or if the contination_pattern finds a match in the input line
        """
        if not line:
            return True

        return self._continuation_pattern.search( line ) != None
            

class ContinuePast( LineGrouper ):
    """ A ContinuePast multiline grouper.
    If the start pattern matches, then all consecutive lines matching the contuation pattern, plus one additional line,
    are included in the line.
    This is useful in cases where a log message ends with a continuation marker, such as a backslash, indicating
    that the following line is part of the same message.
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
        #if the previous call saw the last line of the pattern, then the next call should always return False
        if self.__last_line:
            self.__last_line = False
            return False

        #see if we match the continuation pattern
        match = self._continuation_pattern.search( line )
        result = True

        # if we are grouping lines and we don't have a match, then we need to flag that the next
        # line will always end the line continuation
        if self.__grouping:
            if not match:
                self.__grouping = False
                self.__last_line = True
        else:
            # we aren't grouping lines so if we don't have a match then the input doesn't match this
            # line grouping pattern, so return False
            if not match:
                result = False

        return result
    
class HaltBefore( LineGrouper ):
    """ A HaltBefore line grouper.
    If the start pattern matches, then all consecutive lines not matching the contuation pattern are included in the line.
    This is useful where a log line contains a marker indicating that it begins a new message.
    """
    def __init__( self, start_pattern, continuation_pattern, max_line_length = 5*1024, line_completion_wait_time=5*60 ):
        LineGrouper.__init__( self, start_pattern, continuation_pattern, max_line_length, line_completion_wait_time )
        self.__match_single = False

    def _start_line( self, line ):
        self.__match_single = LineGrouper._start_line( self, line )
        return self.__match_single

    def _continue_line( self, line ):
        return self._continuation_pattern.search( line ) == None

    def _match_single_line( self ):
        #HaltBefore can potentiall match a single line
        return self.__match_single

class HaltWith( LineGrouper ):
    """ A HaltWith line grouper.
    If the start pattern matches, all consecutive lines, up to and including the first line matching the contuation pattern,
    are included in the line. This is useful where a log line ends with a termination marker, such as a semicolon.
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
        #if we have previously been flagged that the last line has been reached, then return False to stop
        #the line from continuing
        if self.__last_line:
            self.__last_line = False
            return False

        #see if the continuation pattern matches
        cont = self._continuation_pattern.search( line ) == None

        # if it doesn't, then we still continue the line for this input, but we have reached the end ofr
        # the pattern so the next line should end the group
        if not cont:
            self.__last_line = True
            cont = True
        return cont
        

