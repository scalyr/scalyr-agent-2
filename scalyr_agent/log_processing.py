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
# Abstractions that implement the core of the log reading
# and processing logic for the agent.  These abstractions include:
#     LogFileIterator:  Iterates over the lines in the log file at
#         a single file path.  Also handles noticing log rotations
#         and truncations, correctly returning lines from the previous
#         logs.
#
# author: Steven Czerwinski <czerwin@scalyr.com>
import sys

__author__ = 'czerwin@scalyr.com'

import datetime
import errno
import fnmatch
import glob
import os
import random
import re
import string
import threading
import time
import timeit

import scalyr_agent.json_lib as json_lib
import scalyr_agent.scalyr_logging as scalyr_logging
import scalyr_agent.util as scalyr_util

import scalyr_agent.third_party.uuid_tp.uuid as uuid

from scalyr_agent.agent_status import LogMatcherStatus
from scalyr_agent.agent_status import LogProcessorStatus

from scalyr_agent.line_matcher import LineMatcher

from scalyr_agent.scalyr_client import Event

from cStringIO import StringIO
from os import listdir
from os.path import isfile, join


# The maximum allowed size for a line when reading from a log file.
# We do not strictly enforce this -- some lines returned by LogFileIterator may be
#longer than this due to some edge cases.
MAX_LINE_SIZE = 5 * 1024

# The number of seconds we are willing to wait when encountering a log line at the end of a log file that does not
# currently end in a new line (referred to as a partial line).  It could be that the full line just hasn't made it
# all the way to disk yet.  After this time though, we will just return the bytes as a line.
LINE_COMPLETION_WAIT_TIME = 5 * 60

# The number of bytes to read from a file at a time into the buffer.  This must
# always be greater than the MAX_LINE_SIZE
READ_PAGE_SIZE = 64 * 1024

# The minimum time we wait for a log file to reappear on a file system after it has been removed before
# we consider it deleted.
LOG_DELETION_DELAY = 10 * 60

# If we have noticed that new bytes have appeared in a file but we do not read them before this threshold
# is exceeded, then we consider those bytes to be stale and just skip to reading from the end to get the freshest bytes.
COPY_STALENESS_THRESHOLD = 15 * 60

log = scalyr_logging.getLogger(__name__)

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

