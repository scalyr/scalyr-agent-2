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

from __future__ import unicode_literals
from __future__ import print_function
from __future__ import absolute_import
import time

import requests
from six.moves.urllib.parse import quote_plus, urlencode


class ScalyrRequest:
    """
    Abstraction to create scalyr API requests.
    """

    def __init__(self, server_address, read_api_key, max_count=1000, start_time=None):
        self._server_address = server_address
        self._read_api_key = read_api_key
        self._max_count = max_count
        self._start_time = start_time

        self._filters = list()

    def add_filter(self, expr):
        expr = quote_plus(expr)
        self._filters.append(expr)

    def build(self):
        params = {
            "maxCount": self._max_count,
            "startTime": self._start_time or time.time(),
            "token": self._read_api_key,
        }

        params_str = urlencode(params)

        filter_fragments_str = "+and+".join(self._filters)

        query = "{0}&filter={1}".format(params_str, filter_fragments_str)

        return query

    def send(self):
        query = self.build()

        protocol = "https://" if not self._server_address.startswith("http") else ""

        full_query = "{0}{1}/api/query?queryType=log&{2}".format(
            protocol, self._server_address, query
        )

        print("Query server: {0}".format(full_query))

        with requests.Session() as session:
            resp = session.get(full_query, verify=False)

        data = resp.json()

        return data
