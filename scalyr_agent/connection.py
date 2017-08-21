# Copyright 2016 Scalyr Inc.
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
# author: Imron Alston <imron@scalyr.com>

__author__ = 'imron@scalyr.com'

import httplib
import re
import socket

import scalyr_agent.scalyr_logging as scalyr_logging

log = scalyr_logging.getLogger(__name__)

# noinspection PyBroadException
try:
    import ssl
    __has_ssl__ = True
except Exception:
    __has_ssl__ = False
    ssl = None


class ConnectionFactory:
    """ Factory class for creating connection objects using either Httplib or Requests
    to handle the connection.
    """
    @staticmethod
    def connection( server, request_deadline, ca_file, headers, use_requests, quiet=False, proxies=None):
        """ Create a new connection, with either Requests or Httplib, depending on the
        use_requests parameter.  If Requests is not available, fallback to to Httplib

        @param server: the server to connect to (scheme://domain:port)
        @param request_deadline: The timeout for any requests made on this connection
        @param ca_file: the path to a certifcate bundle for ssl verification
        @param headers: any headers to send with each request made on the connection
        @param use_requests: whether or not to use Requests for handling queries
        @param quiet:  Whether or not to emit non-error log messages.
        @param proxies:  A dict describing the network proxies to use or None if there aren't any.  Only valid if
            use_requests is True.

        @type server: str
        @type request_deadline: float
        @type ca_file: str
        @type headers: dict
        @type use_requests: bool
        @type quiet: bool
        @type proxies: dict

        @return: A new Connection object
        @rtype: Connection

        """

        result = None
        if use_requests:
            try:
                from scalyr_agent.requests_connection import RequestsConnection
                result = RequestsConnection( server, request_deadline, ca_file, headers, proxies)
            except Exception, e:
                log.warn( "Unable to load requests module '%s'.  Falling back to Httplib for connection handling" % str( e ) )
                result = HttplibConnection( server, request_deadline, ca_file, headers )
                use_requests = False
        else:
            result = HttplibConnection( server, request_deadline, ca_file, headers)

        if not quiet:
            if use_requests:
                log.info( "Using Requests for HTTP(S) connections" )
            else:
                log.info( "Using Httplib for HTTP(S) connections" )

        return result

class Connection( object ):
    """ Connection class
    An abstraction for dealing with different connection types Httplib or Requests
    """

    def __init__( self, server, request_deadline, ca_file, headers ):

        # Verify the server address looks right.
        parsed_server = re.match('^(http://|https://|)([^:]*)(:\d+|)$', server.lower())

        if parsed_server is None:
            raise Exception('Could not parse server address "%s"' % server)

        # The host for the server.
        self._host = parsed_server.group(2)
        # Whether or not the connection uses SSL.  For production use, this should always be true.  We only
        # use non-SSL when testing against development versions of the Scalyr server.
        self._use_ssl = parsed_server.group(1) == 'https://'

        # Determine the port, defaulting to the right one based on protocol if not given.
        if parsed_server.group(3) != '':
            self._port = int(parsed_server.group(3)[1:])
        elif self._use_ssl:
            self._port = 443
        else:
            self._port = 80

        self._standard_headers = headers
        self._full_address = server
        self._ca_file = ca_file
        self._request_deadline = request_deadline
            
    def __check_ssl( self ):
        """ Helper function to check if ssl is available and enabled """
        if self._use_ssl:
            if not __has_ssl__:
                log.warn('No ssl library available so cannot verify server certificate when communicating with Scalyr. '
                         'This means traffic is encrypted but can be intercepted through a man-in-the-middle attack. '
                         'To solve this, install the Python ssl library. '
                         'For more details, see https://www.scalyr.com/help/scalyr-agent#ssl',
                         limit_once_per_x_secs=86400, limit_key='nosslwarning', error_code='client/nossl')
            elif self._ca_file is None:
                log.warn('Server certificate validation has been disabled while communicating with Scalyr. '
                         'This means traffic is encrypted but can be intercepted through a man-in-the-middle attach. '
                         'Please update your configuration file to re-enable server certificate validation.',
                         limit_once_per_x_secs=86400, limit_key='nocertwarning', error_code='client/sslverifyoff')

    def post( self, request_path, body ):
        """Post requests"""
        self.__check_ssl()
        self._post( request_path, body )

    def get( self, request_path ):
        """Get requests"""
        self.__check_ssl()
        self._get( request_path, body )

    def _post( self, request_path, body ):
        """Subclasses override to handle specifics of post requests """
        pass
    
    def _get( self, request_path ):
        """Subclasses override to handle specifics of get requests """
        pass

    def response( self ):
        """Subclasses override to return the text contents of a response from a server
        
        @return: The text contents of a requests
        @rtype: str
        """
        pass
        
    def status_code( self ):
        """Subclasses override to return the status code of a request
        
        @return: The status code of a request
        """
        pass

    def close( self ):
        """Subclasses override to close a connection"""
        pass