class LogFileIterator(object):
    """Reads the bytes from a log file at a particular path, returning the lines.

    This is the core abstraction that handles iterating over the lines contained in the
    a log file at a single file path.  If the log file is rotated, then this will
    continue returning the lines from the original file until it is exhausted
    and then iterate over the contents in the new file at the file path.  If the
    log file is truncated, assumes it also represents a log rotation and begins
    iterating over the new contents of the file.

    One of the key features of this abstraction is it can also be rewound, meaning
    you can use the 'tell' method to get the current position of the iterator, iterate past it,
    but then return to it by invoking 'seek'.
    """

    def __init__(self, path, config, log_config, file_system=None, checkpoint=None):
        """

        @param path: The path of the file to read.
        @param config: The configuration object containing values for parameters that govern how logs will be
            processed, such as ``max_line_size``.
        @param log_config: the specific log config for this log file
        @param file_system: The object to use to read the file system.  This is used for testing
            purposes.  If None, then will just use the native file system.
        @param checkpoint: The checkpoint object describing where to pick up reading the file.

        @type path: str
        @type config: scalyr_agent.Configuration
        @type file_system: FileSystem
        @type checkpoint: dict
        """
        # The full path of the log file.
        self.__path = path
        # The representation of the iterator is a little tricky.  To handle log rotation, we actually
        # keep a list of pending files that represent the file handles we have to read from (in order) to get
        # all of the log content.  Typically, this should just be a list of one and two at the most (when a log
        # file has been recently rotated).  However, we implement it as a list because it was easier to think about
        # it generically.
        #
        # The abstraction revolves around the notion of mark position (or just usually referred to as position).
        # This represents the place we are currently reading from, relative to the last call to mark().  However, this
        # position goes across files, meaning mark position 500 might be in the first file (the file where the old
        # just recently rotated log is stored) but position 700 might be in the second file (the current file at the
        # file path for the log).  This would be mean the first file only has 699 bytes, so the 700th comes from the
        # next position.
        #
        # So, much of this abstraction is just about mapping which portions of the files map to which mark positions,
        # and corresponding, which portions of the buffered lines match with which mark positions.
        #
        # Oh yes, we actually use a StringIO buffer to temporarily buffer the bytes from the files.  We read them in
        # in chunks of 64K and then just pull the strings out of them.  A single buffer holds the contents from
        # different files if needed.

        # The objects of this list are of type LogFileIterator.FileState.  Each object has two important fields
        # position_start and position_end which specify where the contents of the file falls in terms of mark position.
        self.__pending_files = []
        # Track what mark generation is being used.  We change the generation every time mark() is invoked.  This
        # allows us to reset the self.__position field to zero so that we can avoid overflowing.
        self.__mark_generation = LogFileIterator.MarkGeneration()

        # The current position we are reading from, relative to the position that was last passed into mark.
        self.__position = 0L
        # The StringIO buffer holding the bytes to be read.
        self.__buffer = None
        # This is a list of LogFileIterator.BufferEntry which maps which portions of the buffer map to which mark
        # positions.
        self.__buffer_contents_index = None

        # If there is no longer a file at the log path, then this marks the time when we first noticed it was gone.
        self.__log_deletion_time = None

        # Has closed been called.
        self.__is_closed = False

        # Files that haven't been modified recently get closed in prepare_for_inactivity
        self.__max_modification_duration = config.close_old_files_duration_in_seconds

        # We are at the 'end' if the log file has been deleted.  This is because we always expect more bytes to be
        # written to it if not.
        self.at_end = False

        self.__max_line_length = config.max_line_size  # Defaults to 5 * 1024
        self.__line_completion_wait_time = config.line_completion_wait_time  # Defaults to 5 * 60
        self.__log_deletion_delay = config.log_deletion_delay  # Defaults to 10 * 60
        self.__page_size = config.read_page_size  # Defaults to 64 * 1024

        self.__parse_as_json = log_config.get('parse_lines_as_json', False)
        self.__json_log_key = log_config.get('json_message_field', 'log' )
        self.__json_timestamp_key = log_config.get('json_timestamp_field', 'time')

        # create the line matcher objects for matching single and multiple lines
        self.__line_matcher = LineMatcher.create_line_matchers(log_config, config.max_line_size,
                                                               config.line_completion_wait_time)

        # Stat just used in testing to verify pages are being read correctly.
        self.page_reads = 0

        # cache modification time to avoid calling stat twice
        # This is in seconds since epoch
        self.__modification_time_raw = time.time()

        # sequence id for this file
        self.__sequence_id = self.__get_unique_id()

        # the value of the sequence number at the last mark, the sequence_number is a combination
        # of this and self.__position
        self.__sequence_number_at_mark = 0

        self.__max_sequence_number = config.max_sequence_number # defaults to 1TB

        # The file system facade that we direct all I/O calls through
        # so that we can insert testing methods in the future if needed.
        self.__file_system = file_system

        if self.__file_system is None:
            self.__file_system = FileSystem()

        # If we have a checkpoint, then iterate over it, seeing if the contents are up-to-date.  If so, then
        # we will pick up from the left off point.
        if checkpoint is not None:
            need_to_close = True
            try:
                if 'sequence_id' in checkpoint:
                    # only set the sequence id if the checkpoint also has a sequence number.
                    # If it's missing the sequence number then something has become corrupted
                    # so we shouldn't use it
                    if 'sequence_number' in checkpoint:
                        self.__sequence_number_at_mark = checkpoint['sequence_number']
                        self.__sequence_id = checkpoint['sequence_id']

                if 'position' in checkpoint:
                    self.__position = checkpoint['position']
                    for state in checkpoint['pending_files']:
                        if not state['is_log_file'] or self.__file_system.trust_inodes:
                            (file_object, file_size, inode) = self.__open_file_by_inode(os.path.dirname(self.__path),
                                                                                        state['inode'])
                        else:
                            (file_object, file_size, inode) = self.__open_file_by_path(self.__path)

                        if file_object is not None:
                            self.__pending_files.append(LogFileIterator.FileState(state, file_object))
                    self.__refresh_pending_files(time.time())
                    need_to_close = False
                else:
                    # Must be a psuedo checkpoint created by the static create_checkpoint method.  This is asking us
                    # to start iterating over the log file at a specific position.
                    self.__position = 0
                    initial_position = checkpoint['initial_position']
                    (file_object, file_size, inode) = self.__open_file_by_path(self.__path)
                    if file_object is not None and file_size >= initial_position:
                        self.__pending_files.append(LogFileIterator.FileState(
                            LogFileIterator.FileState.create_json(0, initial_position, file_size, inode, True),
                            file_object))
                    elif file_object is not None:
                        file_object.close()
                need_to_close = False
            finally:
                if need_to_close:
                    for file_state in self.__pending_files:
                        self.__close_file(file_state)
                    self.__pending_files = []

    def set_line_matcher(self, line_matcher):
        """Sets the line matcher
        Useful for testing
        """
        self.__line_matcher = line_matcher

    def set_parameters(self, max_line_length=None, page_size=None):
        """Sets the various parameters for reading the file.

        This is used for testing purposes.

        @param max_line_length: The maximum allowed line size or None if you do not wish to change the current value.
        @param page_size: How much data is read from the file at a given time. or None if you do not wish to change
            the current value.
        @type max_line_length: int or None
        @type page_size: int or None
        """
        if max_line_length is not None:
            self.__max_line_length = max_line_length

        self.__line_matcher.max_line_length = self.__max_line_length

        if page_size is not None:
            self.__page_size = page_size

    def __get_unique_id( self ):
        """Returns a uuid as a string
        We want uuids as strings mostly as a convenience for json_lib
        """
        return str( uuid.uuid4() )

    def get_sequence( self ):
        """Gets the current sequence id and sequence number of the iterator
        The sequence id is a globally unique number that groups a set of sequence numbers

        @return: A tuple containing a (sequence_id, sequence_number)
        @rtype: (uuid.UUID, int)
        """
        return self.__sequence_id, self.__sequence_number_at_mark + self.__position

    def __increase_sequence_number( self, amount ):
        """Increases the sequence number and resets both the sequence number and the id
        if the sequence number exceeds the maximum value"""
        self.__sequence_number_at_mark += amount
        if self.__sequence_number_at_mark > self.__max_sequence_number:
            self.__sequence_id = self.__get_unique_id()
            self.__sequence_number_at_mark = 0

    def mark(self, position, current_time=None):
        """Marks the specified location of the file.

        After this call, you cannot call the 'seek' method on a position that occurred before this mark.

        Note, this should be called once in a while, otherwise this abstraction will never close file handles
        for old files.

        @param position: The position to mark.
        @param current_time: If not None, the time in seconds past epoch.  Used for testing purposes.

        @type position: LogFileIterator.Position
        @type current_time: float or None
        """
        if current_time is None:
            current_time = time.time()

        # This is a good time to check the state of each of the pending files (seeing if they have grown, shrunk, if
        # the file has rotated, etc.
        self.__refresh_pending_files(current_time)

        new_pending_files = []

        # TODO:  None of this code should throw exceptions, but if it does, we could leave __pending_files
        # in a weird state.  Maybe we should make this more bullet proof.

        # We throw out any __pending_file entries that are before the current mark position or can no longer be
        # read.
        mark_position = position.get_offset_into_buffer()
        for pending_file in self.__pending_files:
            if not pending_file.valid or (mark_position >= pending_file.position_end
                                          and not pending_file.is_log_file):
                self.__close_file(pending_file)
            else:
                new_pending_files.append(pending_file)

        # We zero center the mark position.
        position_delta = mark_position
        for pending_file in new_pending_files:
            pending_file.position_start -= position_delta
            pending_file.position_end -= position_delta

        if self.__buffer is not None:
            for buffer_entry in self.__buffer_contents_index:
                buffer_entry.position_start -= position_delta
                buffer_entry.position_end -= position_delta

        self.__increase_sequence_number(self.__position)
        self.__position -= position_delta

        self.__pending_files = new_pending_files
        self.__mark_generation = LogFileIterator.MarkGeneration(previous_generation=self.__mark_generation,
                                                                position_advanced=position_delta)

    def tell(self, dest=None):
        """Returns a position.

        This position can be used to invoke the 'seek' method later to return to this point.

        @param dest:  If not None, update the specified Position object with the location, rather than creating
            a new Position object.
        @type dest:  LogFileIterator.Position

        @return: An opaque token that represents this position.
        @rtype: LogFileIterator.Position
        """
        if dest is not None:
            dest.mark_generation = self.__mark_generation
            dest.mark_offset = self.__position
            return dest
        else:
            return LogFileIterator.Position(self.__mark_generation, self.__position)

    def seek(self, position):
        """Sets the position to the supposed position value.

        This position must occur after the furthest mark that has been set.

        @param position: The position to move the file to.  This must have been returned by a previous call
            to the 'tell' method.
        @type position: LogFileIterator.Position
        """
        mark_offset = position.get_offset_into_buffer()
        if mark_offset < 0:
            raise Exception('Attempt to seek to a position that occurs before further set mark.')

        buffer_index = self.__determine_buffer_index(mark_offset)
        if buffer_index is not None:
            self.__buffer.seek(buffer_index)
        else:
            self.__reset_buffer()

        self.__position = mark_offset

    def bytes_between_positions(self, first, second):
        """Returns the number of bytes between the two positions.

        Both arguments must have been returned by previous calls to the 'tell' method.  Also, no call
        to the 'mark' method may have occurred between the two calls to 'tell'.

        @param first: The first position
        @param second: The second position.
        @return:  The number of bytes between the two positions.
        @rtype: int
        """
        if first.mark_generation is not second.mark_generation:
            raise Exception('Attempt to compare positions from two different mark generations')

        return second.mark_offset - first.mark_offset

    def readline(self, current_time=None):
        """Returns the next line from the file.

        This will only return a line if an entire line is available (where a line is defined by ending in a newline
        character), except for two cases.  First, if the available number of bytes has exceeded the maximum line size,
        then a line will be returned using the available bytes up to the max line size.  Second, if there are bytes
        available, and sufficient time has past without seeing a newline, then the available lines are returned.

        If the 'parse_as_json' configuration item is True then this function will also attempt to process the line as json,
        extracting a log message, a timestamp and any other remaining fields, all of which are returned as a LogLine object.

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

        @param current_time: If not None, the value to use for the current_time.  Used for testing purposes.
        @type current_time: float
        @return: A LogLine object.  The line attribute will be the line read from the iterator, or an empty string if none is available
        @rtype: LogLine
        """
        if current_time is None:
            current_time = time.time()

        available_buffer_bytes = self.__available_buffer_bytes()
        more_file_bytes_available = self.__more_file_bytes_available()

        # if there are no bytes available in the buffer or on the file
        # shortcircuit return an empty string
        if available_buffer_bytes == 0 and not more_file_bytes_available:
            return LogLine( line='' )

        # Keep our underlying buffer of bytes filled up.
        if self.__buffer is None or (available_buffer_bytes < self.__max_line_length and
                                     more_file_bytes_available):
            self.__fill_buffer(current_time)

        # The following code and the sanity check below were to check for an old bug that was fixed a long time ago.
        # original_buffer_index = self.__buffer.tell()
        # expected_buffer_index = self.__determine_buffer_index(self.__position)
        # Just a sanity check.
        #if len(self.__buffer_contents_index) > 0 and self.__position != self.__buffer_contents_index[-1].position_end:
        #    if expected_buffer_index != original_buffer_index:
        #        assert expected_buffer_index == original_buffer_index, (
        #            'Mismatch between expected index and actual %ld %ld',
        #            expected_buffer_index, original_buffer_index)

        # read a complete line from our line_matcher
        next_line = self.__line_matcher.readline(self.__buffer, current_time)
        result = LogLine(line=next_line)

        if len(result.line) == 0:
            return result

        self.__position = self.__determine_mark_position(self.__buffer.tell())

        # Just a sanity check.
        #if len(self.__buffer_contents_index) > 0:
        #    expected_size = self.__buffer_contents_index[-1].buffer_index_end
        #    actual_size = self.__file_system.get_file_size(self.__buffer)
        #    if expected_size != actual_size:
        #        assert expected_size == actual_size, ('Mismatch between expected and actual size %ld %ld',
        #                                              expected_size, actual_size)

        # check to see if we need to parse the line as json
        if self.__parse_as_json:
            try:
                json = scalyr_util.json_decode( result.line )

                line = None
                attrs = {}
                timestamp = None
                # go over all json key/values, adding non-message values to a attr dict
                # and the message value to the line variable
                for key, value in json.iteritems():
                    if key == self.__json_log_key:
                        line = value
                    elif key == self.__json_timestamp_key:
                        # TODO: need to add support for multiple timestamp formats
                        timestamp = scalyr_util.rfc3339_to_nanoseconds_since_epoch(value)
                        if 'raw_timestamp' not in attrs:
                            attrs['raw_timestamp'] = value
                    else:
                        attrs[key] = value

                # if we didn't find a valid line key/value pair
                # throw a warning and treat it as a normal line
                if line is None:
                    log.warn("Key '%s' doesn't exist in json object for log %s.  Logging full line. Please check the log's 'json_message_field' configuration" %
                        (self.__json_log_key, self.__path), limit_once_per_x_secs=300, limit_key=('json-message-field-missing-%s' % self.__path))
                else:
                    # we found a key match for the message field, so use that for the log line
                    # and store any other fields in the attr dict
                    result.line = line
                    result.timestamp = timestamp
                    if attrs:
                        result.attrs = attrs

            except Exception, e:
                # something went wrong. Return the full line and log a message
                log.warn("Error parsing line as json for %s.  Logging full line: %s\n%s" % (self.__path, str(e), result.line.decode( "utf-8", 'replace' )),
                         limit_once_per_x_secs=300, limit_key=('bad-json-%s' % self.__path))
        return result

    def advance_to_end(self, current_time=None):
        """Advance the iterator to point at the end of the log file and begin reading from there.

        @param current_time: If not None, the value to use for the current_time.  Used for testing purposes.
        @type current_time: float or None

        @return: The number of bytes that were skipped to reach the end.
        """
        if current_time is None:
            current_time = time.time()

        self.__refresh_pending_files(current_time=current_time)

        skipping = self.available
        # Go to the end.
        self.__position += skipping
        # Force us to re-read the memory buffer.
        self.__reset_buffer()

        return skipping

    def scan_for_new_bytes(self, current_time=None):
        """Checks the underlying file to see if any new bytes are available or if the file has been rotated.

        @param current_time: If not None, the value to use for the current_time.  Used for testing purposes.
        @type current_time: float or None

        This does not perform any processing, but does update certain statistics like pending byte count, etc.
        """
        if current_time is None:
            current_time = time.time()
        self.__refresh_pending_files(current_time)

    def prepare_for_inactivity(self, current_time=None):
        """Can be called before times when this iterator instance will not be used for some period of
        time.

        This is necessary to do on some platforms, such as Windows, where open file handles should be closed
        while no real work is going on.

        No calls are necessary to bring it out of this mode.  The next invocation of any method on this
        instance will result in the instance no longer being considered inactive.
        """

        if current_time is None:
            current_time = time.time()

        # This is a pain, but Windows does not allow for anyone to delete a file or its parent directory while
        # someone has a file handle open to it.  So, to be nice, we should close ours.  However, it does limit
        # our ability to detect and more easily handle log rotates.  (Ok, it is not completely true that Windows does
        # not allow for file deletes while someone has a file handle open, but you have to use the native win32 api
        # to be able to open files that work in such a way.. and it still does not allow for the parent dirs to be
        # deleted.)
        close_file = (sys.platform == 'win32')

        # also close any files that haven't been modified for a certain amount of time.
        # This can help prevent errors from having too many open files if we are scanning
        # a directory with many files in it.
        if self.__max_modification_duration:
            try:
                delta = current_time - self.__modification_time_raw
                if delta > self.__max_modification_duration:
                    close_file = True

            except OSError:
                pass

        if close_file:
            for pending in self.__pending_files:
                self.__close_file(pending)

    def close(self):
        """Closes all files open for this iterator.  This should be called before it is discarded."""
        for pending in self.__pending_files:
            self.__close_file(pending)
        self.__pending_files = []
        self.__buffer_contents_index = None
        self.__buffer = None
        self.__is_closed = True

    @property
    def available(self):
        """Returns the number of bytes between the current position and the known end of the file.
        @return: The number of bytes
        @rtype: int
        """
        if self.__pending_files is not None and len(self.__pending_files) > 0:
            return self.__pending_files[-1].position_end - self.__position
        else:
            return 0

    @property
    def last_modification_time(self):
        """Returns the time that the file was last modified.

        Note, you must call ``mark`` first to get the latest time.

        @return:  The time in seconds since epoch.
        @rtype: float
        """
        return self.__modification_time_raw

    def __determine_buffer_index(self, mark_position):
        """Returns the index of the specified position (relative to mark) in the buffer.

        If the buffer does not current hold that position, returns None.  If that position should
        be in the buffer but is not (likely because its file had to be skipped while filling the buffer)
        then it will return the next smallest valid position in the buffer, or None if the end of buffer is reached.

        @param mark_position:  The position
        @type: int

        @return:  The index of the position into the buffer, or None.
        """
        # Make sure we have filled the buffer.
        if self.__buffer is None or len(self.__buffer_contents_index) == 0:
            return None
        # Make sure the overall range could possibly hold the position.
        if self.__buffer_contents_index[0].position_start > mark_position:
            return None
        if self.__buffer_contents_index[-1].position_end <= mark_position:
            return None

        for entry in self.__buffer_contents_index:
            if entry.position_start <= mark_position < entry.position_end:
                return mark_position - entry.position_start + entry.buffer_index_start
            elif entry.position_start > mark_position:
                return entry.buffer_index_start
        return None

    def __determine_mark_position(self, buffer_index):
        """Returns the position (relative to mark) represented by the specified index in the buffer.

        @param buffer_index: The index into the buffer
        @type: int

        @return: The position relative to the last mark.
        """
        # Special case the index representing everything has been read from the buffer to map to the
        # current position end.
        if buffer_index == self.__buffer_contents_index[-1].buffer_index_end:
            return self.__buffer_contents_index[-1].position_end

        for entry in self.__buffer_contents_index:
            if entry.buffer_index_start <= buffer_index < entry.buffer_index_end:
                return entry.position_start + buffer_index - entry.buffer_index_start

        # We should never reach here since the fill_buffer method should construct a buffer_contents_index that
        # spans all the buffer positions.
        assert False, 'Buffer index of %d not found' % buffer_index

    def __available_buffer_bytes(self):
        """Returns the number of bytes available to be read in the buffer.

        @return: The number of bytes available.
        @rtype: int
        """
        if self.__buffer is None or len(self.__buffer_contents_index) == 0:
            return 0
        return self.__buffer_contents_index[-1].buffer_index_end - self.__buffer.tell()

    def __more_file_bytes_available(self):
        """
        @return: True if there are more bytes in the files on disk that can be read into the buffer.
        @rtype: bool
        """
        if self.__pending_files is not None and len(self.__pending_files) > 0:
            if self.__buffer is None or len(self.__buffer_contents_index) == 0:
                return self.__pending_files[-1].position_end > self.__position
            else:
                return self.__pending_files[-1].position_end > self.__buffer_contents_index[-1].position_end
        else:
            return False

    def __reset_buffer(self):
        """Clears the buffer."""
        self.__buffer = None
        self.__buffer_contents_index = None

    def __close_file(self, file_entry):
        """Closes the file in the specified entry.

        @param file_entry: The entry for the file to close.
        @type file_entry: FileState
        """
        if file_entry.file_handle is not None:
            self.__file_system.close(file_entry.file_handle)
            file_entry.file_handle = None

    def __add_entry_for_log_path(self, inode):
        self.__log_deletion_time = None
        if len(self.__pending_files) > 0:
            largest_position = self.__pending_files[-1].position_end
        else:
            largest_position = 0
        (file_handle, file_size, inode) = self.__open_file_by_path(self.__path, starting_inode=inode)

        if file_handle is not None:
            self.__pending_files.append(LogFileIterator.FileState(
                LogFileIterator.FileState.create_json(largest_position, 0, file_size, inode, True), file_handle))

    def __refresh_pending_files(self, current_time):
        """Check to see if __pending_files needs to be adjusted due to log rotation or the
        current log growing.

        This should be called periodically to sync the state of the file system with the metadata
        tracked by this abstraction.

        @param current_time: If not None, the value to use for the current_time.  Used for testing purposes.
        @type current_time: float or None
        """

        has_no_position = len(self.__pending_files) == 0

        # Check to see if the last file in our pending files is still at the path of the real log file.
        if len(self.__pending_files) > 0 and self.__pending_files[-1].is_log_file:
            current_log_file = self.__pending_files[-1]
        else:
            current_log_file = None

        # First, try to see if the file at the log file path still exists, and if so, what's size and inode is.
        try:
            # Get the latest size and inode of the file at __path.
            stat_result = self.__file_system.stat(self.__path)
            latest_inode = stat_result.st_ino
            latest_size = stat_result.st_size
            self.__modification_time_raw = stat_result.st_mtime

            # See if it is rotated by checking out the file handle we last opened to this file path.
            if current_log_file is not None:
                if (current_log_file.last_known_size > latest_size or
                        self.__file_system.trust_inodes and current_log_file.inode != latest_inode):
                    # Ok, the log file has rotated.  We need to add in a new entry to represent this.
                    # But, we also take this opportunity to see if the current entry we had for the log file has
                    # grown in length since the last time we checked it, which is possible.  This is the last time
                    # we have to check it since theorectically, the file would have been fully rotated before a new
                    # log file was created to take its place.
                    if current_log_file.file_handle is not None:
                        current_log_file.last_known_size = max(
                            current_log_file.last_known_size,
                            self.__file_system.get_file_size(current_log_file.file_handle))
                    elif not self.__file_system.trust_inodes:
                        # If we do not have the file handle open (probably because we are on a win32 system) and
                        # we do not trust inodes, then there is no way to get back to the original contents, so we
                        # just mark this file portion as now invalid.
                        current_log_file.valid = False
                    current_log_file.is_log_file = False
                    current_log_file.position_end = current_log_file.position_start + current_log_file.last_known_size
                    # Note, we do not yet detect if current_log_file is actually pointing to the same inode as the
                    # log_path.  This could be true if the log file was copied to another location and then truncated
                    # in place (a commom mode of operation used by logrotate).  If this is the case, then the
                    # file_handle in current_log_file will eventually fail since it will seek to a location no longer
                    # in the file.  We handle that fairly cleanly in __fill_buffer so no need to do it here.  However,
                    # if we want to look for the file where the previous log file was copied, this is where we would
                    # do it.  That is a future feature.

                    # Add in an entry for the file content at log_path.
                    self.__add_entry_for_log_path(latest_inode)
                else:
                    # It has not been rotated.  So we just update the size of the current entry.
                    current_log_file.last_known_size = latest_size
                    current_log_file.position_end = current_log_file.position_start + latest_size
            else:
                # There is no entry representing the file at log_path, but it does exist, so we need to add it in.
                self.__add_entry_for_log_path(latest_inode)
        except OSError, e:
            # The file could have disappeared or the file permissions could have changed such that we can no longer
            # read it.  We have to handle these cases gracefully.  We treat both like it has disappeared from our point
            # of view.
            if e.errno == errno.ENOENT or e.errno == errno.EACCES:
                # The file doesn't exist.  See if we think we have a file handle that is for the log path, and if
                # so, update it to reflect it no longer is.
                if current_log_file is not None:
                    current_log_file.is_log_file = False
                    if current_log_file.file_handle is not None:
                        current_log_file.last_known_size = max(current_log_file.last_known_size,
                                                               self.__file_system.get_file_size(
                                                                   current_log_file.file_handle))
                    current_log_file.position_end = current_log_file.position_start + current_log_file.last_known_size
                if self.__log_deletion_time is None:
                    self.__log_deletion_time = current_time
                self.at_end = current_time - self.__log_deletion_time > self.__log_deletion_delay

            else:
                raise

        if has_no_position and len(self.__pending_files) > 0:
            self.__position = self.__pending_files[-1].position_end

    def __fill_buffer(self, current_time):
        """Fill the memory buffer with up to a page worth of file content read from the pending files.

        @param current_time: If not None, the value to use for the current_time.  Used for testing purposes.
        @type current_time: float or None
        """
        new_buffer = StringIO()
        new_buffer_content_index = []

        # What position we need to read from the files.
        read_position = self.__position

        # Grab whatever is left over in the current buffer.  We first see if the position is even in
        # the buffer.
        buffer_index = self.__determine_buffer_index(self.__position)
        if buffer_index is not None:
            # Copy over the content_index entries.  We have to find where we left off first.
            expected_bytes = 0
            for entry in self.__buffer_contents_index:
                # The easiest way to think about this is that we are shifting the buffer positions of all existing
                # entries by buffer_index.  If that results in a positive end position, then it's still a useful
                # entry.
                entry.buffer_index_start = max(entry.buffer_index_start - buffer_index, 0)
                entry.buffer_index_end -= buffer_index

                if entry.buffer_index_end > 0:
                    new_buffer_content_index.append(entry)
                    expected_bytes += entry.buffer_index_end - entry.buffer_index_start
                    entry.position_start = entry.position_end - (entry.buffer_index_end - entry.buffer_index_start)
                    read_position = entry.position_end

            # Now read the bytes.  We should get the number of bytes we just found in all of the entries.
            tmp = self.__buffer.read()
            new_buffer.write(tmp)
            if expected_bytes != new_buffer.tell():
                assert expected_bytes == new_buffer.tell(), (
                    'Failed to get the right number of left over bytes %d %d "%s"' % (
                    expected_bytes, new_buffer.tell(), tmp))

        leftover_bytes = new_buffer.tell()

        # Just in case a file has been rotated recently, we refresh our list before we read it.
        self.__refresh_pending_files(current_time)

        # Now we go through the files and get as many bytes as we can.
        should_have_bytes = False
        for pending_file in self.__pending_files:
            if read_position < pending_file.position_end:
                should_have_bytes = True
                read_position = max(pending_file.position_start, read_position)
                bytes_left_in_file = pending_file.last_known_size - (read_position - pending_file.position_start)
                content = self.__read_file_chunk(
                    pending_file, read_position,
                    min(self.__page_size - new_buffer.tell(), bytes_left_in_file))
                if content is not None:
                    buffer_start = new_buffer.tell()
                    new_buffer.write(content)
                    buffer_end = new_buffer.tell()
                    new_buffer_content_index.append(LogFileIterator.BufferEntry(read_position,
                                                                                buffer_start,
                                                                                buffer_end - buffer_start))
                read_position = pending_file.position_end
                if new_buffer.tell() >= self.__page_size:
                    break

        buffer_size = new_buffer.tell()

        self.page_reads += 1
        self.__buffer = new_buffer
        self.__buffer.seek(0)
        self.__buffer_contents_index = new_buffer_content_index

        if len(self.__buffer_contents_index) > 0:
            # We may not have been able to read the bytes at the current position if those files have become
            # invalidated.  If so, we need to adjust the position to the next legal one according to the
            # buffer map.
            self.__position = self.__buffer_contents_index[0].position_start
            # TODO:  This warning was firing in normal cases.  Have to re-examine under what conditions this triggers.
            # It might be that if the file is empty, or if it consume all bytes, then we trigger this.
            # log.warn('Had to skip over invalidated portions of the file.  May not be an indicator of a real error. '
            #         'File=%s', self.__path, limit_once_per_x_secs=60, limit_key=('some-invalidated-%s' % self.__path))
        elif should_have_bytes:
            # We only get here if we were not able to read anything into the buffer but there were files that should
            # have had bytes available for reading.  This must mean  all of our file content after the current position
            # is gone.  so, just adjust the position to point to the end as we know it.
            self.__position = self.__pending_files[-1].position_end
            log.warn('File content appears to have disappeared.  This may not be an indicator of a real error. '
                     'File=%s', self.__path, limit_once_per_x_secs=60, limit_key=('some-disappeared-%s' % self.__path))

        # Just a sanity check.
        if len(self.__buffer_contents_index) > 0:
            expected_size = self.__buffer_contents_index[-1].buffer_index_end
            actual_size = buffer_size
            if expected_size != actual_size:
                assert expected_size == actual_size, ('Mismatch between expected and actual size %ld %ld %ld %ld',
                                                      expected_size, actual_size, leftover_bytes,
                                                      actual_size - leftover_bytes)

    def __read_file_chunk(self, file_state, read_position_relative_to_mark, num_bytes):
        """Reads a portion of the file in file_state and returns it.

        @param file_state: The pending file to be read from.
        @param read_position_relative_to_mark: The position to read, relative to the mark.
        @param num_bytes: The number of bytes to read.  If this exact number of bytes cannot be read,
            then None is returned.

        @type file_state: LogFileIterator.FileState
        @type read_position_relative_to_mark: int
        @type num_bytes: int

        @return: If there are bytes to read, returns them, otherwise None.
        @rtype: str or None
        """
        if not file_state.valid:
            return None

        # The file_handle could have been closed if we are on a win32 system and prepare_for_inactivity was closed.
        # If so, we need to re-open it for reading.
        if file_state.file_handle is None:
            (file_state.file_handle, x, y) = self.__open_file_by_path(self.__path, starting_inode=file_state.inode)

        if file_state.file_handle is None:
            file_state.valid = False
            return None

        offset_in_file = read_position_relative_to_mark - file_state.position_start
        self.__file_system.seek(file_state.file_handle, offset_in_file)
        chunk = self.__file_system.read(file_state.file_handle, num_bytes)
        if chunk is None:
            file_state.valid = False
            return None

        if len(chunk) != num_bytes:
            # We did not read the right number of bytes for some reason.  This shouldn't really happen, but
            # we just pretend like we didn't read anything to prevent corrupting logs.
            log.warn('Did not read expected number of bytes. Expected=%ld vs Read=%ld in file %s', num_bytes,
                     len(chunk), self.__path, limit_once_per_x_secs=60,
                     limit_key=('byte_mismatch-%s' % self.__path))
            file_state.valid = False
            return None

        # Check to see if the file has been truncated.. if so, then we probably are not reading what we think
        # we are reading.
        if self.__file_system.get_file_size(file_state.file_handle) < file_state.last_known_size:
            file_state.valid = False
            return None

        return chunk

    def __open_file_by_path(self, file_path, starting_inode=None):
        """Open the file at the specified path and return a file handle and the inode for the file

        Some work is done to ensure that returned inode actually is for the file represented by the file handle.

        @param file_path: The path of the file to open
        @param starting_inode: If not None, then the expected inode of the file.  This is used as a hint, but does
            not guarantee the returned inode will match this.

        @type file_path: str
        @type starting_inode: int

        @return: A tuple of the file handle, the size, and the current inode of the file at that path.
        @rtype: (FileIO, int, int)
        """
        pending_file = None
        try:
            attempts_left = 3

            try:
                # Because there is no atomic way to open a file and get its inode, we have to do a little bit of
                # extra work here.  We look at the inode, open the file, and look at the inode again.. if the
                # inode hasn't changed, then we return it and the file handle.. otherwise, we try again.  We
                # only try three times at most.
                while attempts_left > 0:
                    if starting_inode is None and self.__file_system.trust_inodes:
                        starting_inode = self.__file_system.stat(file_path).st_ino

                    pending_file = self.__file_system.open(file_path)
                    second_stat = self.__file_system.stat(file_path)

                    if not self.__file_system.trust_inodes or starting_inode == second_stat.st_ino:
                        new_file = pending_file
                        pending_file = None
                        return new_file, second_stat.st_size, second_stat.st_ino

                    pending_file.close()
                    pending_file = None
                    attempts_left -= 1
                    starting_inode = None
            except IOError, error:
                if error.errno == 13:
                    log.warn('Permission denied while attempting to read file \'%s\'', file_path,
                             limit_once_per_x_secs=60, limit_key=('invalid-perm' + file_path))
                else:
                    log.warn('Error seen while attempting to read file \'%s\' with errno=%d', file_path, error.errno,
                             limit_once_per_x_secs=60, limit_key=('unknown-io' + file_path))
                return None, None, None
            except OSError, e:
                if e.errno == errno.ENOENT:
                    log.warn('File unexpectantly missing when trying open it')
                else:
                    log.warn('OSError seen while attempting to read file \'%s\' with errno=%d', file_path, e.errno,
                             limit_once_per_x_secs=60, limit_key=('unknown-os' + file_path))
                return None, None, None
        finally:
            if pending_file is not None:
                pending_file.close()

        return None, None, None

    def __open_file_by_inode(self, dir_path, target_inode):
        """Opens the file in the directory at dir_path with the specified inode, if it exists.

        Note, this is a little inefficient because we have to list all the files in the directory, but
        this should not be needed that often.

        @param dir_path: The path of the directory to look in.
        @param target_inode: The inode of the desired file.

        @type dir_path: str
        @type target_inode: int

        @return: A tuple of the file handle, the size, and the current inode of the file at that path.
        @rtype: (FileIO, int, int)
        """
        if not self.__file_system.trust_inodes:
            return None, None, None

        pending_file = None
        attempts_left = 3

        try:
            while attempts_left > 0:
                found_path = None
                # List all files in the directory in the directory.
                for path in self.__file_system.list_files(dir_path):
                    if self.__file_system.stat(path).st_ino == target_inode:
                        found_path = path
                        break

                if found_path is None:
                    return None, None, None

                (pending_file, file_size, opened_inode) = self.__open_file_by_path(found_path, target_inode)
                if opened_inode == target_inode:
                    opened_file = pending_file
                    pending_file = None
                    return opened_file, file_size, opened_inode
                pending_file.close()
                pending_file = None
                attempts_left -= 1

            return None, None, None
        finally:
            if pending_file is not None:
                pending_file.close()

    def get_mark_checkpoint(self):
        """Returns a check point representing the position of the iterator that was last marked.

        This can be used in the constructor to pick up where the iterator last left off.

        This is returned as a dict so that it can be serialized and read back later.

        @return: The check point representing the position of the iterator.
        @rtype: dict
        """
        pending_files = []
        for pending_file in self.__pending_files:
            pending_files.append(pending_file.to_json())
        result = {'position': 0, 'pending_files': pending_files}

        if self.__sequence_id:
            result['sequence_id'] = self.__sequence_id
            result['sequence_number'] = self.__sequence_number_at_mark

        return result

    @staticmethod
    def create_checkpoint(initial_position):
        """Returns a checkpoint object that will begin reading the log file from the specified position.

        @param initial_position: The byte position in the file where copying should begin.

        @return: The check point representing the position of the iterator.
        @rtype: dict
        """
        # We implement this by creating a psuedo checkpoint that we then detect and handle properly
        # in the constructor.
        return {'initial_position': initial_position}

    def get_open_files_count(self):
        """Returns the number of pending file objects that need to be read to return log content.

        This is only used for tests.
        """
        result = 0
        for pending_file in self.__pending_files:
            if pending_file and pending_file.file_handle is not None:
                result += 1
        return result

    class BufferEntry(object):
        """Simple object used to represent a portion of the cache buffer holding a portion of a file."""
        def __init__(self, position_start, buffer_index_start, num_bytes):
            # The mark position start and end for these bytes.
            self.position_start = position_start
            self.position_end = position_start + num_bytes
            # The position of the bytes in the actual buffer.
            self.buffer_index_start = buffer_index_start
            self.buffer_index_end = buffer_index_start + num_bytes

    class FileState(object):
        """Represents a file in the list of pending files for the LogFileIterator."""
        def __init__(self, state_json, file_handle):
            """
            @param state_json: The state for this file, including what mark positions its bytes are in the overall
                LogFileIterator.
            @param file_handle: The open file handle.

            @type state_json: json_lib.JsonObject
            @type file_handle: FileIO
            """
            # True if this file is still a valid portion of the overall iterator.
            self.valid = True
            # The mark position of the bytes in this file.
            self.position_start = state_json['position_start']
            self.position_end = state_json['position_end']
            self.file_handle = file_handle
            if 'inode' in state_json:
                self.inode = state_json['inode']
            self.last_known_size = state_json['last_known_size']
            # Is this file currently at the file path of the log file (or is it a file a rotated log).
            self.is_log_file = state_json['is_log_file']

        def to_json(self):
            """Creates and returns the state serialized to Json.

            @return: The JsonObject containing the serialized state.
            @rtype: json_lib.JsonObject
            """
            result = json_lib.JsonObject(position_start=self.position_start,
                                         position_end=self.position_end,
                                         last_known_size=self.last_known_size,
                                         is_log_file=self.is_log_file)
            if self.inode is not None:
                result['inode'] = self.inode
            return result

        @staticmethod
        def create_json(position_start, initial_offset, file_size, inode, is_log_file):
            """Creates a JsonObject that represents the specified state.

            @param position_start: The start position relative to mark for this file.
            @param initial_offset: The initial offset in the file from where bytes should be read.
            @param file_size: The file size.
            @param inode: The inode for the file.
            @param is_log_file: True if this file is currently at the log file path.

            @type position_start: int
            @type initial_offset: int
            @type file_size: int
            @type inode: int
            @type is_log_file: bool

            @return:  The serialized state.
            @rtype: json_lib.JsonObject
            """
            result = json_lib.JsonObject(position_start=position_start - initial_offset,
                                         position_end=position_start + file_size - initial_offset,
                                         last_known_size=file_size,
                                         is_log_file=is_log_file)
            if inode is not None:
                result['inode'] = inode
            return result

    class Position(object):
        """Represents a position in the iterator."""
        def __init__(self, mark_generation, position):
            # The offset from the mark generation.
            self.mark_offset = position
            # The mark generation that was current when this position was made.
            self.mark_generation = mark_generation

        def get_offset_into_buffer(self):
            """Returns the number of bytes this position is from the most recent mark() call.

            @return:  The offset from the most recent mark call.
            @rtype: int
            """
            return self.mark_generation.get_offset_into_buffer(self.mark_offset)

    class MarkGeneration(object):
        """Represents a generation of positions.  All positions made within the same MarkGeneration are all
        relative to the same location in the file.

        The main job of this abstraction is to keep track of the offsets from one mark generation to the next
        so that we can always calculate the offset, even for positions made with an old generation.

        """
        def __init__(self, previous_generation=None, position_advanced=0):
            """Creates a new mark generation.  There are two forms of this initializer.  The first ever created
            MarkGeneration object for an instance of the LogFileIterator will not have any of the arguments
            supplied to indicate it is the root.  Otherwise, it will have the information supplied from the
            pervious generation.

            @param previous_generation:  The previous mark generation, if there was any.  This must be used if
                there was a previous generation because this will update that generation's offset so that their
                positions point to the correct location.
            @param position_advanced:  The number of bytes that this this generation is offset from the previous
                generation, if there was one.
            @type previous_generation: LogFileIterator.MarkGeneration
            @type position_advanced: int
            """
            # Note, we are very particular that we store references to the next generation, instead of the previous,
            # so that if there are no more Position objects referencing a given MarkGeneration, then that MarkGeneration
            # will be garbage collected.
            #
            # The mark generation that was made next after this one, if any.  If this is None, it indicates this
            # mark generation instance is the current generation.
            self.__next_generation = None
            # The offset of this mark generation's positions to the next one, if there is one.
            self.__offset_to_next = 0
            if previous_generation is not None:
                previous_generation.__next_generation = self
                previous_generation.__offset_to_next = -1 * position_advanced

        def get_offset_into_buffer(self, position):
            """Calculates the offset for the position to the most recent mark call.

            @param position:  The position relative to this mark generation's mark.
            @type position: int
            @return:  The offset of the position to the most recent mark call.
            @rtype: int
            """
            current_generation = self
            while current_generation.__next_generation is not None:
                position += current_generation.__offset_to_next
                current_generation = current_generation.__next_generation
            return position


