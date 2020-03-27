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
#
# Defines ServerProcessor, a simple abstraction that handles receiving
# small requests over TCP/IP and performing some action based on it.
#
# author: Steven Czerwinski <czerwin@scalyr.com>

from __future__ import absolute_import
from scalyr_agent import compat

__author__ = "czerwin@scalyr.com"

import io
import errno
import socket
import six.moves.socketserver
import struct
import time

import scalyr_agent.scalyr_logging as scalyr_logging

global_log = scalyr_logging.getLogger(__name__)


class ServerProcessor(
    six.moves.socketserver.ThreadingMixIn, six.moves.socketserver.TCPServer
):
    """Base class for simple servers that only need to accept incoming connections, perform some actions on
    individual commands, and return no output.

    This abstraction is meant can be used to implement trivial monitoring servers such as graphite or
    OpenTSDB.  It is meant to run in its own thread, and will spawn a new thread for each incoming
    connection.  Multiple commands can be received on each connection, but each command is executed
    independently (there is no connection state shared between the commands on an individual connection).

    To use this abstraction, you must provide implementations for the parse_request and execute_request
    methods.  Additionally, you should probably provide an implementation of report_connection_problem so
    that errors generated will handling an individual connection can be recorded.
    """

    def __init__(
        self,
        server_port,
        localhost_socket=True,
        max_connection_idle_time=300,
        max_request_size=100 * 1024,
        buffer_size=100 * 1024,
        run_state=None,
    ):
        """Creates a new instance that will accept new connections on the specified port.

        To begin accepting connections, you must invoke the 'run' method.

        @param server_port: The port on which to accept connections.
        @param localhost_socket: If True, this instance will only bind a socket on the localhost address so that
            external connections will not be accepted.
        @param max_connection_idle_time: The maximum idle time to allow for a connection before it is closed down. The
            idle time is calculated by the last time a complete request was received on the connection.
        @param max_request_size: The maximum request size to allow in bytes.
        @param buffer_size: The buffer size for receiving incoming requests per connection. This must be greater than
            max_request_size
        @param run_state: The run_state instance that controls when this instance should stop accepting new
            connections.
        """
        if localhost_socket:
            server_address = ("localhost", server_port)
        else:
            server_address = ("", server_port)
        # Allow for quick server socket re-use.  This helps prevent problems if we are quickly restarting the agent.
        self.allow_reuse_address = True
        self.max_connection_idle_time = max_connection_idle_time
        self.max_request_size = max_request_size
        self.buffer_size = buffer_size
        self.run_state = run_state
        # Make sure our shutdown method is invoked when run_state becomes stopped.
        if run_state is not None:
            self.run_state.register_on_stop_callback(self.shutdown)

        six.moves.socketserver.TCPServer.__init__(
            self, server_address, ConnectionHandler
        )

    def run(self):
        """Begins accepting new connections and processing the incoming requests.

        This does not return until either the 'shutdown' method is invoked or the run_state instance passed into
        the initializer is stopped.
        """
        self.serve_forever()

    def parse_request(self, request_input, num_available_bytes):
        """Reads the incoming data from an individual connection's request_input buffer (file object) and returns a
        string containing the next complete request that should be processed by this instance.

        Derived classes must override this method.  You may use some helper parsers such as LineRequestParser
        and Int32RequestParser to implement this method.

        The request_input's read position is set to point at the next byte to read.  Any bytes that are read by
        this method are considered to be consumed and will not be passed to any future 'parse_request' invocations
        even if this method returns None.  Care must be taken such that only the bytes that are part of the current
        request are consumed by this method.

        If a complete request is not found in request_input then None should be returned.  When more input is
        received on a connection, this method will be invoked again at this same position.

        @param request_input: A file object that holds the incoming data for an individual connection. It is
            implemented using a StringIO instance so it is efficient to use 'seek' and 'tell' to reposition the
            position if necessary. (This is useful if an incomplete server request was found and you need to reset the
            position to the start.) Note, the position of the buffer is not guaranteed to be zero (previous commands
            may still be in the buffer.
        @param num_available_bytes: The number of bytes between the current read position and the end of the buffer.

        @return: A string containing the next complete request that should be executed for this connection, or None
            if there is no complete request.  Additionally, if request_input's read position has been moved,
            then those bytes are considered to be consumed for the connection.
        """
        pass

    def execute_request(self, request):
        """Executes a request that was returned by a previous invocation to 'parse_request'.

        Derived classes must implement this method to take some action on the request.

        @param request: The request to executed.
        """

    def report_connection_problem(self, exception):
        """Report an exception raised while handling an individual connection.

        If this is invoked, it also means that the connection that generated this exception will be closed.

        @param exception: The exception that was thrown. This is always invoked in an exception handler, so it is valid
            to report the exception using a logger's 'exception' method.
        """
        pass


