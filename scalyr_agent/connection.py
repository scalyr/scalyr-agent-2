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

from __future__ import unicode_literals
from __future__ import absolute_import

__author__ = "imron@scalyr.com"

import re
import ssl
import socket

import six
import six.moves.http_client

import scalyr_agent.scalyr_logging as scalyr_logging
from scalyr_agent.compat import ssl_match_hostname
from scalyr_agent.compat import CertificateError
from scalyr_agent.compat import PY_post_equal_279


log = scalyr_logging.getLogger(__name__)


class ConnectionFactory:
    """ Factory class for creating connection objects using either Httplib or Requests
    to handle the connection.
    """

    @staticmethod
    def connection(
        server,
        request_deadline,
        ca_file,
        intermediate_certs_file,
        headers,
        use_requests,
        quiet=False,
        proxies=None,
    ):
        """ Create a new connection, with either Requests or Httplib, depending on the
        use_requests parameter.  If Requests is not available, fallback to to Httplib

        @param server: the server to connect to (scheme://domain:port)
        @param request_deadline: The timeout for any requests made on this connection
        @param ca_file: the path to a certificate bundle for ssl verification
        @param intermediate_certs_file: path to certificate bundle for trusted intermediate server certificates
        @param headers: any headers to send with each request made on the connection
        @param use_requests: whether or not to use Requests for handling queries
        @param quiet:  Whether or not to emit non-error log messages.
        @param proxies:  A dict describing the network proxies to use or None if there aren't any.  Only valid if
            use_requests is True.

        @type server: six.text_type
        @type request_deadline: float
        @type ca_file: six.text_type
        @type intermediate_certs_file: six.text_type
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

                result = RequestsConnection(
                    server, request_deadline, ca_file, headers, proxies
                )
            except Exception as e:
                log.warn(
                    "Unable to load requests module '%s'.  Falling back to Httplib for connection handling"
                    % six.text_type(e)
                )
                result = ScalyrHttpConnection(
                    server, request_deadline, ca_file, intermediate_certs_file, headers,
                )
                use_requests = False
        else:
            result = ScalyrHttpConnection(
                server, request_deadline, ca_file, intermediate_certs_file, headers,
            )

        if not quiet:
            if use_requests:
                log.info("Using Requests for HTTP(S) connections")
            else:
                log.info("Using ScalyrHttpConnection/Httplib for HTTP(S) connections")

        return result


class Connection(object):
    """ Connection class
    An abstraction for dealing with different connection types Httplib or Requests
    """

    def __init__(self, server, request_deadline, ca_file, headers):

        # Verify the server address looks right.
        parsed_server = re.match(r"^(http://|https://|)([^:]*)(:\d+|)$", server.lower())

        if parsed_server is None:
            raise Exception('Could not parse server address "%s"' % server)

        # The host for the server.
        self._host = parsed_server.group(2)
        # Whether or not the connection uses SSL.  For production use, this should always be true.  We only
        # use non-SSL when testing against development versions of the Scalyr server.
        self._use_ssl = parsed_server.group(1) == "https://"

        # Determine the port, defaulting to the right one based on protocol if not given.
        if parsed_server.group(3) != "":
            self._port = int(parsed_server.group(3)[1:])
        elif self._use_ssl:
            self._port = 443
        else:
            self._port = 80

        # 2->TODO In python2 httplib accepts request headers as binary string(str),
        #  and in python3 http.client accepts headers as unicode.  In this case 'six.ensure_str' can be very useful.
        self._standard_headers = dict()
        for name, value in six.iteritems(headers):
            self._standard_headers[six.ensure_str(name)] = six.ensure_str(value)

        self._full_address = server
        self._ca_file = ca_file
        self._request_deadline = request_deadline
        self.__connection = None

    def __check_ssl(self):
        """ Helper function to check if ssl is available and enabled """
        if self._use_ssl and not self._ca_file:
            log.warn(
                "Server certificate validation has been disabled while communicating with Scalyr. "
                "This means traffic is encrypted but can be intercepted through a man-in-the-middle attack. "
                "Please update your configuration file to re-enable server certificate validation.",
                limit_once_per_x_secs=86400,
                limit_key="nocertwarning",
                error_code="client/sslverifyoff",
            )

    def post(self, request_path, body):
        """Post requests"""
        self.__check_ssl()
        self._post(request_path, body)

    def get(self, request_path):
        """Get requests"""
        self.__check_ssl()
        self._get(request_path)

    def _post(self, request_path, body):
        """Subclasses override to handle specifics of post requests """
        pass

    def _get(self, request_path):
        """Subclasses override to handle specifics of get requests """
        pass

    def response(self):
        """Subclasses override to return the text contents of a response from a server

        @return: The text contents of a requests
        @rtype: str
        """
        pass

    def status_code(self):
        """Subclasses override to return the status code of a request

        @return: The status code of a request
        """
        pass

    def close(self):
        """Subclasses override to close a connection"""
        pass

    @property
    def is_pure_python_tls(self):
        """Subclasses override to close a connection"""
        pass


class ScalyrHttpConnection(Connection):
    def __init__(
        self, server, request_deadline, ca_file, intermediate_certs_file, headers,
    ):
        super(ScalyrHttpConnection, self).__init__(
            server, request_deadline, ca_file, headers
        )
        self.__http_response = None
        self._intermediate_certs_file = intermediate_certs_file

        self._init_connection()

        log.info("HttpConnection uses native os ssl")

    def _init_connection(self):
        try:
            if self._use_ssl:
                self.__connection = HTTPSConnectionWithTimeoutAndVerification(
                    self._host, self._port, self._request_deadline, self._ca_file,
                )
                self.__connection.connect()
            else:
                # unencrypted connection
                self.__connection = HTTPConnectionWithTimeout(
                    self._host, self._port, self._request_deadline
                )
                self.__connection.connect()
        except Exception as error:
            if hasattr(error, "errno"):
                errno = error.errno  # pylint: disable=no-member
            else:
                errno = None

            error_code = "client/connectionFailed"

            if isinstance(error, CertificateError):
                error_code = "client/connectionFailedCertHostnameValidationFailed"
                log.exception(
                    'Failed to connect to "%s" because of server certificate validation error: "%s". '
                    "This likely indicates a MITM attack.",
                    self._full_address,
                    getattr(error, "message", str(error)),
                    error_code=error_code,
                )
            elif isinstance(error, ssl.SSLError):
                error_code = "client/connectionFailedSSLError"
                log.exception(
                    'Failed to connect to "%s" due to some SSL error.  Possibly the configured certificate '
                    "for the root Certificate Authority could not be parsed, or we attempted to connect to "
                    "a server whose certificate could not be trusted (if so, maybe Scalyr's SSL cert has "
                    "changed and you should update your agent to get the new certificate).  The returned "
                    "errno was %d and the full exception was '%s'.  Closing connection, will re-attempt",
                    self._full_address,
                    errno,
                    six.text_type(error),
                    error_code=error_code,
                )
            elif errno == 61:  # Connection refused
                error_code = "client/connectionFailedConnRefused"
                log.exception(
                    'Failed to connect to "%s" because connection was refused.  Server may be unavailable.',
                    self._full_address,
                    error_code=error_code,
                )
            elif errno == 8:  # Unknown name
                error_code = "client/connectionFailed"
                log.exception(
                    'Failed to connect to "%s" because could not resolve address.  Server host may be bad.',
                    self._full_address,
                    error_code=error_code,
                )
            elif errno is not None:
                error_code = "client/connectionFailed"
                log.exception(
                    'Failed to connect to "%s" due to errno=%d.  Exception was "%s".  Closing connection, '
                    "will re-attempt",
                    self._full_address,
                    errno,
                    six.text_type(error),
                    error_code=error_code,
                )
            else:
                error_code = "client/connectionFailed"
                log.exception(
                    'Failed to connect to "%s" due to exception.  Exception was "%s".  Closing connection, '
                    "will re-attempt",
                    self._full_address,
                    six.text_type(error),
                    error_code=error_code,
                )

            # TODO: We should probably propagate original exception class...
            exc = Exception("%s. Original error: %s" % (error_code, str(error)))
            exc.error_code = error_code
            raise exc

    # 2->TODO ensure that httplib request accepts only binary data, even method name and
    #  request path python2 httplib can not handle mixed data
    def _post(self, request_path, body):
        self.__http_response = None
        self.__connection.request(
            six.ensure_str("POST"),
            six.ensure_str(request_path),
            body=body,
            headers=self._standard_headers,
        )

    def _get(self, request_path):
        self.__http_response = None
        self.__connection.request(
            six.ensure_str("GET"),
            six.ensure_str(request_path),
            headers=self._standard_headers,
        )

    def response(self):
        if not self.__http_response:
            self.__http_response = self.__connection.getresponse()

        return self.__http_response.read()

    def status_code(self):
        if not self.__http_response:
            self.__http_response = self.__connection.getresponse()

        return self.__http_response.status

    def close(self):
        self.__connection.close()


class HTTPConnectionWithTimeout(six.moves.http_client.HTTPConnection):
    """An HTTPConnection replacement with added support for setting a timeout on all blocking operations.

    Older versions of Python (2.4, 2.5) do not allow for setting a timeout directly on httplib.HTTPConnection
    objects.  This is meant to solve that problem generally.
    """

    def __init__(self, host, port, timeout):
        self.__timeout = timeout
        six.moves.http_client.HTTPConnection.__init__(self, host, port)

    def connect(self):
        # This method is essentially copied from 2.7's httplib.HTTPConnection.connect.
        # If socket.create_connection then we use it (as it does in newer Pythons), otherwise, rely on our
        # own way of doing it.
        if hasattr(socket, "create_connection"):
            self.sock = socket.create_connection((self.host, self.port), self.__timeout)
        else:
            self.sock = create_connection_helper(
                self.host, self.port, timeout=self.__timeout
            )
        if hasattr(self, "_tunnel_host") and self._tunnel_host:
            self._tunnel()


class HTTPSConnectionWithTimeoutAndVerification(six.moves.http_client.HTTPSConnection):
    """An HTTPSConnection replacement that adds support for setting a timeout as well as performing server
    certificate validation.

    Older versions of Python (2.4, 2.5) do not allow for setting a timeout directly on httplib.HTTPConnection
    objects, nor do they perform validation of the server certificate.  However, if the user installs the ssl
    Python library, then it is possible to perform server certificate validation even on Python 2.4, 2.5.  This
    class implements the necessary support.
    """

    def __init__(self, host, port, timeout, ca_file):
        """
        Creates an instance.

        Params:
            host: The server host to connect to.
            port: The port to connect to.
            timeout: The timeout, in seconds, to use for all blocking operations on the underlying socket.
            ca_file:  If not None, then this is a file containing the certificate authority's root cert to use
                for validating the certificate sent by the server.
                If None is passed in, then no validation of the server certificate will be done whatsoever, so
                you will be susceptible to man-in-the-middle attacks.  However, at least your traffic will be
                encrypted.
        """
        self.__timeout = timeout
        self.__ca_file = ca_file
        six.moves.http_client.HTTPSConnection.__init__(self, host, port)

    def connect(self):
        # Create the underlying socket.  Prefer Python's newer socket.create_connection method if it is available.
        if hasattr(socket, "create_connection"):
            self.sock = socket.create_connection((self.host, self.port), self.__timeout)
        else:
            self.sock = create_connection_helper(
                self.host, self.port, timeout=self.__timeout
            )

        if hasattr(self, "_tunnel_host") and self._tunnel_host:
            self._tunnel()

        # Now ask the ssl library to wrap the socket and verify the server certificate if we have a ca_file.
        if self.__ca_file:
            if PY_post_equal_279:
                # ssl.PROTOCOL_TLSv1_2 was added in Python 2.7.9 so we request that protocol if we
                # are running on that or newer version. Since July 2020, Scalyr API side now only
                # supports TLSv1.2.
                # On newer versions we also use a more secure SSLContext which gives us more flexibility
                # and control over the options vs using ssl.wrap_socket on older versions
                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
                ssl_context.options |= ssl.OP_NO_SSLv2
                ssl_context.options |= ssl.OP_NO_SSLv3
                ssl_context.options |= ssl.OP_NO_TLSv1
                ssl_context.options |= ssl.OP_NO_TLSv1_1
                ssl_context.verify_mode = ssl.CERT_REQUIRED
                ssl_context.check_hostname = True
                ssl_context.load_verify_locations(self.__ca_file)

                self.sock = ssl_context.wrap_socket(
                    self.sock, do_handshake_on_connect=True, server_hostname=self.host
                )

                # Additional asserts / guards
                assert (
                    self.sock._context.verify_mode == ssl.CERT_REQUIRED
                ), "invalid verify_mode"
                assert (
                    self.sock._context.check_hostname is True
                ), "check_hostname is False"
                # NOTE: By default we use our bundled ca certs file with two CA certs, but user
                # could specify to use a system bundle we can't assert on number being exactly
                # 2
                assert (
                    len(self.sock._context.get_ca_certs()) >= 1
                ), "ca certs not loaded"
                assert (
                    self.sock.do_handshake_on_connect is True
                ), "do_handshake_on_connect is false"
            else:
                # server_hostname argument was added in 2.7.9 so before that version we won't send
                # SNI and also use ssl.wrap_socket instead of ssl.SSLContext
                self.sock = ssl.wrap_socket(
                    self.sock, ca_certs=self.__ca_file, cert_reqs=ssl.CERT_REQUIRED
                )

                # Additional asserts / guards
                assert self.sock.ca_certs, "ca_certs is falsy"
                assert self.sock.cert_reqs == ssl.CERT_REQUIRED, "cert_reqs is invalid"
                assert (
                    self.sock.do_handshake_on_connect is True
                ), "do_handshake_on_connect is false"

            # NOTE: In newer versions of Python when using SSLContext + check_hostname = True, this
            # should happen automatically post handshake, but to also support older versions and
            # ensure this verification is always performed, we call this method manually here.
            # Will throws CertificateError in case host validation fails
            cert = self.sock.getpeercert()
            ssl_match_hostname(cert=cert, hostname=self.host)
        else:
            log.warn(
                "Server certificate validation has been disabled while communicating with Scalyr. "
                "This means traffic is encrypted but can be intercepted through a man-in-the-middle attack. "
                "Please update your configuration file to re-enable server certificate validation.",
                limit_once_per_x_secs=86400,
                limit_key="nocertwarning",
                error_code="client/sslverifyoff",
            )

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

        except socket.error as _:
            err = _
            if sock is not None:
                sock.close()

    if err is not None:
        raise err
    else:
        raise socket.error("getaddrinfo returns an empty list")