class LogFileProcessor(object):
    """Performs all processing on a single log file (identified by a path) including returning which lines are ready
    to be sent to the server after applying any sampling and redaction rules.
    """

    def __init__(self, file_path, config, log_config, close_when_staleness_exceeds=None, log_attributes=None,
                 file_system=None, checkpoint=None):
        """Initializes an instance.

        @param file_path: The path of the log file to process.
        @param config:  The configuration object containing parameters that govern how the logs will be processed
            such as ``max_line_length``.
        @param log_config: the log entry config for this specific log file
        @param close_when_staleness_exceeds: If not None, the processor will close the file once the number of seconds
            since the file was last modified exceeds the supplied value.
        @param log_attributes: The attributes to include on all lines copied from this log to the server.
            These are typically the file attributes from the configuration file and include such things as the
            parser for the log, etc.
        @param file_system: The object to use to read and write from the file system.  If None, just uses the
            real file system.  This is used for testing.
        @param checkpoint: An object previously returned by the 'get_checkpoint' method.  This will cause
            the processing to pick up from where it was when the checkpoint was created.

        @type file_path: str
        @type config: scalyr_agent.Configuration
        @type log_attributes: dict or None
        @type file_system: FileSystem
        @type checkpoint: dict or None
        """
        if file_system is None:
            file_system = FileSystem()
        if log_attributes is None:
            log_attributes = {}

        self.__path = file_path
        # To mimic the behavior of the old agent which would use the ``thread_id`` feature of the Scalyr API to
        # group all events from the same log file together, we associate a thread_id (and thread_name) for each
        # LogFileProcessors.  We really should fix this at some point because thread_ids do not persist across sessions
        # which will mean all the vents from a single logical log file will not be put together (when an agent restart
        # happens).  However, this is how the old agent worked and the UI relies on it, so we just keep the old system
        # going for now.
        self.__thread_name = 'Lines for file %s' % file_path
        self.__thread_id = LogFileProcessor.generate_unique_thread_id()

        self.__log_file_iterator = LogFileIterator(file_path, config, log_config, file_system=file_system,
                                                   checkpoint=checkpoint)

        self.__minimum_scan_interval = None
        if 'minimum_scan_interval' in log_config and log_config['minimum_scan_interval'] is not None:
            self.__minimum_scan_interval = log_config['minimum_scan_interval']
        else:
            self.__minimum_scan_interval = config.minimum_scan_interval

        # Trackers whether or not close has been invoked on this processor.
        self.__is_closed = False

        # Tracks whether the processor has recently logged data
        self.__is_active = False

        # The processor should be closed if the staleness of this file exceeds this number of seconds (if not None)
        self.__close_when_staleness_exceeds = close_when_staleness_exceeds

        # The base event that will be used to insert all events from this log.
        self.__base_event = Event(thread_id=self.__thread_id, attrs=log_attributes)
        # The redacter to perform on all log lines from this log file.
        self.__redacter = LogLineRedacter(file_path)
        # The sampler to apply to all log lines from this log file.
        self.__sampler = LogLineSampler(file_path)

        # The lock that must be held when reading all status related fields and __is_closed.
        self.__lock = threading.Lock()
        # The following fields are tracked for generating status information.
        self.__total_bytes_copied = 0L
        self.__total_bytes_skipped = 0L   # Bytes that had to be skipped due to falling too far behind in the log.
        self.__total_bytes_failed = 0L    # Bytes that could not be sent up to server.
        self.__total_bytes_dropped_by_sampling = 0L
        self.__total_bytes_pending = 0L  # The number of bytes that haven't been processed from the log file yet.
        self.__total_bytes_being_processed = 0L  # The number of bytes that are currently being processed.

        self.__total_lines_copied = 0L
        self.__total_lines_dropped_by_sampling = 0L

        self.__total_redactions = 0L

        # the count of sampling and redaction rules. Used to detect when there are none.
        self.__num_redaction_and_sampling_rules = 0

        # The last time the log file was checked for new content.
        self.__last_scan_time = None

        self.__copy_staleness_threshold = config.copy_staleness_threshold  # Defaults to 15 * 60

        self.__max_existing_log_offset_size = config.max_existing_log_offset_size  # Defaults to 100 * 1024 * 1024

        # if we don't have a checkpoint or if the checkpoint doesn't contain pending files
        # then we assume this is a new file and we only go back at most max_log_offset_size bytes
        if checkpoint is None or 'pending_files' not in checkpoint:
            self.__max_log_offset_size = config.max_log_offset_size  # Defaults to 5 * 1024 * 1024
        else:
            # otherwise this is an existing file so we can go back at most
            # max_existing_log_offset_size bytes
            self.__max_log_offset_size = self.__max_existing_log_offset_size

        self.__last_success = None

        self.__disable_processing_new_bytes = config.disable_processing_new_bytes

    def add_missing_attributes( self, attributes ):
        """ Adds items attributes to the base_event's attributes if the base_event doesn't
        already have those attributes set
        """
        self.__base_event.add_missing_attributes( attributes )


    def set_max_log_offset_size( self, max_log_offset_size ):
        """Sets the max_log_offset_size.

        Used for testing
        """
        self.__max_log_offset_size = max_log_offset_size

    def generate_status(self):
        """Generates and returns a status object for this particular processor.

        @return: The status object, including such fields as the total number of bytes copied, etc.
        @rtype: LogProcessorStatus
        """
        try:
            self.__lock.acquire()
            result = LogProcessorStatus()
            result.log_path = self.__path
            result.last_scan_time = self.__last_scan_time

            result.total_bytes_copied = self.__total_bytes_copied
            result.total_bytes_pending = self.__total_bytes_pending + self.__total_bytes_being_processed

            result.total_bytes_skipped = self.__total_bytes_skipped
            result.total_bytes_failed = self.__total_bytes_failed
            result.total_bytes_dropped_by_sampling = self.__total_bytes_dropped_by_sampling
            result.total_lines_copied = self.__total_lines_copied
            result.total_lines_dropped_by_sampling = self.__total_lines_dropped_by_sampling
            result.total_redactions = self.__total_redactions
            result.total_bytes_skipped = self.__total_bytes_skipped

            return result
        finally:
            self.__lock.release()

    def is_closed(self):
        """
        @return: True if the processor has been closed.
        @rtype: bool
        """
        self.__lock.acquire()
        result = self.__is_closed
        self.__lock.release()
        return result

    @property
    def is_active( self ):
        return self.__is_active

    def set_inactive( self ):
        self.__is_active = False

    @property
    def log_path(self):
        """
        @return:  The log file path
        @rtype: str
        """
        # TODO:  Change this to just a regular property?
        return self.__path

    # Success results for the callback returned by perform_processing.
    SUCCESS = 1
    FAIL_AND_DROP = 2
    FAIL_AND_RETRY = 3

    def perform_processing(self, add_events_request, current_time=None):
        """Scans the available lines from the log file, processes them using the configured redacters and samplers
         and appends the lines that emerge to add_events_request.

        @param add_events_request:  The request to add the resulting lines/events to.  This request will
            eventually be sent to the server.
        @param current_time:  If not None, the value to use as the current_time.  Used for testing.

        @type add_events_request: scalyr_client.AddEventsRequest
        @type current_time: float or None

        @return A tuple containing two elements:  a callback function to invoke when the result of sending the
            events to the server is known, and a bool indicating if the buffer has been filled and could not
            accept new events.  The call function takes a single argument that is an int which can
            only have values of SUCCESS, FAIL_AND_DROP, and FAIL_AND_RETRY.  If SUCCESS is passed in, then the
            events are marked as successfully sent.  If FAIL_AND_DROP is passed in, then the events are
            marked as consumed but not successfully processed.  If FAIL_AND_RETRY is passed in, then the processor
            is rolled back and the events will be retried for processing later on.  The function, when invoked,
            will return True if the log file should be considered closed and no further processing will be needed.
            The caller should no longer use this processor instance in this case.
        @rtype: (function(int) that returns a bool, bool)
        """
        if current_time is None:
            current_time = time.time()

        # If this is our first time processing this log file, just pretend like we had a recent success.
        if self.__last_success is None:
            self.__last_success = current_time

        self.__lock.acquire()
        last_scan_time = self.__last_scan_time
        self.__lock.release()

        # see if we need to scan for new bytes yet
        scan = True
        if last_scan_time is not None and self.__minimum_scan_interval is not None:
            scan = (current_time - last_scan_time > self.__minimum_scan_interval)

        # scan for new bytes
        if scan:
            self.__log_file_iterator.scan_for_new_bytes(current_time=current_time)
            self.__lock.acquire()
            self.__last_scan_time = current_time
            self.__lock.release()

        # Check to see if we haven't had a success in enough time.  If so, then we just skip ahead.
        if current_time - self.__last_success > self.__copy_staleness_threshold:
            self.skip_to_end('Too long since last success.  Last success was \'%s\'' % scalyr_util.format_time(
                self.__last_success), 'skipForStaleness', current_time=current_time)
        # Also make sure we are at least within 5MB of the tail of the log.  If not, then we skip ahead.
        elif self.__log_file_iterator.available > self.__max_log_offset_size:
            self.skip_to_end(
                'Too far behind end of log.  Num of bytes to end is %ld' % self.__log_file_iterator.available,
                'skipForTooFarBehind', current_time=current_time)

        # Keep track of both the position in the iterator and where we are about to add new events to the request,
        # in case we have to roll it back.
        original_position = self.__log_file_iterator.tell()
        original_events_position = add_events_request.position()

        start_process_time = 0.0

        # Some performance analysis timings we use from time to time.
        # fast_get_time = timeit.default_timer
        # start_process_time = fast_get_time()

        position = self.__log_file_iterator.tell()

        # noinspection PyBroadException
        try:
            # Keep track of some states about the lines/events we process.
            bytes_read = 0L
            lines_read = 0L
            bytes_copied = 0L
            lines_copied = 0L
            total_redactions = 0L
            lines_dropped_by_sampling = 0L
            bytes_dropped_by_sampling = 0L

            time_spent_reading = 0.0
            time_spent_serializing = 0.0

            buffer_filled = False
            added_thread_id = False

            # Keep looping, add more events until there are no more or there is no more room.
            while True:
                # debug leak
                if self.__disable_processing_new_bytes:
                    log.log(scalyr_logging.DEBUG_LEVEL_0, 'Processing new bytes disabled for %s' % self.__path,
                                   limit_once_per_x_secs=60, limit_key=('disable-processing-%s' % self.__path))
                    break

                position = self.__log_file_iterator.tell(dest=position)

                #time_spent_reading -= fast_get_time()
                line_object = self.__log_file_iterator.readline(current_time=current_time)
                line_len = len(line_object.line)
                #time_spent_reading += fast_get_time()

                # This means we hit the end of the file, or at least there is not a new line yet available.
                if line_len == 0:
                    break

                # We have a line, process it and see what comes out.
                bytes_read += line_len
                lines_read += 1L

                if self.__num_redaction_and_sampling_rules > 0:
                    sample_result = self.__sampler.process_line(line_object.line)
                    if sample_result is None:
                        lines_dropped_by_sampling += 1L
                        bytes_dropped_by_sampling += line_len
                        continue

                    (line_object.line, redacted) = self.__redacter.process_line(line_object.line)
                    line_len = len(line_object.line)
                else:
                    sample_result = 1.0
                    redacted = False

                if line_len > 0:
                    # Try to add the line to the request, but it will let us know if it exceeds the limit it can
                    # send.
                    sequence_id, sequence_number = self.__log_file_iterator.get_sequence()

                    #time_spent_serializing += fast_get_time()
                    event = self.__create_events_object(line_object, sample_result)
                    if not add_events_request.add_event(event, timestamp=line_object.timestamp, sequence_id=sequence_id, sequence_number=sequence_number):
                        #time_spent_serializing -= fast_get_time()

                        self.__log_file_iterator.seek(position)
                        buffer_filled = True
                        break

                    #time_spent_serializing -= fast_get_time()

                    # Try to add the thread id if we have not done so far.  This should only be added once per file.
                    if not added_thread_id:
                        if not add_events_request.add_thread(self.__thread_id, self.__thread_name):
                            # If we got here, it means we did not have enough room to add both the thread id
                            # and the event into the events request.  So, we have to remove the event we just
                            # added to the add_events_request by setting the position to the original.
                            add_events_request.set_position(original_events_position)
                            self.__log_file_iterator.seek(position)
                            buffer_filled = True
                            break
                        added_thread_id = True

                if redacted:
                    total_redactions += 1L
                bytes_copied += line_len
                lines_copied += 1

            if not self.__is_active:
                self.__is_active = bytes_read > 0

            final_position = self.__log_file_iterator.tell()

            # start_process_time = fast_get_time() - start_process_time
            #add_events_request.increment_timing_data(serialization_time=time_spent_serializing,
            #                                         reading_time=time_spent_reading,
            #                                         process_time=start_process_time,
            #                                         lines=lines_read, bytes=bytes_read, files=1)
            add_events_request.increment_timing_data(lines=lines_read, bytes=bytes_read, files=1)

            # To do proper account when an RPC has failed and we retry it, we track how many bytes are
            # actively being processed.  We will update this once the completion callback has been invoked.
            self.__lock.acquire()
            self.__total_bytes_being_processed = bytes_copied
            self.__total_bytes_pending = self.__log_file_iterator.available
            self.__lock.release()

            # We have finished a processing loop.  We probably won't be calling the iterator for a while, so let it
            # do some clean up work until the next time we need it.
            self.__log_file_iterator.prepare_for_inactivity( current_time )

            # If we get here on what was a new file, then the file is now an existing file, so set the maximum log
            # offset size to use the size for existing files
            self.__max_log_offset_size = self.__max_existing_log_offset_size

            # Define the callback to return.
            def completion_callback(result):
                """Invoked by the caller to indicate if the events were successfully sent to server, and if not,
                what to do.

                @param result: Must be one of SUCCESS, FAIL_AND_DROP, FAIL_AND_RETRY.
                @type result: int
                @return: True if the processor has been closed because it is finished and the caller should no longer
                    use it.
                @rtype: bool
                """
                try:
                    #log.log(scalyr_logging.DEBUG_LEVEL_3, 'Result for advancing %s was %s', self.__path, str(result))
                    self.__lock.acquire()
                    # Zero out the bytes we were tracking as they were in flight.
                    self.__total_bytes_being_processed = 0

                    # If it was a success, then we update the counters and advance the iterator.
                    if result == LogFileProcessor.SUCCESS:
                        self.__total_bytes_copied += bytes_copied
                        bytes_between_positions = self.__log_file_iterator.bytes_between_positions( original_position, final_position)
                        self.__total_bytes_skipped +=  bytes_between_positions - bytes_read

                        self.__total_bytes_dropped_by_sampling += bytes_dropped_by_sampling
                        self.__total_bytes_pending = self.__log_file_iterator.available
                        self.__total_lines_copied += lines_copied
                        self.__total_lines_dropped_by_sampling += lines_dropped_by_sampling
                        self.__total_redactions += total_redactions
                        self.__last_success = current_time

                        # Do a mark to cleanup any state in the iterator.  We know we won't have to roll back
                        # to before this point now.
                        # Only mark files that have logged new bytes to prevent stat'ing unused files
                        if bytes_between_positions > 0:
                            self.__log_file_iterator.mark(final_position, current_time=current_time)

                        if self.__log_file_iterator.at_end or self.__should_close_because_stale(current_time):
                            self.__log_file_iterator.close()
                            self.__is_closed = True
                            return True
                        else:
                            return False
                    elif result == LogFileProcessor.FAIL_AND_DROP:
                        self.__log_file_iterator.mark(final_position, current_time=current_time)
                        self.__total_bytes_pending = self.__log_file_iterator.available
                        self.__total_bytes_failed += bytes_read
                        return False
                    elif result == LogFileProcessor.FAIL_AND_RETRY:
                        self.__log_file_iterator.seek(original_position)
                        self.__total_bytes_pending = self.__log_file_iterator.available
                        return False
                    else:
                        raise Exception('Invalid result %s' % str(result))
                finally:
                    self.__lock.release()

            #log.log(scalyr_logging.DEBUG_LEVEL_3, 'Scanned %s and found %ld bytes for copying.  Buffer filled=%s.',
                    #self.__path, bytes_copied, str(buffer_filled))

            return completion_callback, buffer_filled
        except Exception:
            log.exception('Failed to copy lines from \'%s\'.  Will re-attempt lines.', self.__path,
                          error_code='logCopierFailed')
            log.log(scalyr_logging.DEBUG_LEVEL_3, 'Failed while scanning \'%s\' for new bytes.', self.__path)

            # Roll back the positions if something happened.
            self.__log_file_iterator.seek(original_position)
            add_events_request.set_position(original_events_position)

            return None, False

    def __should_close_because_stale(self, current_time):
        """Returns true if the processor should be closed because the last time the file it is monitoring has been
        modified exceeds the number of seconds in ``__close_when_staleness_exceeds``.

        This will always return False if ``__close_when_staleness_exceeds`` is None.

        @param current_time: The current time
        @type current_time: float
        @return:  True if it should be closed due to staleness.
        @rtype: bool
        """
        if self.__close_when_staleness_exceeds is None:
            return False

        return (current_time - self.__log_file_iterator.last_modification_time) > self.__close_when_staleness_exceeds

    def skip_to_end(self, message, error_code, current_time=None):
        """Advances the iterator to the end of the log file due to some error.

        @param message: The error message to include in the log to explain why we had to skip to the end.
        @param error_code: The error code to include
        @param current_time: If not None, the value to use as the current time.  Used for testing.

        @type message: str
        @type error_code: str
        @type current_time: float
        """
        if current_time is None:
            current_time = time.time()
        skipped_bytes = self.__log_file_iterator.advance_to_end(current_time=current_time)

        self.__lock.acquire()
        self.__total_bytes_skipped += skipped_bytes
        self.__lock.release()

        log.warn('Skipped copying %ld bytes in \'%s\' due to: %s', skipped_bytes, self.__path, message,
                 error_code=error_code)

    def add_sampler(self, match_expression, sampling_rate):
        """Adds a new sampling rule that will be applied after all previously added sampling rules.

        @param match_expression: The regular expression that must match any portion of a log line
        @param sampling_rate: The rate to include any line that matches the expression in the results sent to the
            server.
        """
        self.__num_redaction_and_sampling_rules += 1
        self.__sampler.add_rule(match_expression, sampling_rate)

    def add_redacter(self, match_expression, replacement, hash_salt=''):
        """Adds a new redaction rule that will be applied after all previously added redaction rules.

        @param match_expression: The regular expression that must match the portion of the log line that will be
            redacted.
        @param replacement: The text to replace the matched expression with. You may use \1, \2, etc to use sub
            expressions from the match regular expression.
        @param hash_salt: The salt used for hashing, only if hashing group replacement is used

        @type hash_salt: str
        """
        self.__num_redaction_and_sampling_rules += 1
        self.__redacter.add_redaction_rule(
            match_expression, replacement, hash_salt
        )

    def __create_events_object(self, line_object, sampling_rate):
        """Returns the events object that can be sent to the server for this log to insert the specified message.

        @param line_object: A LogLine containing a message, to be placed in attrs.message, plus an optional timestamp and attrs dict.
        @param sampling_rate:  The sampling rate that had been used to decide if the event_message should be
            sent to the server.

        @return: An scalyr_client.Event object containing the correct fields that when serialized to JSON and added to
            an addEvents request will insert the specified event along with any log attributes associated with this log.
            In particular, when serialized, it will contain the attrs field.  The ts (timestamp) and sequence-related
            fields are not set because the AddEventRequest object will set them.  The attrs JSON field will be another
            JSON containing all of the log attributes for this log as well as a 'message' field containing event_message.
        """
        result = Event(base=self.__base_event)
        if line_object.attrs:
            result.add_missing_attributes( line_object.attrs )
        result.set_message(line_object.line)
        if sampling_rate != 1.0:
            result.set_sampling_rate(sampling_rate)
        return result

    def scan_for_new_bytes(self, current_time=None):
        """Checks the underlying file to see if any new bytes are available or if the file has been rotated.

        This does not perform any processing, but does update certain statistics like pending byte count, etc.

        It is useful to be invoked now and then to sync up the file system state with the in-memory data tracked
        about the file such as its current length.

        @param current_time: If not None, the value to use as the current time.  Used for testing.
        @type current_time: float
        """
        if current_time is None:
            current_time = time.time()
        self.__log_file_iterator.scan_for_new_bytes(current_time)
        self.__lock.acquire()
        self.__last_scan_time = current_time
        self.__total_bytes_pending = self.__log_file_iterator.available
        self.__lock.release()

    @property
    def total_bytes_pending( self ):
        result = 0
        self.__lock.acquire()
        result = self.__total_bytes_pending
        self.__lock.release()
        return result

    def close(self):
        """Closes the processor, closing all underlying file handles.

        This does nothing if the processor is already closed.
        """
        try:
            self.__lock.acquire()
            if not self.__is_closed:
                self.__log_file_iterator.close()
                self.__is_closed = True
        finally:
            self.__lock.release()

    def get_checkpoint(self):
        return self.__log_file_iterator.get_mark_checkpoint()

    @staticmethod
    def create_checkpoint(initial_position):
        """Returns a checkpoint object that will begin reading a log file from the specified position.

        @param initial_position: The byte position in the file where copying should begin.
        """
        return LogFileIterator.create_checkpoint(initial_position)

    # Variables used to implement the static method ``generate_unique_thread_id``.
    __thread_id_lock = threading.Lock()
    __thread_id_counter = 0

    @staticmethod
    def generate_unique_thread_id():
        """Generates and returns a unique thread id that has not been issued before by this agent.

        This is used to assign a unique thread id to all events coming from a single LogFileProcessor instance.
        @rtype: str
        """
        LogFileProcessor.__thread_id_lock.acquire()
        LogFileProcessor.__thread_id_counter += 1
        new_id = LogFileProcessor.__thread_id_counter
        LogFileProcessor.__thread_id_lock.release()

        return 'log_%d' % new_id