class HttplibConnection( Connection ):
    def __init__( self, server, request_deadline, ca_file, headers ):

        super( HttplibConnection, self ).__init__( server, request_deadline, ca_file, headers )
        self.__http_response = None

        try:
            if self._use_ssl:
                # If we do not have the SSL library, then we cannot do server certificate validation anyway.
                if __has_ssl__:
                    ca_file = self._ca_file
                else:
                    ca_file = None
                self.__connection = HTTPSConnectionWithTimeoutAndVerification(self._host, self._port,
                                                                              self._request_deadline,
                                                                              ca_file, __has_ssl__)

            else:
                self.__connection = HTTPConnectionWithTimeout(self._host, self._port, self._request_deadline)
            self.__connection.connect()
        except (socket.error, socket.herror, socket.gaierror), error:
            if hasattr(error, 'errno'):
                errno = error.errno
            else:
                errno = None
            if __has_ssl__ and isinstance(error, ssl.SSLError):
                log.error('Failed to connect to "%s" due to some SSL error.  Possibly the configured certificate '
                          'for the root Certificate Authority could not be parsed, or we attempted to connect to '
                          'a server whose certificate could not be trusted (if so, maybe Scalyr\'s SSL cert has '
                          'changed and you should update your agent to get the new certificate).  The returned '
                          'errno was %d and the full exception was \'%s\'.  Closing connection, will re-attempt',
                          self._full_address, errno, str(error), error_code='client/connectionFailed')
            elif errno == 61:  # Connection refused
                log.error('Failed to connect to "%s" because connection was refused.  Server may be unavailable.',
                          self._full_address, error_code='client/connectionFailed')
            elif errno == 8:  # Unknown name
                log.error('Failed to connect to "%s" because could not resolve address.  Server host may be bad.',
                          self._full_address, error_code='client/connectionFailed')
            elif errno is not None:
                log.error('Failed to connect to "%s" due to errno=%d.  Exception was %s.  Closing connection, '
                          'will re-attempt', self._full_address, errno, str(error),
                          error_code='client/connectionFailed')
            else:
                log.error('Failed to connect to "%s" due to exception.  Exception was %s.  Closing connection, '
                          'will re-attempt', self._full_address, str(error),
                          error_code='client/connectionFailed')
            raise Exception( "client/connectionFailed" )

    def _post( self, request_path, body ):
        self.__http_response = None
        self.__connection.request( 'POST', request_path, body=body, headers=self._standard_headers )

    def _get( self, request_path ):
        self.__http_response = None
        self.__connection.request( 'GET', request_path, headers=self._standard_headers )

    def response( self ):
        if not self.__http_response:
            self.__http_response = self.__connection.getresponse()
        
        return self.__http_response.read()
        
    def status_code( self ):
        if not self.__http_response:
            self.__http_response = self.__connection.getresponse()
        
        return self.__http_response.status

    def close( self ):
        self.__connection.close()

class HTTPConnectionWithTimeout(httplib.HTTPConnection):
    """An HTTPConnection replacement with added support for setting a timeout on all blocking operations.

    Older versions of Python (2.4, 2.5) do not allow for setting a timeout directly on httplib.HTTPConnection
    objects.  This is meant to solve that problem generally.
    """
    def __init__(self, host, port, timeout):
        self.__timeout = timeout
        httplib.HTTPConnection.__init__(self, host, port)

    def connect(self):
        # This method is essentially copied from 2.7's httplib.HTTPConnection.connect.
        # If socket.create_connection then we use it (as it does in newer Pythons), otherwise, rely on our
        # own way of doing it.
        if hasattr(socket, 'create_connection'):
            self.sock = socket.create_connection((self.host, self.port), self.__timeout)
        else:
            self.sock = create_connection_helper(self.host, self.port, timeout=self.__timeout)
        if self._tunnel_host:
            self._tunnel()