class LineRequestParser(object):
    """Simple abstraction that implements a 'parse_request' that can be used to parse incoming requests
    that are terminated by either '\n' or '\r\n'.
    """

    def __init__(self, max_request_size, eof_as_eol=False):
        """Creates a new instance.

        @param max_request_size: The maximum number of bytes that can be contained in an individual request.
        @param eof_as_eol: If true then treat EOF as the end of a line
        """
        self.__max_request_size = max_request_size
        self.__eof_as_eol = eof_as_eol

    def parse_request(self, input_buffer, _):
        """Returns the next complete request from 'input_buffer'.

        If there is a complete line at the start of 'input_buffer' (where complete line is determined by it
        ending in a newline character), then consumes those bytes from 'input_buffer' and returns the string
        including the newline.  Otherwise None is returned and no bytes are consumed from 'input_buffer'

        @param input_buffer: The bytes to read.
        @param _: The number of bytes available in 'input_buffer'. (not used)

        @return: A string containing the next complete request read from 'input_buffer' or None if there is none.

            RequestSizeExceeded if a line is found to exceed the maximum request size.
        """
        original_position = None
        try:
            original_position = input_buffer.tell()
            line = input_buffer.readline(self.__max_request_size + 1)

            bytes_received = len(line)
            if bytes_received > self.__max_request_size:
                # We just consume these bytes if the line did exceeded the maximum.  To some degree, this
                # typically does not matter since once we see any error on a connection, we close it down.
                original_position = None
                raise RequestSizeExceeded(bytes_received, self.__max_request_size)

            # Check to see if a complete line was actually returned since if readline() hit EOF, then
            # it will return whatever line was left without a newline.
            return_line = False
            if bytes_received > 0:
                # 2->TODO use slicing to get bytes on bith python versions.
                if line[-1:] == b"\n":
                    return_line = True
                else:
                    # check if we want to return the remaining text when EOF is hit
                    if self.__eof_as_eol:
                        # this will return an empty string if EOF is reached
                        last_line = input_buffer.read(1)
                        if len(last_line) == 0:
                            # we have reach eof so also return
                            return_line = True

            if return_line:
                original_position = None
                return line
        finally:
            if original_position is not None:
                input_buffer.seek(original_position)


class Int32RequestParser(object):
    """Simple abstraction that implements a 'parse_request' that can be used to parse incoming requests
    that are sent using an integer prefix format.

    This supports binary protocols where each request is prefixed by a 4 byte integer in network order
    that specifies the size of the request in bytes.  Those bytes are then read from the input stream.

    Some monitor protocols, such as Graphite's pickle protocol uses this format.
    """

    def __init__(self, max_request_size):
        """Creates a new instance.

        @param max_request_size: The maximum number of bytes that can be contained in an individual request.
        """
        self.__format = "!I"
        self.__prefix_length = struct.calcsize(self.__format)
        self.__max_request_size = max_request_size

    def parse_request(self, input_buffer, num_bytes):
        """Returns the next complete request from 'input_buffer'.

        If there is a complete request at the start of 'input_buffer', it is returned.  A complete request
        is one whose initial 4 byte length prefixed has been received as well as the number of bytes specified
        in that prefix.  This method will consume all of those bytes and return only the complete request
        payload (not the initial 4 byte length field).  If no request is found, then None is returned and
        no bytes are consumed from 'input_buffer'

        @param input_buffer: The bytes to read.
        @param num_bytes: The number of bytes available in 'input_buffer'.

        @return: A string containing the next complete request read from 'input_buffer' or None if there is none.

        @raise RequestSizeExceeded: If a line is found to exceed the maximum request size.
        """
        original_position = None
        try:
            original_position = input_buffer.tell()
            # Make sure we have 4 bytes so that we can at least read the length prefix, and then try to read
            # the complete data payload.
            if num_bytes > self.__prefix_length:
                # 2->TODO struct.pack|unpack in python < 2.7.7 does not allow unicode format string.
                (length,) = compat.struct_unpack_unicode(
                    six.ensure_str(self.__format),
                    input_buffer.read(self.__prefix_length),
                )
                if length > self.__max_request_size:
                    raise RequestSizeExceeded(length, self.__max_request_size)
                if length + self.__prefix_length <= num_bytes:
                    original_position = None
                    return input_buffer.read(length)

            return None
        finally:
            if original_position is not None:
                input_buffer.seek(original_position)