class LogLineSampler(object):
    """Encapsulates all of the configured sampling rules to perform on lines from a single log file.

    It contains a list of filters, specified as regular expressions and a corresponding pass rate
    (a number between 0 and 1 inclusive) for each filter.  When a line is processed, each filter
    regular expression is matched against the line in order.  If a expression matches any portion of the
    line, then its pass rate is used to determine if that line should be included in the output.  A random number
    is generated and if it is greater than the filter's pass rate, then the line is included.  The first filter that
    matches a line is used.
    """

    def __init__(self, log_file_path):
        """Initializes an instance for a single file.

        @param log_file_path: The full path for the log file that the sampler will be applied to.
        """
        self.__log_file_path = log_file_path
        self.__sampling_rules = []
        self.total_passes = 0L

    def process_line(self, input_line):
        """Performs all configured sampling operations on the input line and returns whether or not it should
        be kept.  If it should be kept, then a float is returned indicating the sampling rate of the rule that
        allowed it to be included.  Otherwise, None.

        See the class description for the algorithm that determines which lines are returned.

        @param input_line: The input line.

        @return: A float between 0 and 1 if the input line should be kept, the sampling rate of the rule that allowed
            it to be included.  Otherwise, None.
        """

        if len(self.__sampling_rules) == 0:
            self.total_passes += 1L
            return 1.0

        sampling_rule = self.__find_first_match(input_line)
        if sampling_rule is None:
            return 1.0
        else:
            sampling_rule.total_matches += 1L
            if self.__flip_biased_coin(sampling_rule.sampling_rate):
                sampling_rule.total_passes += 1L
                self.total_passes += 1L
                return sampling_rule.sampling_rate
        return None

    def add_rule(self, match_expression, sample_rate):
        """Appends a new sampling rule.  Any line that contains a match for match expression will be sampled with
        the specified rate.

        @param match_expression: The regular expression that much match any part of a line to activie the rule.
        @param sample_rate: The sampling rate, expressed as a number between 0 and 1 inclusive.
        """
        self.__sampling_rules.append(SamplingRule(match_expression, sample_rate))

    def __find_first_match(self, line):
        """Returns the first sampling rule to match the line, if any.

        @param line: The input line to match against.

        @return: The first sampling rule to match any portion of line.  If none
            match, then returns None.
        """
        for sampling_rule in self.__sampling_rules:
            if sampling_rule.match_expression.search(line) is not None:
                return sampling_rule
        return None

    def __flip_biased_coin(self, bias):
        """Flip a biased coin and return True if it comes up head.

        @param bias: The probability the coin will come up heads.
        @type bias: float
        @return:  True if it comes up heads.
        @rtype: bool
        """
        if bias == 0:
            return False
        elif bias == 1:
            return True
        else:
            return self._get_next_random() < bias

    def _get_next_random(self):
        """Returns a random between 0 and 1 inclusive.

        This is used for testing.
        """
        return random.random()


