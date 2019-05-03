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
import scalyr_agent.util as scalyr_util
import scalyr_agent.scalyr_logging as scalyr_logging

log = scalyr_logging.getLogger(__name__)

__author__ = 'imron@scalyr.com'

class LogLine(object):
    """A class representing a line from a log file.
    This object will always have a single field 'line' which contains the log line.
    It can also contain two other attributes 'timestamp' which is the timestamp of the
    the log line in nanoseconds since the epoch (defaults to None, in which case the
    current time.time() will be used), and 'attrs' which are optional attributes for the line.
    """
    def __init__(self, line):
        # line is a string
        self.line = line

        # timestamp is a long, counting nanoseconds since Epoch
        # or None to use current time
        self.timestamp = None

        # attrs is a dict of optional attributes to attach to the log message
        self.attrs = None


class LineMatcher(object):
    """ An abstraction for a Line Matcher.
    Reads an entire 'line' from a file like object (e.g. anything implementing Python's
    file interface such as StringIO).  By default it reads just a single line terminated
    by a newline, however subclasses can override the _readline method to provide their
    own definition of what a 'line' is.

    This class also handles partial lines and timeouts between reading a full line.
    """

    @staticmethod
    def create_line_matchers( log_config, read_page_size, max_line_length, line_completion_wait_time ):
        """Creates line matchers based on the config passed in
        see: https://www.scalyr.com/help/parsing-logs#multiline for more info

        If no lineGroupers attribute is found, then it defaults to a single line matcher

        @param log_config: A JsonObject containing the log config
        @param read_page_size: The maximum page size to read - used by line matches that parse a specific line format
        @param max_line_length: The maximum line length of a log message
        @param line_completion_wait_time: The maximum amount of time to wait
            if only a partial line is ready
        @return - a line matcher object based on the config
        """

        line_groupers = log_config['lineGroupers']

        #return a single line matcher if line_groupers is empty or None
        if not line_groupers:
            # return a json line parser if necessary
            if log_config.get( 'parse_lines_as_json', False ):
                return JsonLineMatcher(
                    max_line_length=max_line_length,
                    line_completion_wait_time=line_completion_wait_time,
                    read_page_size=read_page_size,
                    json_message_field=log_config.get( 'json_message_field', 'log' ),
                    json_timestamp_field=log_config.get( 'json_timestamp_field', 'time' )
                )

            # otherwise return a normal parser
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

    def readline( self, file_like, current_time, current_file=None ):
        """
        Reads a line from a `file_like` object

        @return: A LogLine object.
        @rtype: LogLine
        """
        #save the original position
        original_offset = file_like.tell()

        #read a line, and whether or not this is a partial line from the file_like object
        line, partial = self._readline( file_like, current_file=current_file )

        # convert line to a LogLine if necessary
        if not isinstance(line, LogLine):
            line = LogLine(line)

        if len( line.line ) == 0:
            self.__partial_line_time = None
            return line

        # If we have a partial line then we should only
        # return it if sufficient time has passed.
        if partial and len( line.line ) < self.max_line_length:

            if self.__partial_line_time is None:
                self.__partial_line_time = current_time

            if current_time - self.__partial_line_time < self.__line_completion_wait_time:
                # We aren't going to return it so reset buffer back to the original spot.
                file_like.seek( original_offset )
                return LogLine('')
        else:
            self.__partial_line_time = None

        return line

    def _readline( self, file_like, max_length=0, current_file=None ):
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