class ConnectionIdleTooLong(Exception):
    """Raised when the time since a connection last received a complete request has exceeded the maximum connection
    idle time.
    """

    def __init__(self, time_since_last_activity, max_inactivity):
        Exception.__init__(
            self,
            "Connection has been idle too long. No data has been received for "
            "%d seconds and limit is %d" % (time_since_last_activity, max_inactivity),
        )


class RequestSizeExceeded(Exception):
    """Raised when an incoming request has exceeded the maximum allowed request size.
    """

    def __init__(self, request_size, max_request_size):
        Exception.__init__(
            self,
            "The current request size of %d exceeded maximum allowed of %d"
            % (request_size, max_request_size),
        )


class ConnectionProcessor(object):
    """An internal abstraction that reads requests from an incoming request_stream and executes them.

    This manages an individual connection, including raising a 'ConnectionIdleTooLong' exception when a
    complete request has not been received in the allowed time.

    """

    # This abstraction exists really only for testing purposes.  It could have been implemented as part of
    # 'ConnectionHandler', but since that class derives from 'SocketServer.BaseRequestHandler', it is
    # difficult to test.  That is because 'SocketServer.BaseRequestHandler' does non-test-friendly things like
    # invoking 'handle' as part of instance initialization.
    def __init__(
        self, request_stream, request_executor, run_state, max_connection_idle_time
    ):
        """Returns a new instance.  You must invoke 'run' to begin processing requests.

        @param request_stream: An instance of 'RequestSream' containing the incoming bytes for a connection.
        @param request_executor: A method to invoke to execute each request that takes in just a single
        @param run_state: The run_state that controls when this process should stop.
        @param max_connection_idle_time: The maximum number of seconds to wait between commands before raising a
            ConnectionIdleTooLong exception and closing the connection.
        """
        self.__request_stream = request_stream
        self.__request_executor = request_executor
        self.__run_state = run_state
        self.__max_connection_idle_time = max_connection_idle_time
        self.__last_request_time = None
        # The amount of time in seconds to sleep when there are no bytes available on the socket until we check
        # again.
        self.__polling_interval = 0.5

    def run(self):
        """Begins reading requests from the incoming request stream and executing them.

        This will not return until the 'run_state' instance passed in at initialization has been stopped.
        """
        while self.run_single_cycle(time.time()):
            pass

    def run_single_cycle(self, current_time=None):
        """Performs a single cycle of reading the next available request and executing it, or waiting for
        the polling interval for the next request.

        This is exposed only for testing purposes.

        @param current_time: If provided, uses the specified time as the current time. Used for testing.

        @return: """
        if current_time is None:
            current_time = time.time()

        if self.__last_request_time is None:
            self.__last_request_time = current_time

        request = self.__request_stream.read_request(
            timeout=self.__polling_interval, run_state=self.__run_state
        )
        if request is not None:
            self.__request_executor(request)
            self.__last_request_time = current_time
        elif current_time - self.__last_request_time > self.__max_connection_idle_time:
            raise ConnectionIdleTooLong(
                self.__last_request_time - time.time(), self.__max_connection_idle_time
            )
        return self.__run_state.is_running() and not self.__request_stream.at_end()


class ConnectionHandler(six.moves.socketserver.BaseRequestHandler):
    """The handler class that is used by ServerProcess to handle incoming connections.
    """

    # The bulk of the work for this class is actually implemented in ConnectionProcess to allow for
    # easier testing.
    def handle(self):
        try:
            # Create an instance of RequestStream for the incoming connection and then use a ConnectionProcessor
            # to handle it.
            request_stream = RequestStream(
                self.request,
                self.server.parse_request,
                max_buffer_size=self.server.buffer_size,
                max_request_size=self.server.max_request_size,
            )
            processor = ConnectionProcessor(
                request_stream,
                self.server.execute_request,
                self.server.run_state,
                self.server.max_connection_idle_time,
            )
            processor.run()
        except Exception as e:
            self.server.report_connection_problem(e)