class SamplingRule(object):
    """Encapsulates all data for one sampling rule."""

    def __init__(self, match_expression, sampling_rate):
        self.match_expression = re.compile(match_expression)
        self.sampling_rate = sampling_rate
        self.total_matches = 0
        self.total_passes = 0


class LogLineRedacter(object):
    """Encapsulates all of the configured redaction rules to perform on lines from a single log file.

    It contains a list of redaction filters, specified as regular expressions, that are applied against
    all lines being processed, in order.  If a redaction filter's regular expression matches any portion
    of the line, the matched text is replaced with the text specified by the redaction rule, which may
    include portions of the matched text using the $1, etc operators from the regular expression.

    Redaction rules can match each line multiple times.
    """

    # Indicator in the replacement text[optional] to hash the group content.
    # eg replacement string of foo\\1=\\H2 will replace the second group with its hashed content
    HASH_GROUP_INDICATOR = "H"

    def __init__(self, log_file_path):
        """Initializes an instance for a single file.

        @param log_file_path: The full path for the log file that the sampler will be applied to.
        """
        self.__log_file_path = log_file_path
        self.__redaction_rules = []
        self.total_redactions = 0

    def process_line(self, input_line):
        """Performs all configured redaction rules on the input line and returns the results.

        See the class description for the algorithm that determines how the rules are applied.

        @param input_line: The input line.

        @return: A sequence of two elements, the line with the redaction applied (if any) and True or False
            indicating if a redaction was applied.
        """

        if len(self.__redaction_rules) == 0:
            return input_line, False

        modified_it = False

        for redaction_rule in self.__redaction_rules:
            (input_line, redaction) = self.__apply_redaction_rule(input_line, redaction_rule)
            modified_it = modified_it or redaction

        return input_line, modified_it

    def add_redaction_rule(self, redaction_expression, replacement_text, hash_salt=''):
        """Appends a new redaction rule to this instance.

        @param redaction_expression: The regular expression that must match some portion of the line.
        @param replacement_text: The text to replace the matched text with. May include \1 etc to use a portion of the
            matched text.
        @param hash_salt: [optional] If hashing is set, then the cryptographic salt to be used

        @type hash_salt: str
        """

        self.__redaction_rules.append(
            RedactionRule(
                redaction_expression, replacement_text, hash_salt=hash_salt
            )
        )

    def __apply_redaction_rule(self, line, redaction_rule):
        """Applies the specified redaction rule on line and returns the result.

        @param line: The input line
        @param redaction_rule: The redaction rule.

        @return: A sequence of two elements, the line with the redaction applied (if any) and True or False
            indicating if a redaction was applied.
        """

        def __replace_groups_with_hashed_content(re_ex, replacement_ex, line):

            _matches = re.finditer(re_ex, line)

            if not _matches:
                # if no matches, return the `line` as such
                return line, None

            replacement_matches = 0

            # last_match_index captures the index of the last match position
            # that will help us rebuild the original string with replaced pattern
            last_match_index = 0
            replaced_string = ""

            for _match in _matches:
                _groups = _match.groups()
                # `replaced_group` will initially hold the replacement expression `replacement_ex`
                # and the group expressions like \\1 or \\H2 etc. will be substituted with the actual
                # group value or the hashed group value depending on whether the group needs hashing or not
                # Once substituted, this can be used to replace the matched string portion
                replaced_group = replacement_ex
                for _group_index, _group in enumerate(_groups):
                    # for each group in a match, replace the `replacement_ex` with either its `group` content, or
                    # the hash of the `group` depending on the hash indicator \\1 vs \\H1 etc.
                    group_hash_indicator = "\{}{}".format(
                        LogLineRedacter.HASH_GROUP_INDICATOR,
                        _group_index + 1
                    )
                    replacement_matches += 1
                    if group_hash_indicator in replacement_ex:
                        # the group needs to be hashed
                        replaced_group = replaced_group.encode('utf8')
                        replaced_group = replaced_group.replace(
                            group_hash_indicator,
                            scalyr_util.md5_digest(_group + redaction_rule.hash_salt),
                            1
                        )
                    else:
                        # the group does not need to be hashed
                        replaced_group = replaced_group.replace("\{}".format(_group_index + 1), _group, 1)
                # once we have formed the replacement expression, we just need to replace the matched
                # portion of the `line` with the `replaced_group` that we just built
                replaced_string = replaced_string + line[last_match_index: _match.start()]
                replaced_string += replaced_group
                # forward the last match index to the end of the match group
                last_match_index = _match.end()
            return replaced_string, replacement_matches

        try:
            if redaction_rule.hash_redacted_data:
                # out of these matched groups,
                (result, matches) = __replace_groups_with_hashed_content(
                    redaction_rule.redaction_expression,
                    redaction_rule.replacement_text,
                    line
                )
            else:
                (result, matches) = re.subn(
                    redaction_rule.redaction_expression, redaction_rule.replacement_text, line
                )
        except UnicodeDecodeError:
            # if our line contained non-ascii characters and our redaction_rules
            # are unicode, then the previous replace will fail.
            # Try again, but this time convert the line to utf-8, replacing any
            # invalid characters with the unicode replacement character
            if redaction_rule.hash_redacted_data:
                (result, matches) = __replace_groups_with_hashed_content(
                    redaction_rule.redaction_expression,
                    redaction_rule.replacement_text,
                    line.decode('utf-8', 'replace')
                )
            else:
                (result, matches) = re.subn(
                    redaction_rule.redaction_expression,
                    redaction_rule.replacement_text,
                    line.decode('utf-8', 'replace')
                )

        if matches > 0:
            # if our result is a unicode string, lets convert it back to utf-8
            # to avoid any conflicts
            if type(result) == unicode:
                result = result.encode('utf-8')
            self.total_redactions += 1
            redaction_rule.total_lines += 1
            redaction_rule.total_redactions += matches
        return result, matches > 0


