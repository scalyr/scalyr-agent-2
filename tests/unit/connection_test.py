# Copyright 2014-2020 Scalyr Inc.
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

from __future__ import absolute_import

from scalyr_agent import scalyr_init

scalyr_init()

import os
import sys
import ssl
import socket

from scalyr_agent.compat import PY26
from scalyr_agent.compat import PY_post_equal_279
from scalyr_agent.connection import ConnectionFactory
from scalyr_agent.connection import HTTPSConnectionWithTimeoutAndVerification

from scalyr_agent.test_base import ScalyrTestCase

BASE_DIR = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))

CA_FILE = os.path.join(BASE_DIR, "fixtures/certs/ca_certs.crt")
INTERMEDIATE_CERTS_FILE = os.path.join(
    BASE_DIR, "fixtures/certs/intermediate_certs.pem"
)

SCALYR_COM_PEM_PATH = os.path.join(BASE_DIR, "fixtures/certs/scalyr_com.pem")
EXAMPLE_COM_PEM_PATH = os.path.join(BASE_DIR, "fixtures/certs/example_com.pem")

ORIGINAL_SOCKET_CREATE_CONNECTION = socket.create_connection
ORIGINAL_SOCKET_GETADDR_INFO = socket.getaddrinfo


class ScalyrNativeHttpConnectionTestCase(ScalyrTestCase):
    def tearDown(self):
        socket.create_connection = ORIGINAL_SOCKET_CREATE_CONNECTION

    def test_connect_valid_cert_and_hostname_success(self):
        connection = self._get_connection_cls(server="https://agent.scalyr.com:443")

        conn = connection._ScalyrHttpConnection__connection  # pylint: disable=no-member
        self.assertTrue(isinstance(conn, HTTPSConnectionWithTimeoutAndVerification))

        if PY_post_equal_279:
            self.assertEqual(conn.sock._context.verify_mode, ssl.CERT_REQUIRED)
            self.assertEqual(conn.sock._context.check_hostname, True)
        else:
            self.assertEqual(conn.sock.cert_reqs, ssl.CERT_REQUIRED)
            self.assertEqual(conn.sock.ca_certs, CA_FILE)

    def test_connect_valid_cert_invalid_hostname_failure(self):
        # TODO: Add the same tests but where we mock the host on system level (e.g. via
        # /etc/hosts entry)
        def mock_create_connection(address_pair, timeout, **kwargs):
            # We want to connect to the actual Scalyr agent endpoint, but actual host
            # specified in the config to be different
            assert address_pair[0] == "agent.invalid.scalyr.com"
            new_address_pair = ("agent.scalyr.com", address_pair[1])
            return ORIGINAL_SOCKET_CREATE_CONNECTION(
                new_address_pair, timeout, **kwargs
            )

        socket.create_connection = mock_create_connection

        try:
            if sys.version_info >= (3, 7, 0):
                expected_msg = r"Original error: .*Hostname mismatch.*"  # NOQA
            else:
                expected_msg = (
                    r"Original error: hostname 'agent.invalid.scalyr.com' doesn't match either "
                    r"of '\*.scalyr.com', 'scalyr.com'"
                )  # NOQA

            self.assertRaisesRegexp(
                Exception,
                expected_msg,
                self._get_connection_cls,
                server="https://agent.invalid.scalyr.com:443",
            )
        finally:
            socket.create_connection = ORIGINAL_SOCKET_CREATE_CONNECTION

    def test_connect_invalid_cert_failure(self):
        if PY26:
            # Under Python 2.6, error looks like this:
            # [Errno 1] _ssl.c:498: error:14090086:SSL
            # routines:SSL3_GET_SERVER_CERTIFICATE:certificate verify failed
            expected_msg = r"certificate verify failed"
        else:
            expected_msg = r"Original error: \[SSL: CERTIFICATE_VERIFY_FAILED\]"
        self.assertRaisesRegexp(
            Exception,
            expected_msg,
            self._get_connection_cls,
            server="https://example.com:443",
        )

    def _get_connection_cls(self, server):
        connection = ConnectionFactory.connection(
            server=server,
            request_deadline=10,
            ca_file=CA_FILE,
            intermediate_certs_file=INTERMEDIATE_CERTS_FILE,
            headers={},
            use_requests=False,
            quiet=False,
            proxies=None,
        )

        return connection


class ScalyrRequestsHttpConnectionTestCase(ScalyrTestCase):
    # NOTE: With the requests library, connection is established lazily on first request and
    # that's also when SSL handshake and cert + hostname validation happens
    def tearDown(self):
        socket.getaddrinfo = ORIGINAL_SOCKET_GETADDR_INFO

    def test_connect_valid_cert_and_hostname_success(self):
        connection = self._get_connection_cls(server="https://agent.scalyr.com:443")
        # pylint: disable=no-member
        self.assertIsNone(connection._RequestsConnection__response)
        self.assertIsNone(connection._RequestsConnection__session)
        # pylint: enable=no-member

        connection._get("/")
        # pylint: disable=no-member
        self.assertTrue(connection._RequestsConnection__response)
        self.assertTrue(connection._RequestsConnection__session)
        # pylint: enable=no-member

    def test_connect_valid_cert_invalid_hostname_failure(self):
        # TODO: Add the same tests but where we mock the host on system level (e.g. via
        # /etc/hosts entry)
        def mock_socket_getaddrinfo(host, *args, **kwargs):
            # We want to connect to the actual Scalyr agent endpoint, but actual host
            # specified in the config to be different
            assert host == "agent.invalid.scalyr.com"
            new_host = "agent.scalyr.com"
            return ORIGINAL_SOCKET_GETADDR_INFO(new_host, *args, **kwargs)

        socket.getaddrinfo = mock_socket_getaddrinfo

        try:
            connection = self._get_connection_cls(
                server="https://agent.invalid.scalyr.com:443",
            )

            # pylint: disable=no-member
            self.assertIsNone(connection._RequestsConnection__response)
            self.assertIsNone(connection._RequestsConnection__session)
            # pylint: enable=no-member

            expected_msg = r"hostname 'agent.invalid.scalyr.com' doesn't match either of '\*.scalyr.com', 'scalyr.com'"
            self.assertRaisesRegexp(
                Exception,
                expected_msg,
                connection.get,
                request_path="/",
            )

            # pylint: disable=no-member
            self.assertIsNone(connection._RequestsConnection__response)
            self.assertTrue(connection._RequestsConnection__session)
            # pylint: enable=no-member
        finally:
            connection._RequestsConnection__session = None
            socket.getaddrinfo = ORIGINAL_SOCKET_CREATE_CONNECTION

    def test_connect_invalid_cert_failure(self):
        if PY26:
            # Under Python 2.6, error looks like this:
            # [Errno 1] _ssl.c:498: error:14090086:SSL
            # routines:SSL3_GET_SERVER_CERTIFICATE:certificate verify failed
            expected_msg = r"certificate verify failed"
        else:
            expected_msg = r"\[SSL: CERTIFICATE_VERIFY_FAILED\]"

        connection = self._get_connection_cls(server="https://example.com:443")
        self.assertRaisesRegexp(
            Exception,
            expected_msg,
            connection.get,
            request_path="/",
        )

    def _get_connection_cls(self, server):
        connection = ConnectionFactory.connection(
            server=server,
            request_deadline=10,
            ca_file=CA_FILE,
            intermediate_certs_file=INTERMEDIATE_CERTS_FILE,
            headers={},
            use_requests=True,
            quiet=False,
            proxies=None,
        )

        return connection
