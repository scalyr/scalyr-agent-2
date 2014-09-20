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
# A ScalyrMonitor which retrieves a specified URL and records the response status and body.

import re
import urllib2
import cookielib

from scalyr_agent import ScalyrMonitor


# Pattern that matches the first line of a string
first_line_pattern = re.compile('[^\r\n]+')


# Redirect handler that doesn't follow any redirects
class NoRedirection(urllib2.HTTPErrorProcessor):
    def __init__(self):
        pass

    def http_response(self, request, response):
        return response

    https_response = http_response


# UrlMonitor implementation
class UrlMonitor(ScalyrMonitor):
    """A Scalyr agent monitor which retrieves a specified URL, and records the response status and body.
    """

    def _initialize(self):
        # Fetch and validate our configuration options.
        #
        # Note that we do NOT currently validate the URL. It would be reasonable to check
        # for valid syntax here, but we should not check that the domain name exists, as an
        # external change (e.g. misconfigured DNS server) could then prevent the agent from
        # starting up.
        self.url = self._config.get("url", required_field=True)
        self.timeout = self._config.get("timeout", default=10, convert_to=float, min_value=0, max_value=30)
        self.max_characters = self._config.get("max_characters", default=200, convert_to=int, min_value=0,
                                               max_value=10000)
        self.log_all_lines = self._config.get("log_all_lines", default=False)

        extract_expression = self._config.get("extract", default="")
        if extract_expression:
            self.extractor = re.compile(extract_expression)
            
            # Verify that the extract expression contains a matching group, i.e. a parenthesized clause.
            # We perform a quick-and-dirty test here, which will work for most regular expressions.
            # If we miss a bad expression, it will result in a stack trace being logged when the monitor
            # executes.
            if extract_expression.find("(") < 0:
                raise Exception("extract expression [%s] must contain a matching group" % extract_expression)
        else:
            self.extractor = None

    def gather_sample(self):
        # Query the URL
        try:
            opener = urllib2.build_opener(NoRedirection, urllib2.HTTPCookieProcessor(cookielib.CookieJar()))
            response = opener.open(self.url, None, self.timeout)
        except urllib2.HTTPError, e:
            self._logger.error("HTTPError retrieving %s: %s" % (self.url, e))
            return
        except urllib2.URLError, e:
            self._logger.error("URLError retrieving %s: %s" % (self.url, e))
            return

        # Read the response, and apply any extraction pattern
        response_body = response.read()
        response.close()
        if self.extractor is not None:
            match = self.extractor.search(response_body)
            if match is not None:
                response_body = match.group(1)

        # Apply log_all_lines and max_characters, and record the result.
        if self.log_all_lines:
            s = response_body
        else:
            first_line = first_line_pattern.search(response_body)
            s = ''
            if first_line is not None:
                s = first_line.group().strip()

        if len(s) > self.max_characters:
            s = s[:self.max_characters] + "..."
        self._logger.emit_value('response', s, extra_fields={'url': self.url, 'status': response.getcode(),
                                                             'length': len(response_body)})
