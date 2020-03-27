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

import scalyr_agent.third_party.requests as requests

from scalyr_agent.connection import Connection


class RequestsConnection(Connection):
    """Class to handle http(s) queries using the Requests library"""

    def __init__(self, server, request_deadline, ca_file, headers, proxies):

        super(RequestsConnection, self).__init__(
            server, request_deadline, ca_file, headers
        )
        self.__response = None
        self.__session = None
        self.__proxies = proxies

    def __verify(self):
        if self._ca_file:
            return self._ca_file
        return False

    def __check_session(self):
        if not self.__session:
            self.__session = requests.Session()
            if self.__proxies is not None:
                self.__session.proxies = self.__proxies
            self.__session.headers.update(self._standard_headers)

    def _post(self, request_path, body):
        url = self._full_address + request_path
        self.__check_session()
        self.__response = self.__session.post(
            url, verify=self.__verify(), timeout=self._request_deadline, data=body
        )

    def _get(self, request_path):
        url = self._full_address + request_path
        self.__check_session()
        self.__response = self.__session.get(
            url, verify=self.__verify(), timeout=self._request_deadline
        )

    def response(self):
        return self.__response.text

    def status_code(self):
        return self.__response.status_code

    def close(self):
        del self.__response
        del self.__session

        self.__response = None
        self.__session = None
