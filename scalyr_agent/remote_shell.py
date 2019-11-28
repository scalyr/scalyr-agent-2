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
# This code was based on a post at http://www.shysecurity.com/posts/Remote%20Interactive%20Python by
# kelson@shysecurity.com.
#
# This is used to enable remote interaction with the python process for remote debugging.  It should
# be used with extreme care since there is no security in the connection model right now.
#
# author: Steven Czerwinski <czerwin@scalyr.com>

__author__ = 'czerwin@scalyr.com'

import sys
import socket

import scalyr_agent.scalyr_logging as scalyr_logging

from scalyr_agent.util import StoppableThread

log = scalyr_logging.getLogger(__name__)


class SocketWrapper(object):
    """Wraps a socket in order to implement the necessary functions to be as a stdin.

    This is necessary to cast the socket as stdin to be used by the code.iteract method.

    It implements only the methods necessary to be used in place of stdin.
    """
    def __init__(self, my_socket):
        """Initializes the wrapper.

        @param my_socket: The socket to wrap
        @type my_socket: socket.socket
        @return:
        @rtype:
        """
        self.__socket = my_socket

    def read(self, max_bytes):
        """Reads bytes from the underlying connection.

        This will bock until some bytes can be returned.

        @param max_bytes: The maximum number of bytes to read.

        @type max_bytes: int

        @return: The bytes read as a string.
        @rtype: str
        """
        while True:
            try:
                return self.__socket.recv(max_bytes)
            except socket.timeout:
                continue
            except socket.error, e:
                if e.errno == 35:
                    continue
                raise e

    def write(self, input_str):
        """Writes the string to the underlying socket.
        @param input_str: The string to send.
        @type input_str: str
        """
        return self.__socket.send(input_str)

    def readline(self):
        """Reads an entire line from the underlying socket, blocking until a line is received.

        @return: The line
        @rtype: str
        """
        data = ''
        while True:
            try:
                iota = self.read(1)
            except socket.timeout:
                continue
            if not iota:
                break
            else:
                data += iota
            if iota in '\n':
                break
        return data


class DebugServer(StoppableThread):
    """A HTTP Server that accepts connections from local host to an interactive Python shell.

    This can be used for debugging purposes.  The interactive Python shell allows you to inspect the state
    of the running Python process including global variables, etc.

    This currently creates a new thread for every incoming connection.
    """
    def __init__(self, local=None, host='localhost', port=2000):
        self.__server_socket = None
        # The open connections.
        self.__connections = []
        # Any local variables to set for the interactive shell.  This is a dict.
        self.__local = local
        # The IP address to server the connections from.
        self.__host = host
        # The port.
        self.__port = port
        StoppableThread.__init__(self, 'debug server thread')

    def run(self):
        """Run the server, accepting new connections and handling them.

        This method does not return until the thread has been stopped.
        """
        # Run until the thread has been stopped.
        while self._run_state.is_running():
            # Set up the server socket.
            if self.__server_socket is None:
                self.__setup_server_socket()

            # block until we get a new connection.
            session = self.__accept_connection()
            if session is not None:
                self.__connections.append(session)
                session.start()

            # Clean up any connections that have been closed.
            if len(self.__connections) > 0:
                remaining_connections = []
                for connection in self.__connections:
                    if connection.isAlive():
                        remaining_connections.append(connection)
                    else:
                        connection.join(1)
                self.__connections = remaining_connections

    def __accept_connection(self):
        """Blocks until a new connection is made.

        @return The new connection.
        @rtype: DebugConnection
        """
        if self.__server_socket is None:
            return None

        # noinspection PyBroadException
        # TODO:  Move this catch out of here.
        try:
            client, addr = self.__server_socket.accept()
            return DebugConnection(self.__local, client, self.__host, self.__port)
        except socket.timeout:
            return None
        except Exception:
            log.exception('Failure while accepting new debug connection.  Resetting socket')
            self.__close_socket()
        return None

    def __setup_server_socket(self):
        """Create the server socket, binding to the appropriate address.
        """
        if self.__server_socket is not None:
            return

        # noinspection PyBroadException
        # TODO: Move this catch out of here.
        try:
            self.__server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.__server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.__server_socket.settimeout(1)
            self.__server_socket.bind((self.__host, self.__port))
            self.__server_socket.listen(5)
        except Exception:
            log.exception('Failure while accepting new debug connection.  Resetting socket')
            self.__close_socket()

    def __close_socket(self):
        """Close the underlying server socket.
        """
        if self.__server_socket is not None:
            try:
                self.__server_socket.shutdown(socket.SHUT_RDWR)
                self.__server_socket = None
            except socket.error:
                self.__server_socket = None


class DebugConnection(StoppableThread):
    """Handles a single incoming connection on the server, connecting it to the interactive Python shell.

    This is run as a thread.
    """
    def __init__(self, local, client_connection, host, port):
        """Initializes the connection.
        @param local: The dict of local variables to populate into the envinroment the interactive shell is run in.
        @param client_connection:  The network connection
        @param host: the client's IP address
        @param port: the client's port

        @type local: dict
        @type client_connection:
        @type host: str
        @type port: int
        """
        self.__local = local
        self.__client_connection = client_connection
        self.__host = host
        self.__port = port
        StoppableThread.__init__(self, 'Debug connection thread')

    def run(self):
        """Handle the incoming connection, connecting it to the interactive shell.

        Will terminate either when the connection closes or the stop method in this thread is invoked.
        """
        import traceback
        # Wrap the socket so we can tie it to stdin,stdout.
        link = SocketWrapper(self.__client_connection)
        banner = 'connected to %s:%d' % (self.__host, self.__port)
        banner += '\nStack Trace\n'
        banner += '----------------------------------------\n'
        banner += ''.join(traceback.format_stack()[:-2])
        banner += '----------------------------------------\n'
        # In order to hook it up shell, we need to set the stdin,stdout,stderr global variables. Luckily, no
        # other agent really should using these variables when running as daemon, so we should not have any
        # race conditiosn before we set it back.
        orig_fds = sys.stdin, sys.stdout, sys.stderr
        sys.stdin, sys.stdout, sys.stderr = link, link, link
        try:
            self.__interactive_shell(banner)
        finally:
            # Restore the original values.
            sys.stdin, sys.stdout, sys.stderr = orig_fds

    def __interactive_shell(self, banner='interactive shell'):
        """Run an interactive shell.

        @param banner: The banner (message) to show the user when the shell starts up
        @type banner: str
        """
        import code
        if self.__local:
            local = dict(globals(), **self.__local)
        else:
            local = globals()
        code.interact(banner, local=local)