class RedactionRule(object):
    """Encapsulates all data for one redaction rule."""

    def __init__(self, redaction_expression, replacement_text, hash_salt=''):
        self.redaction_expression = re.compile(redaction_expression)
        self.replacement_text = replacement_text
        self.hash_salt = hash_salt
        self.total_lines = 0
        self.total_redactions = 0

    @property
    def hash_redacted_data(self):
        return "\{}".format(LogLineRedacter.HASH_GROUP_INDICATOR) in self.replacement_text


class LogMatcher(object):
    """Performs all matching and processing logic to handle a single log entry in the configuration file.

    The single log entry specifies the path for the log file that should be collected (where the path is
    possibly a glob) along with any sampling, redactions rules that should be applied to the log lines of
    that log file.  Finally, it also includes attributes that should be included with each log line from that
    log when sent to the server.
    """
    def __init__(self, overall_config, log_entry_config, file_system=None):
        """Initializes an instance.
        @param overall_config:  The configuration object containing parameters that govern how the logs will be
            processed such as ``max_line_length``.
        @param log_entry_config: The configuration entry from the logs array in the agent configuration file,
            which specifies the path for the log file, as well as redaction rules, etc.
        @param file_system: The object to use to read and write from the file system.  If None, just uses the
            real file system.  This is used for testing.

        @type overall_config: scalyr_agent.Configuration
        @type log_entry_config: dict
        @type file_system: FileSystem
        """
        if file_system is None:
            self.__file_system = FileSystem()
        else:
            self.__file_system = file_system
        self.__overall_config = overall_config
        self.__log_entry_config = log_entry_config
        self.log_path = self.__log_entry_config['path']

        # Determine if we should be ignoring stale files (meaning we don't track them at all).
        # If we should not be ignoring them, then self.__stale_threshold_secs will be set to a number.
        if 'ignore_stale_files' in self.__log_entry_config and self.__log_entry_config['ignore_stale_files']:
            if 'staleness_threshold_secs' in self.__log_entry_config:
                self.__stale_threshold_secs = self.__log_entry_config['staleness_threshold_secs']
            else:
                self.__stale_threshold_secs = 300
            log.log(scalyr_logging.DEBUG_LEVEL_3, 'Using a staleness threshold of %f for %s',
                    self.__stale_threshold_secs, self.log_path)
        else:
            self.__stale_threshold_secs = None

        # Determine if the log path to match on is a glob or not by looking for normal wildcard characters.
        # This probably leads to false positives, but that's ok.
        self.__is_glob = '*' in self.log_path or '?' in self.log_path or '[' in self.log_path
        # The time in seconds past epoch when we last checked for new files that match the glob.
        self.__last_check = None
        # The LogFileProcessor objects for all log files that have matched the log_path.  This will only have
        # one element if it is not a glob.
        self.__processors = []
        # The lock that protects the __processor and __last_check vars.
        self.__lock = threading.Lock()

    @property
    def config(self):
        """Returns the log entry configuration for this matcher.

        This is used only for testing purposes.

        @return: The configuration.  You must not modify this object.
        @rtype: dict
        """
        return self.__log_entry_config

    def generate_status(self):
        """
        @return:  The status object describing the state of the log processors for this log file.
        @rtype: LogMatcherStatus
        """
        try:
            self.__lock.acquire()
            self.__removed_closed_processors()

            result = LogMatcherStatus()
            result.log_path = self.log_path
            result.is_glob = self.__is_glob
            result.last_check_time = self.__last_check

            for processor in self.__processors:
                result.log_processors_status.append(processor.generate_status())

            return result
        finally:
            self.__lock.release()

    def find_matches(self, existing_processors, previous_state, copy_at_index_zero=False):
        """Determine if there are any files that match the log file for this matcher that are not
        already handled by other processors, and if so, return a processor for it.

        @param existing_processors: A dict from file path to the processor currently handling it.  This method will
            not create any new processors for file paths that are keys in this dict.
        @param previous_state: A dict from file path to the serialized checkpoint state last recorded for that
            file path.  Note, if this method does use a state entry, then it will remove it from this dict.
        @param copy_at_index_zero: If a match is found and no previous checkpoint state is found for the file path,
            then if copy_at_index_zero is True, the file will be processed from the first byte in the file.  Otherwise,
            the processing will skip over all bytes currently in the file and only process bytes added after this
            point.

        @type existing_processors: dict of str to LogFileProcessor
        @type previous_state: dict of str to json_lib.JsonObject
        @type copy_at_index_zero: bool

        @return: A list of the processors to handle the newly matched files.
        @rtype: list of LogFileProcessor
        """
        if not self.__is_glob and self.log_path in existing_processors:
            existing_processors[self.log_path].add_missing_attributes( self.__log_entry_config['attributes'] )
            return []

        self.__lock.acquire()
        self.__last_check = time.time()
        self.__removed_closed_processors()
        self.__lock.release()

        result = []
        # We need to be careful that we throw out any processors that were created if we do hit an exception,
        # so we track if we got to the return statement down below or not.
        reached_return = False

        copy_from_start = False
        if 'copy_from_start' in self.__log_entry_config:
            copy_from_start = self.__log_entry_config['copy_from_start']

        # See if the file path matches.. even if it is not a glob, this will return the single file represented by it.
        try:
            for matched_file in glob.glob(self.__log_entry_config['path']):

                skip = False
                # check to see if this file matches any of the exclude globs
                for exclude_glob in self.__log_entry_config['exclude']:
                    if fnmatch.fnmatch( matched_file, exclude_glob ):
                        skip = True
                        break

                # if so, skip it.
                if skip:
                    continue

                already_exists = matched_file in existing_processors
                # Only process it if we have permission to read it and it is not already being processed.
                # Also check if we should skip over it entirely because it is too stale.
                if not already_exists and self.__can_read_file_and_not_stale(matched_file, self.__last_check):
                    checkpoint_state = None
                    # Get the last checkpoint state if it exists.
                    if matched_file in previous_state:
                        checkpoint_state = previous_state[matched_file]
                        del previous_state[matched_file]
                    elif copy_at_index_zero or copy_from_start:
                        # If we don't have a checkpoint and we are suppose to start copying the file at index zero,
                        # then create a checkpoint to represent that.
                        checkpoint_state = LogFileProcessor.create_checkpoint(0)

                    renamed_log = self.__rename_log_file( matched_file, self.__log_entry_config )

                    # Be sure to add in an entry for the logfile name to include in the log attributes.  We only do this
                    # if the field or legacy field is not present.  Maybe we should override this regardless because the
                    # user could get it wrong.. but for now, we just let them screw it up if they want to.
                    log_attributes = dict(self.__log_entry_config['attributes'])
                    if 'logfile' not in log_attributes and 'filename' not in log_attributes:
                        log_attributes['logfile'] = renamed_log

                    if 'original_file' not in log_attributes and renamed_log != matched_file:
                        # Note, this next line is for a hack in the kubernetes_monitor to not include the original
                        # log file name.  TODO: Clean this up.
                        if not 'rename_no_original' in self.__log_entry_config:
                            log_attributes['original_file'] = matched_file

                    # Create the processor to handle this log.
                    new_processor = LogFileProcessor(matched_file, self.__overall_config, self.__log_entry_config,
                                                     log_attributes=log_attributes, checkpoint=checkpoint_state,
                                                     close_when_staleness_exceeds=self.__stale_threshold_secs)
                    for rule in self.__log_entry_config['redaction_rules']:
                        new_processor.add_redacter(
                            rule['match_expression'],
                            rule['replacement'],
                            str(rule.get('hash_salt', default_value=''))
                        )
                    for rule in self.__log_entry_config['sampling_rules']:
                        new_processor.add_sampler(rule['match_expression'], rule.get_float('sampling_rate', 1.0))
                    result.append(new_processor)

            self.__lock.acquire()
            for new_processor in result:
                self.__processors.append(new_processor)
            self.__lock.release()

            reached_return = True
            return result

        finally:
            # If we didn't actually return the result, then we need to be sure to close the processors so that
            # we release any file handles.
            if not reached_return:
                for new_processor in result:
                    new_processor.close()

    def __split_path( self, path ):
        paths = []
        while True:
            prev = path
            path, current = os.path.split( path )

            if prev == path:
                break;
            elif current != "":
                paths.append(current)
            else:
                if path != "":
                    paths.append(path)

                break

        paths.reverse()
        return paths

    def __rename_log_file( self, matched_file, log_config ):
        """Renames a log file based on the log_config's 'rename_logfile' field (if present)
        """
        result = matched_file
        if 'rename_logfile' in log_config:
            rename = log_config['rename_logfile']

            if isinstance( rename, basestring ):
                pattern = string.Template( rename )
                try:
                    values = {}
                    sections = self.__split_path( matched_file )
                    for index, section in enumerate(sections, 1):
                        values["PATH%d"%index] = section

                    basename = os.path.basename( matched_file )
                    values['BASENAME'] = basename
                    values['BASENAME_NO_EXT'] = os.path.splitext( basename )[0]
                    result = pattern.substitute( values )
                except Exception, e:
                    log.warn( "Invalid substition pattern in 'rename_logfile'. %s" % str( e ) )
            elif isinstance( rename, json_lib.JsonObject ):
                if 'match' in rename and 'replacement' in rename:
                    try:
                        pattern = re.compile( rename['match'] )
                        result = re.sub( pattern, rename['replacement'], matched_file )
                        if result == matched_file:
                            log.warn( "Regex '%s' used to rename logfile '%s', but logfile name was not changed." % ( rename['match'], matched_file ),
                                   limit_once_per_x_secs=600, limit_key=('rename-regex-same-%s' % matched_file))
                    except Exception, e:
                        log.warn( "Error matching regular expression '%s' and replacing with '%s'.  %s" % (rename['match'], rename['replacement'], str(e ) ),
                                   limit_once_per_x_secs=600, limit_key=('rename-regex-error-%s' % matched_file))

        return result

    def __can_read_file_and_not_stale(self, file_path, current_time):
        """Determines if this process can read the file at the path.

        @param file_path: The file path
        @type file_path: str
        @return: True if it can be read.
        @rtype: bool
        """
        if self.__stale_threshold_secs is not None:
            mod_time = self.__file_system.get_last_mod_time(file_path)
            if mod_time is not None and (current_time - mod_time) > self.__stale_threshold_secs:
                log.log(scalyr_logging.DEBUG_LEVEL_3, 'Ignoring "%s" because its last mod is too old', file_path)
                return False

        return self.__file_system.can_read(file_path)

    def __removed_closed_processors(self):
        """Performs some internal clean up to remove any processors that are no longer active.

        You can only call this if you hold self.__lock.
        """
        new_list = []
        for processor in self.__processors:
            if not processor.is_closed():
                new_list.append(processor)
        self.__processors = new_list


