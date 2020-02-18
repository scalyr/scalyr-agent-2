import time

import requests
from six.moves.urllib.parse import quote_plus, urlencode


class ScalyrRequest:
    def __init__(self, read_api_key, max_count=1000, start_time=None):
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

        query = "{}&filter={}".format(params_str, filter_fragments_str)

        # messages = [match["message"] for match in data["matches"]]

        return query


class RequestSender:
    def __init__(self, server_address, ):
        self._server_address = server_address

    def send_request(self, request):
        request_query = request.build()

        fill_query = "https://{}/api/query?queryType=log&{}".format(
            self._server_address,
            request_query
        )

        with requests.Session() as session:
            resp = session.get(fill_query)

        if resp.status_code != 200:
            a = resp.json()
            a = 10

        data = resp.json()

        return data