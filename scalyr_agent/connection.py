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

import os
import re
import socket
import subprocess
import sys
from tempfile import mkstemp
from io import open

import six
import six.moves.http_client

import scalyr_agent.scalyr_logging as scalyr_logging


log = scalyr_logging.getLogger(__name__)

# noinspection PyBroadException
try:
    import ssl

    __has_ssl__ = True
except Exception:
    __has_ssl__ = False
    ssl = None  # type: ignore


__has_pure_python_tls__ = False
try:
    from tlslite import (  # pylint: disable=import-error
        HTTPTLSConnection,
        HandshakeSettings,
    )

    __has_pure_python_tls__ = True
except Exception:
    pass


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
        use_tlslite,
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
        @param use_tlslite: whether or not to use TLSLite for TLS connections
        @param quiet:  Whether or not to emit non-error log messages.
        @param proxies:  A dict describing the network proxies to use or None if there aren't any.  Only valid if
            use_requests is True.

        @type server: six.text_type
        @type request_deadline: float
        @type ca_file: six.text_type
        @type intermediate_certs_file: six.text_type
        @type headers: dict
        @type use_requests: bool
        @type use_tlslite: bool
        @type quiet: bool
        @type proxies: dict

        @return: A new Connection object
        @rtype: Connection

        """

        if use_tlslite:
            if use_requests:
                log.warn(
                    "Both `use_requests_lib` and `use_tlslite` are set to True.  `use_tlslite` is ignored if `use_requests_lib` is True"
                )

            if sys.version_info[:3] >= (2, 7, 9):
                log.warn(
                    "`use_tlslite` is only valid when running on Python 2.7.8 or below"
                )
                use_tlslite = False

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
                    server,
                    request_deadline,
                    ca_file,
                    intermediate_certs_file,
                    headers,
                    use_tlslite,
                )
                use_requests = False
        else:
            result = ScalyrHttpConnection(
                server,
                request_deadline,
                ca_file,
                intermediate_certs_file,
                headers,
                use_tlslite,
            )

        if not quiet:
            if use_requests:
                log.info("Using Requests for HTTP(S) connections")
            else:
                if result.is_pure_python_tls:
                    log.info(
                        "Using ScalyrHttpConnection/tlslite for HTTP(S) connections"
                    )
                else:
                    log.info(
                        "Using ScalyrHttpConnection/Httplib for HTTP(S) connections"
                    )

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
        if self._use_ssl:
            if not __has_ssl__ and not __has_pure_python_tls__:
                log.warn(
                    "No ssl library available so cannot verify server certificate when communicating with Scalyr. "
                    "This means traffic is encrypted but can be intercepted through a man-in-the-middle attack. "
                    "To solve this, install the Python ssl library. "
                    "For more details, see https://www.scalyr.com/help/scalyr-agent#ssl",
                    limit_once_per_x_secs=86400,
                    limit_key="nosslwarning",
                    error_code="client/nossl",
                )
            elif self._ca_file is None:
                log.warn(
                    "Server certificate validation has been disabled while communicating with Scalyr. "
                    "This means traffic is encrypted but can be intercepted through a man-in-the-middle attach. "
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


class CertValidationError(Exception):
    pass


class ScalyrHttpConnection(Connection):
    def __init__(
        self,
        server,
        request_deadline,
        ca_file,
        intermediate_certs_file,
        headers,
        use_tlslite,
    ):
        super(ScalyrHttpConnection, self).__init__(
            server, request_deadline, ca_file, headers
        )
        self.__http_response = None
        self._intermediate_certs_file = intermediate_certs_file

        try:
            self._init_connection(pure_python_tls=use_tlslite)
        except Exception:  # echee TODO: more specific exception representative of TLS1.2 incompatibility
            log.info(
                "Exception while attempting to init HTTP Connection.  Falling back to pure-python TLS implementation"
            )
            self._init_connection(pure_python_tls=True)

        if self.is_pure_python_tls:
            log.info("HttpConnection uses pure-python TLS")
        else:
            log.info("HttpConnection uses native os ssl")

    def _validate_chain_openssl(self):
        """Validate server certificate chain using openssl system callout"""
        # fetch end-entity certificate and write to tempfile
        end_entity_pem = ssl.get_server_certificate((self._host, self._port))
        try:
            end_entity_pem_tempfile_fd, end_entity_pem_tempfile_path = mkstemp()
            # NOTE: We close the fd here because we open it again below. This way file deletion at
            # the end works correctly on Windows.
            os.close(end_entity_pem_tempfile_fd)

            with os.fdopen(end_entity_pem_tempfile_fd, "w") as fp:
                fp.write(end_entity_pem)

            # invoke openssl
            # root_certs = '/usr/share/scalyr-agent-2/certs/ca_certs.crt'
            # intermediate_certs = '/usr/share/scalyr-agent-2/certs/intermediate_certs.pem'
            cmd = [
                "openssl",
                "verify",
                "-CAfile",
                self._ca_file,
                "-untrusted",
                self._intermediate_certs_file,
                end_entity_pem_tempfile_path,
            ]
            log.debug("Validating server certificate chain via: %s" % cmd)
            proc = subprocess.Popen(
                args=" ".join(cmd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True,
            )
            out, err = proc.communicate()
            returncode = proc.returncode
            if returncode != 0:
                raise CertValidationError(err.strip())
            log.info("Scalyr server cert chain successfully validated via openssl")
        finally:
            # delete temp file
            os.remove(end_entity_pem_tempfile_path)

    def _validate_chain_certvalidator(self, tlslite_connection):
        """Validate server certificate chain using 3rd party certvalidator library which uses oscrypt/libcrypto
        Note: oscrypt uses ctypes find_library() which does not work in certain distributions such as alpine.
        (e.g. see https://github.com/docker-library/python/issues/111)
        On such systems, users will have to rely on other server cert validation approaches such as using openssl
        or turning it off completely.
        """
        try:
            # pylint: disable=import-error,no-name-in-module
            from certvalidator import CertificateValidator
            from certvalidator import ValidationContext
            from asn1crypto import (
                x509,
                pem,
            )

            # pylint: enable=import-error,no-name-in-module

            # validate server certificate chain
            session = tlslite_connection.sock.session
            assert type(session.serverCertChain.x509List) == list

            # get the end-entity cert
            file_bytes = session.serverCertChain.x509List[0].bytes
            end_entity_cert = x509.Certificate.load(six.binary_type(file_bytes))

            def cert_files_exist(path, file_names):
                file_names = [os.path.join(path, f) for f in file_names]
                for f in file_names:
                    if not os.path.isfile(f):
                        return False
                return True

            def get_cert_bytes(cert_dir, file_names):
                file_names = [os.path.join(cert_dir, f) for f in file_names]
                result = []
                for fname in file_names:
                    arr = open(fname, "rb").read()
                    cert_bytes = pem.unarmor(arr)[2]
                    result.append(cert_bytes)
                return result

            intermediate_cert_names = [
                "comodo_ca_intermediate.pem",
                "sectigo_ca_intermediate.pem",
            ]

            extra_trust_names = [
                "scalyr_agent_ca_root.pem",
                "addtrust_external_ca_root.pem",
            ]

            # Determine the directory containing the certs.
            # First check the directory containing the _ca_file
            # but if we don't find the intermediate/extra certs there
            # then look in the relative `certs` directory.  The latter
            # will typically be required if running directly from source
            all_cert_names = intermediate_cert_names + extra_trust_names
            cert_dir = os.path.dirname(self._ca_file)
            if not cert_files_exist(cert_dir, all_cert_names):
                path = os.path.dirname(os.path.abspath(__file__))
                path = os.path.abspath(path + "../../certs")
                if cert_files_exist(path, all_cert_names):
                    cert_dir = path

            trust_roots = None
            intermediate_certs = get_cert_bytes(cert_dir, intermediate_cert_names)
            extra_trust_roots = get_cert_bytes(cert_dir, extra_trust_names)

            if trust_roots:
                context = ValidationContext(
                    trust_roots=trust_roots,
                    extra_trust_roots=extra_trust_roots,
                    other_certs=intermediate_certs,
                    # whitelisted_certs=[end_entity_cert.sha1_fingerprint],
                )
            else:
                context = ValidationContext(
                    extra_trust_roots=extra_trust_roots,
                    other_certs=intermediate_certs,
                    # whitelisted_certs=[end_entity_cert.sha1_fingerprint],
                )
                validator = CertificateValidator(
                    end_entity_cert, validation_context=context
                )
            validator.validate_tls(six.text_type(self._host))
            log.info(
                "Scalyr server cert chain successfully validated via certvalidator library"
            )
        except Exception as ce:
            log.exception("Error validating server certificate chain: %s" % ce)
            raise

    def _init_connection(self, pure_python_tls=False):
        try:
            if self._use_ssl:
                if not pure_python_tls:
                    # If we do not have the SSL library, then we cannot do server certificate validation anyway.
                    if __has_ssl__:
                        ca_file = self._ca_file
                    else:
                        ca_file = None
                    self.__connection = HTTPSConnectionWithTimeoutAndVerification(
                        self._host,
                        self._port,
                        self._request_deadline,
                        ca_file,
                        __has_ssl__,
                    )
                    self.__connection.connect()
                else:
                    # Pure python implementation of TLS does not require ssl library
                    settings = HandshakeSettings()
                    settings.minVersion = (3, 3)  # TLS 1.2
                    self.__connection = HTTPTLSConnection(
                        self._host,
                        self._port,
                        timeout=self._request_deadline,
                        settings=settings,
                    )
                    self.__connection.connect()
                    # Non-null _ca_file signifies server cert validation is requireds
                    if self._ca_file:
                        try:
                            self._validate_chain_certvalidator(self.__connection)
                        except Exception:
                            log.exception("Failure in _validate_chain_certvalidator()")
                            self._validate_chain_openssl()
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
            if isinstance(error, CertValidationError):
                log.error(
                    'Failed to connect to "%s" because of server certificate validation error: "%s"',
                    self._full_address,
                    getattr(error, "message", str(error)),
                    error_code="client/connectionFailed",
                )
            elif __has_ssl__ and isinstance(error, ssl.SSLError):
                log.error(
                    'Failed to connect to "%s" due to some SSL error.  Possibly the configured certificate '
                    "for the root Certificate Authority could not be parsed, or we attempted to connect to "
                    "a server whose certificate could not be trusted (if so, maybe Scalyr's SSL cert has "
                    "changed and you should update your agent to get the new certificate).  The returned "
                    "errno was %d and the full exception was '%s'.  Closing connection, will re-attempt",
                    self._full_address,
                    errno,
                    six.text_type(error),
                    error_code="client/connectionFailed",
                )
            elif errno == 61:  # Connection refused
                log.error(
                    'Failed to connect to "%s" because connection was refused.  Server may be unavailable.',
                    self._full_address,
                    error_code="client/connectionFailed",
                )
            elif errno == 8:  # Unknown name
                log.error(
                    'Failed to connect to "%s" because could not resolve address.  Server host may be bad.',
                    self._full_address,
                    error_code="client/connectionFailed",
                )
            elif errno is not None:
                log.error(
                    'Failed to connect to "%s" due to errno=%d.  Exception was "%s".  Closing connection, '
                    "will re-attempt",
                    self._full_address,
                    errno,
                    six.text_type(error),
                    error_code="client/connectionFailed",
                )
            else:
                log.error(
                    'Failed to connect to "%s" due to exception.  Exception was "%s".  Closing connection, '
                    "will re-attempt",
                    self._full_address,
                    six.text_type(error),
                    error_code="client/connectionFailed",
                )
            raise Exception("client/connectionFailed")

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

    @property
    def is_pure_python_tls(self):
        return __has_pure_python_tls__ and isinstance(
            self.__connection, HTTPTLSConnection
        )


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
            raise Exception(
                "If has_ssl is false, you are not allowed to specify a ca_file because it has no affect."
            )
        self.__timeout = timeout
        self.__ca_file = ca_file
        self.__has_ssl = has_ssl
        six.moves.http_client.HTTPSConnection.__init__(self, host, port)

    def connect(self):
        # Do not delete the next line:
        # SIMULATE_TLS12_FAILURE raise Exception('Fake a failed connection with ssl lib')

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
                six.moves.http_client.HTTPSConnection.connect(self)
                return
            finally:
                socket.setdefaulttimeout(old_timeout)

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
        if self.__ca_file is not None:
            self.sock = ssl.wrap_socket(
                self.sock, ca_certs=self.__ca_file, cert_reqs=ssl.CERT_REQUIRED
            )
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

        except socket.error as _:
            err = _
            if sock is not None:
                sock.close()

    if err is not None:
        raise err
    else:
        raise socket.error("getaddrinfo returns an empty list")