class RequestStream(object):
    """Provides a specialized buffered interface for reading requests from a socket.

    This essentially puts a memory buffer in front of an incoming socket to efficiently read requests from
    the incoming stream and reset the read position when required by incomplete requests.
    """

    def __init__(
        self,
        incoming_socket,
        request_parser,
        max_buffer_size=100 * 1024,
        max_request_size=100 * 1024,
        blocking=True,
    ):
        """Creates a new instance.

        @param incoming_socket: The incoming socket.
        @param request_parser: A method that will attempt to parse the next complete request from the incoming stream
            and return it if possible. Takes two arguments, an StringIO containing the incoming bytes and an integer
            specifying the number of bytes available in the buffer.
        @param max_buffer_size: The maximum buffer to use for buffering the incoming requests.
        @param max_request_size: The maximum allowed size for each request.
        @param blocking: If True pause before reading from the socket to allow time for data to come int
            if False read directly from the socket.
        """
        # We use non-blocking sockets so that we can response quicker when the agent is
        # shutting down.  It does mean there will be some delay between bytes showing up on the
        # connection and when we read them.
        incoming_socket.setblocking(0)
        self.__socket = incoming_socket
        self.__request_parser = request_parser
        self.__max_buffer_size = max_buffer_size
        self.__max_request_size = max_request_size
        self.__blocking = blocking

        if self.__max_buffer_size < self.__max_request_size:
            raise Exception(
                "You cannot have a max buffer size smaller than your max request size (%d > %d)"
                % (self.__max_buffer_size, self.__max_request_size)
            )

        # The number of bytes in _buffer.
        self.__current_buffer_size = 0
        # Whether or not the socket has been closed and the stream should be considered at the end.
        self.__at_end = False

        # Whether or not a socket error has occurred - we keep this separate from at_end to be able to
        # distinguish between errors and eof.  This is useful when testing.
        self.__socket_error = False

        # The actual buffer.  We will maintain an invariant that the position of the buffer is always pointing at
        # the next byte to read.
        self.__buffer = io.BytesIO()

    def read_request(self, timeout=0.5, run_state=None):
        """Attempts to read the next complete request from the socket and return it.

        If there is no request to be immediately read from the socket, will wait for 'timeout' seconds for
        more data to be received on the socket and read the request from that.

        @param timeout: The number of seconds to wait for more data on the socket if there is currently no complete
            request.
        @param run_state: If run_state's 'stop' method is invoked, then this method will attempt to return as quickly
            as possible (not waiting the full 'timeout' period.)

        @return: The request if one was found.  Otherwise None, which can either indicate the socket was closed or
            'timeout' expired and no request was still available.  You may invoke 'at_end' to determine if the
            socket has been closed.
        """
        do_full_compaction = True
        try:
            try:
                # Try to read the request from the already existing buffered input if possible.
                bytes_available_to_read = (
                    self.__get_buffer_write_position()
                    - self.__get_buffer_read_position()
                )
                if bytes_available_to_read > 0:
                    parsed_request = self.__request_parser(
                        self.__buffer, bytes_available_to_read
                    )
                    if parsed_request is not None:
                        do_full_compaction = False
                        return parsed_request
                    elif bytes_available_to_read >= self.__max_request_size:
                        # The parser didn't return a request even though the maximum request size has been reached..
                        # This should never happen (if parser is written correctly), so throw an error
                        raise RequestSizeExceeded(
                            bytes_available_to_read, bytes_available_to_read
                        )
                    elif self.__max_buffer_size == self.__get_buffer_write_position():
                        # If there are pending bytes left in the buffer, then they didn't form a full request.  We
                        # definitely need to read more bytes from the network, so do a full compaction if we have to.
                        self.__full_compaction()

                if self.__blocking:
                    # No data immediately available.  Wait a few milliseconds for some more to come in.
                    if not self.__sleep_until_timeout_or_stopped(timeout, run_state):
                        return None

                do_full_compaction = True

                if self.__max_buffer_size - self.__get_buffer_write_position() == 0:
                    global_log.warning(
                        "RequestStream: write_position == max_buffer.  No room in recv buffer"
                    )

                data = self.__socket.recv(
                    self.__max_buffer_size - self.__get_buffer_write_position()
                )
                # If we get nothing back, then the connection has been closed.  If it is not closed and there is
                # no data, then we would get a socket.timeout or socket.error which are handled below.
                if not data:
                    global_log.log(
                        scalyr_logging.DEBUG_LEVEL_1,
                        "RequestStream.read_request: No data received, flagging end of stream",
                    )
                    self.__at_end = True
                    return None

                # Add the new bytes to the buffer.
                bytes_available_to_read += len(data)
                self.__add_to_buffer(data)

                # Attempt to parse.
                parsed_request = self.__request_parser(
                    self.__buffer, bytes_available_to_read
                )

                if parsed_request is not None:
                    # The parser should be checking the max request size as well, but we do a quick double
                    # check here as well.
                    if len(parsed_request) > self.__max_request_size:
                        raise RequestSizeExceeded(
                            len(parsed_request), self.__max_request_size
                        )
                    do_full_compaction = False
                    return parsed_request

                # If we didn't find a complete request but we are at our maximum buffer size, then we are screwed.. we
                # don't any more room to try to read more bytes to complete that request.. so just call it an error.
                if bytes_available_to_read == self.__max_buffer_size:
                    raise RequestSizeExceeded(
                        self.__max_buffer_size, self.__max_buffer_size
                    )

                return None

            except socket.timeout:
                self.__socket_error = True
                return None
            except socket.error as e:
                if e.errno == errno.EAGAIN:
                    return None
                else:
                    self.__socket_error = True
                    raise e
        finally:
            # We do a full compaction in general if we did not return anything and there is no room
            # left to copy new bytes in.
            if (
                do_full_compaction
                and self.__get_buffer_write_position() == self.__max_buffer_size
            ):
                # Do a compaction if our buffer is at the limit, but we also have bytes at the front of it that have
                # already been consumed (i.e., are read position is not at the beginning of the buffer.. so we can
                # reclaiming the bytes before it to make room.)
                self.__full_compaction()
            else:
                # Always try to do a quick compaction to make room in the buffer.
                self.__quick_compaction()

    def at_end(self):
        """Returns True if the underlying socket has been closed.
        """
        return self.__at_end

    def is_closed(self):
        """Returns True if the underlying socket has been closed - either due to reading EOF
        or due to socket.timeouts and other exceptions.
        We keep this separate from at_end so callers can detect just for EOF if they want.
        """
        return self.at_end() or self.__socket_error

    def get_buffer_size(self):
        """Returns the size of the underlying buffer, which may also include bytes for requests already returned
        by 'read_request'.

        This is used just for testing purposes.
        """
        return self.__get_buffer_write_position()

    def __add_to_buffer(self, new_data):
        """Adds 'new_data' to the underlying buffer.

        @param new_data: A string containing the new bytes to add.
        """
        # Get the original position because this is the current read position.  We need to move our position
        # to the end of the buffer to do the write, and then move it back to this read position.
        original_position = None
        try:
            original_position = self.__buffer.tell()
            self.__buffer.seek(0, 2)
            self.__buffer.write(new_data)
            self.__current_buffer_size = self.__buffer.tell()
        finally:
            if original_position is not None:
                self.__buffer.seek(original_position)

    def __get_buffer_write_position(self):
        """Returns the current write position of the buffer relative to the start of the buffer.  This is where
        new bytes will be added.  This essentially says how many bytes the entire buffer is consuming."""
        return self.__current_buffer_size

    def __get_buffer_read_position(self):
        """Returns the current read position of the buffer.  This is where we will next attempt to read bytes
        to parse server requests.  It is relatively to the start of the entire buffer, which may contain
        bytes that have already been returned by previous 'read_request' invocations."""
        # We have an invariant that the current position is always the read position.
        return self.__buffer.tell()

    def __sleep_until_timeout_or_stopped(self, timeout, run_state):
        """Sleeps for the specified number of seconds, unless 'run_state' becomes stopped in which case
        it attempts to return as quickly as possible.

        @param timeout: The number of seconds to sleep.
        @param run_state: If not None, then will attempt to return as quickly as possible of 'run_state' becomes
            stopped.

        @return: True if 'run_state' is not stopped.
        """
        if run_state is not None:
            run_state.sleep_but_awaken_if_stopped(timeout)
            return run_state.is_running()
        else:
            time.sleep(timeout)
            return True

    def __full_compaction(self):
        """Compacts the memory buffer by remove all bytes that have already been read.
        """
        # Read the leftover data and write it into a new buffer.
        remaining_data = self.__buffer.read()
        self.__buffer.close()
        self.__buffer = io.BytesIO()
        self.__buffer.write(remaining_data)
        self.__current_buffer_size = self.__buffer.tell()
        self.__buffer.seek(0)

    def __quick_compaction(self):
        """Attempts a quick compaction by seeing if all bytes in the current buffer have been read.  If so,
        we can just throw out the old buffer and create a new one since we do not need to copy any leftover bytes.
        """
        if self.__get_buffer_read_position() == self.__get_buffer_write_position():
            self.__buffer.close()
            self.__buffer = io.BytesIO()
            self.__current_buffer_size = 0