class HTTPSConnectionWithTimeoutAndVerification(httplib.HTTPSConnection):
    """An HTTPSConnection replacement that adds support for setting a timeout as well as performing server
    certificate validation.

    Older versions of Python (2.4, 2.5) do not allow for setting a timeout directly on httplib.HTTPConnection
    objects, nor do they perform validation of the server certificate.  However, if the user installs the ssl
    Python library, then it is possible to perform server certificate validation even on Python 2.4, 2.5.  This
    class implements the necessary support.
    """
    def __init__(self, host, port, timeout, ca_file, has_ssl):
        """
        Creates an instance.

        Params:
            host: The server host to connect to.
            port: The port to connect to.
            timeout: The timeout, in seconds, to use for all blocking operations on the underlying socket.
            ca_file:  If not None, then this is a file containing the certificate authority's root cert to use
                for validating the certificate sent by the server.  This must be None if has_ssl is False.
                If None is passed in, then no validation of the server certificate will be done whatsoever, so
                you will be susceptible to man-in-the-middle attacks.  However, at least your traffic will be
                encrypted.
            has_ssl:  True if the ssl Python library is available.
        """
        if not has_ssl and ca_file is not None:
            raise Exception('If has_ssl is false, you are not allowed to specify a ca_file because it has no affect.')
        self.__timeout = timeout
        self.__ca_file = ca_file
        self.__has_ssl = has_ssl
        httplib.HTTPSConnection.__init__(self, host, port)

    def connect(self):
        # If the ssl library is not available, then we just have to fall back on old HTTPSConnection.connect
        # method.  There are too many dependencies to implement it directly here.
        if not self.__has_ssl:
            # Unfortunately, the only way to set timeout is to temporarily set the global default timeout
            # for what it should be for this connection, and then reset it once the connection is established.
            # Messy, but not much we can do.
            old_timeout = None
            try:
                old_timeout = socket.getdefaulttimeout()
                socket.setdefaulttimeout(self.__timeout)
                httplib.HTTPSConnection.connect(self)
                return
            finally:
                socket.setdefaulttimeout(old_timeout)

        # Create the underlying socket.  Prefer Python's newer socket.create_connection method if it is available.
        if hasattr(socket, 'create_connection'):
            self.sock = socket.create_connection((self.host, self.port), self.__timeout)
        else:
            self.sock = create_connection_helper(self.host, self.port, timeout=self.__timeout)

        if self._tunnel_host:
            self._tunnel()

        # Now ask the ssl library to wrap the socket and verify the server certificate if we have a ca_file.
        if self.__ca_file is not None:
            self.sock = ssl.wrap_socket(self.sock, ca_certs=self.__ca_file, cert_reqs=ssl.CERT_REQUIRED)
        else:
            self.sock = ssl.wrap_socket(self.sock, cert_reqs=ssl.CERT_NONE)


def create_connection_helper(host, port, timeout=None, source_address=None):
    """Creates and returns a socket connecting to host:port with the specified timeout.

    @param host: The host to connect to.
    @param port: The port to connect to.
    @param timeout: The timeout in seconds to use for all blocking operations on the socket.
    @param source_address: The source address, or None.

    @return: The connected socket
    """
    # This method was copied from Python 2.7's socket.create_connection.
    err = None
    for res in socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM):
        af, socktype, proto, canonname, sa = res
        sock = None
        try:
            sock = socket.socket(af, socktype, proto)
            if timeout is not None:
                sock.settimeout(timeout)
            if source_address is not None:
                sock.bind(source_address)
            sock.connect(sa)
            return sock

        except socket.error, _:
            err = _
            if sock is not None:
                sock.close()

    if err is not None:
        raise err
    else:
        raise socket.error("getaddrinfo returns an empty list")