class JsonLineMatcher( LineMatcher ):
    """
    Parses a line as JSON

    If the `parse_as_json` configuration item is True then
    """
    def __init__( self, max_line_length=5*1024, line_completion_wait_time=5*60, read_page_size=60*1024, json_message_field='log', json_timestamp_field="time" ):
        LineMatcher.__init__( self, max_line_length, line_completion_wait_time )

        self._json_message_field = json_message_field
        self._json_timestamp_field= json_timestamp_field

    def _truncated_log_line( self, line, max_length ):
        """
        Truncates a line if it is greater than `max_length`, and appends a message saying the number of bytes truncted
        @return: A LogLine with the truncated message
        @rtype: LogLine
        """

        line_len = len(line)
        if line_len > max_length:
            line = line[:max_length]
            line += "...truncated %d bytes..." % (line_len - max_length)
        return LogLine( line )

    def _readline( self, file_like, max_length=0, current_file=None ):
        """ Takes a file_like object (e.g. anything conforming to python's file interface
        and attempts to parse the line as JSON.

        This method will attempt to process the line as json, extracting a log message, a timestamp and any
        other remaining fields, all of which are returned as a LogLine object.

        When parsing as json, each line is required to be a fully formed json object, otherwise the full contents of
        the line will be returned unprocessed.

        The configuration options 'json_message_field' and 'json_timestamp_field' are used to specify which field to use
        as the log message, and which field to use for the timestamp.

        'json_message_field' defaults to 'log' and if no field with this name is found, the function will return the
        full line unprocessed.

        'json_timestamp_field' defaults to 'time', and the value of this field is required to be in rfc3339 format
        otherwise an error will occur.  If the field does not exist in the json object, then the agent will use
        the current time instead.  Note, the value specified in the timestamp field might not be the final value uploaded
        to the server, as the agent ensures that the timestamps of all messages are monotonically increasing.  For
        this reason, if the timestamp field is found, a 'raw_timestamp' attributed is also added to the LogLine's attrs.

        All other fields of the json object will be stored in the attrs dict of the LogLine object.

        The method will read up to `read_page_size` bytes from the buffer, and truncate any log message to `max_line_size` bytes.

        @param file_like: a file like object (e.g. StringIO)
        @param max_length: the maximum length to read from the file_like object

        @return: a tuple containing the content read from the file_like object and whether
            this is a partial line or not.  `partial` will only be true if `read_page_size`
            was exceeded and a full json object wasn't found.

        @rtype: (LogLine, bool)
        """

        # set some sensible defaults
        if max_length == 0:
            max_length = self.read_page_size

        if current_file is None:
            current_file = '<unknown>'

        # read from the buffer
        line = file_like.readline( max_length )

        #return early if no line found
        if len( line ) == 0:
            return LogLine( '' ), False

        # check for presence of newline chars to see if this is a partial line
        partial = line[-1] != '\n' and line[-1] != '\r'

        # early abort if this appears to be a partial line
        if partial:
            log.warn("Error parsing line as json for %s.  Log line does not appear to be a full line.  You can increase the buffer size for json line parsing with the global config option `read_page_size`.  The full line will be uploaded to Scalyr: %s" % (current_file, line.decode( "utf-8", 'replace' )),
                     limit_once_per_x_secs=300, limit_key=('bad-json-%s' % current_file))

            return self._truncated_log_line(line, self.max_line_length), partial

        message = None
        attrs = {}
        timestamp = None

        try:
            json = scalyr_util.json_decode( line )

            # go over all json key/values, adding non-message values to a attr dict
            # and the message value to the message variable
            for key, value in json.iteritems():
                if key == self._json_message_field:
                    message = value
                elif key == self._json_timestamp_field:
                    # TODO: need to add support for multiple timestamp formats
                    timestamp = scalyr_util.rfc3339_to_nanoseconds_since_epoch(value)
                    if 'raw_timestamp' not in attrs:
                        attrs['raw_timestamp'] = value
                else:
                    attrs[key] = value

        except Exception, e:
            # something went wrong. Return the full line and log a message
            log.warn("Error parsing line as json for %s.  Logging full line: %s\n%s" % (current_file, e, line.decode( "utf-8", 'replace' )),
                     limit_once_per_x_secs=300, limit_key=('bad-json-%s' % current_file))
            return self._truncated_log_line( line, self.max_line_length ), False


        # if we didn't find a valid message key/value pair
        # throw a warning and treat it as a normal line
        if message is None:
            log.warn("Key '%s' doesn't exist in json object for log %s.  Logging full line. Please check the log's 'json_message_field' configuration" %
                (self._json_message_field, current_file), limit_once_per_x_secs=300, limit_key=('json-message-field-missing-%s' % current_file))
            return self._truncated_log_line( line, self.max_line_length ), False

        # we found a key match for the message field, so use that for the log message
        # and store any other fields in the attr dict
        result = self._truncated_log_line( message, self.max_line_length )
        result.timestamp = timestamp
        if attrs:
            result.attrs = attrs

        return result, False


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

    def _readline( self, file_like, max_length=0, current_file=None ):
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

    def _readline( self, file_like, max_length=0, current_file=None ):
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