class FileSystem(object):
    """A facade through which file system calls can be made.

    This abstraction is really in place for future testing.  It centralizes all
    of the I/O methods so that they can be stubbed or mocked out if needed.  However,
    for now, the only implementation of this class uses the real file system.

    Attributes:
        trust_inodes:  True if inodes are trusted on this file system.  This is a place
            holder since Scalyr only supports systems (like Linux and MacOS X) that do have
            valid inodes.
    """

    def __init__(self):
        self.trust_inodes = sys.platform != 'win32'

    def open(self, file_path):
        """Returns a file object to read the file at file_path.

        @param file_path: The path of the file to open

        @return: The file object
        """
        return open(file_path, 'rb')

    def readlines(self, file_object, max_bytes=None):
        """Reads lines from the file_object, up to max_bytes bytes.

        @param file_object: The file.
        @param max_bytes: The maximum number of bytes to read.

        @return: A list of lines read.
        """
        if max_bytes is None:
            return file_object.readlines()
        else:
            return file_object.readlines(max_bytes)

    def readline(self, file_object, max_bytes=None):
        """Reads a single lines from the file_object, up to max_bytes bytes.

        @param file_object: The file.
        @param max_bytes: The maximum number of bytes to read.

        @return: The line read.
        """
        if max_bytes is None:
            return file_object.readline()
        else:
            return file_object.readline(max_bytes)

    def read(self, file_object, max_bytes):
        """Reads bytes from file_object, up to max_bytes bytes.

        @param file_object: The file.
        @param max_bytes: The maximum number of bytes to read.

        @return: A string containing the bytes.
        """
        return file_object.read(max_bytes)

    def stat(self, file_path):
        """Performs a stat on the file at file_path and returns the result.

        @param file_path: The path of the file to stat.

        @return: The stat object for the file (see os.stat)
        """
        return os.stat(file_path)

    def close(self, file_object):
        """Closes the file.

        @param file_object: The file to close
        """
        file_object.close()

    def tell(self, file_object):
        """Returns the current position of the file object.
        @param file_object: The file.
        """
        return file_object.tell()

    def seek(self, file_object, position):
        """Changes the current read position of the file.

        @param file_object: The file.
        @param position: The position of the next bytes to read.
        """
        file_object.seek(position)

    def list_files(self, directory_path):
        """Returns the list of files in the specified directory.  Does not include directories.

        @param directory_path: The path of the directory

        @return: A list of string containing the full path name of the files (not directories) present in the directory.
        """
        result = []
        for f in listdir(directory_path):
            full_path = join(directory_path, f)
            if isfile(full_path):
                result.append(full_path)
        return result

    def get_file_size(self, file_object):
        """Returns the file size for the given file object.

        @param file_object: The open file handle for the file
        @type file_object: FileIO
        @return: The size of the file in bytes.
        @rtype: int
        """
        original_position = None
        try:
            # We have to seek to the end of the file to get its length.
            original_position = file_object.tell()
            file_object.seek(0, 2)
            return file_object.tell()
        finally:
            if original_position is not None:
                file_object.seek(original_position)

    def get_last_mod_time(self, file_path):
        """Returns the last modification time in seconds since epoch for the specified file.

        If the file exists, we should always be able to get the stat.  If there is an error, None is returned.

        @param file_path:
        @type file_path: str

        @return: The number of seconds past epoch when the file was last modified.
        @rtype: float or None
        """
        try:
            return os.path.getmtime(file_path)
        except OSError:
            # We really shouldn't ever get errors since you don't need permissions.  So, only if the file doesn't
            # exist will we get this error.
            return None
        except IOError:
            return None

    def can_read(self, file_path):
        """Returns true if this process can read the given file.

        @param file_path: The file path
        @type file_path: str

        @return: True if this process can read the specified file.
        @rtype: bool
        """
        try:
            fp = open(file_path, 'r')
            fp.close()
        except IOError, error:
            if error.errno == 13:
                return False
        return True
