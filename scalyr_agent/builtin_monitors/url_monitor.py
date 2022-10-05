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

from __future__ import unicode_literals
from __future__ import absolute_import

import re
import traceback

import six
import six.moves.urllib.request
import six.moves.urllib.error
import six.moves.urllib.parse
import six.moves.http_cookiejar
import six.moves.http_client

try:
    from __scalyr__ import SCALYR_VERSION
except ImportError:
    from scalyr_agent.__scalyr__ import SCALYR_VERSION

from scalyr_agent import ScalyrMonitor, define_config_option, define_log_field
from scalyr_agent.json_lib.objects import JsonArray

__monitor__ = __name__

define_config_option(
    __monitor__,
    "module",
    "Always `scalyr_agent.builtin_monitors.url_monitor`",
    required_option=True,
    convert_to=six.text_type,
)
define_config_option(
    __monitor__,
    "id",
    "An id, included with each event. Shows in the UI as a value for the `instance` field. "
    "This is especially useful if you are running multiple instances of this plugin to send "
    "requests to multiple URLs. Each instance has a separate `{...}` stanza in the "
    "configuration file (`/etc/scalyr-agent-2/agent.json`).",
)
define_config_option(
    __monitor__,
    "url",
    "URL for the request. Must be HTTP or HTTPS.",
    required_option=True,
)
define_config_option(
    __monitor__,
    "request_method",
    "Optional (defaults to `GET`). The HTTP request method.",
    required_option=False,
    default="GET",
)
define_config_option(
    __monitor__,
    "request_headers",
    "Optional. HTTP headers for the request. A list of dictionaries, each with "
    "`header`, and  `value` key-value pairs. For example, `request_headers: "
    '[{"header": "Accept-Encoding", "value": "gzip"}]`.',
    required_option=False,
    default=[],
)
define_config_option(
    __monitor__,
    "request_data",
    "Optional. A string of data to pass when `request_method` is POST.",
    required_option=False,
    default=None,
)
define_config_option(
    __monitor__,
    "timeout",
    "Optional. (defaults to `10`). Seconds to wait for the URL to load.",
    default=10,
    convert_to=float,
    min_value=0,
    max_value=30,
)
define_config_option(
    __monitor__,
    "extract",
    "Optional. A regular expression, applied to the request response, that lets you "
    "discard unnecessary data. Must contain a matching group (i.e. a subexpression "
    "enclosed in parentheses). Only the content of the matching group is imported.",
    default="",
)
define_config_option(
    __monitor__,
    "log_all_lines",
    "Optional (defaults to `false`). If `true`, all lines from the request response are imported. "
    "If 'false`, only the first line is imported.",
    default=False,
)
define_config_option(
    __monitor__,
    "max_characters",
    "Optional (defaults to `200`). Maximum characters to import from the request. You may "
    "set a value up to `10000`, but we currently truncate all fields to `3500` characters.",
    default=200,
    convert_to=int,
    min_value=0,
    max_value=10000,
)

define_log_field(__monitor__, "monitor", "Always `url_monitor`.")
define_log_field(__monitor__, "metric", "Always `response`.")
define_log_field(
    __monitor__,
    "instance",
    "The `id` value from the monitor configuration, e.g. `instance-type`.",
)
define_log_field(
    __monitor__,
    "url",
    "The request URL, for example `http://169.254.169.254/latest/meta-data/instance-type`.",
)
define_log_field(
    __monitor__, "status", "The HTTP response code, for example 200 or 404."
)
define_log_field(__monitor__, "length", "The length of the HTTP response.")
define_log_field(__monitor__, "value", "The body of the HTTP response.")


# Pattern that matches the first line of a string
first_line_pattern = re.compile("[^\r\n]+")


# Redirect handler that doesn't follow any redirects
class NoRedirection(six.moves.urllib.request.HTTPErrorProcessor):
    def __init__(self):
        pass

    def http_response(self, request, response):
        return response

    https_response = http_response


# UrlMonitor implementation
class UrlMonitor(ScalyrMonitor):
    # fmt: off
    r"""
# HTTP

GET data from an HTTP or HTTPS URL. You can also POST requests.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).

Requests execute from the machine on which the Agent is running. See [HTTP Monitors](/help/monitors) to execute HTTP requests from our servers.


## Installation

1\. Install the Scalyr Agent

If you haven't already, install the [Scalyr Agent](https://app.scalyr.com/help/welcome). You can send requests to any host and port reachable from the machine running the Agent.


2\. Configure the Scalyr Agent

Open the Scalyr Agent configuration file, located at `/etc/scalyr-agent-2/agent.json`.

Find the `monitors: [ ... ]` section and add a `{...}` stanza with the `module` property set for url:

    monitors: [
      {
        module:  "scalyr_agent.builtin_monitors.url_monitor",
        id:      "instance-type",
        url:     "http://169.254.169.254/latest/meta-data/instance-type"
      }
    ]


The `id` property lets you identify the URL you are importing. It shows in the UI as a value for the `instance` field. This is especially useful if you are running multiple instances of this plugin to issue requests to multiple URLs. Add a separate `{...}` stanza for each instance, and set unique `id`s.

The `url` property is a valid HTTP, or HTTPS URL. The above example imports the instance type of an Amazon EC2 server running the Scalyr Agent.

To issue a `POST`, set the `request_method`, which defaults to `GET`:

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.url_monitor",
        id: "post-example",
        url: "http://your-url-to-make-post-request",
        request_method: "POST",
        request_headers: [{"header": "Accept-Encoding", "value": "gzip"}],
        request_data: "your-request-data"
      }
    ]

The `request_headers` property sets the HTTP headers to send. It is is a list of `{ "header": "...", "value": "..." }` dictionaries. `request_data` is a string of data to send with your request.

See [Configuration Options](#options) below for more properties you can add.


3\. Save and confirm

Save the `agent.json` file. The Agent will detect changes within 30 seconds. Wait a few minutes for the Agent to send data.

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.

Log into Scalyr. From Search view query [monitor = 'url_monitor'](/events?filter=monitor+%3D+%27url_monitor%27). This will show all data, across all servers running this plugin.

For help, contact Support.

    """
    # fmt: on

    def _initialize(self):
        # Fetch and validate our configuration options.
        #
        # Note that we do NOT currently validate the URL. It would be reasonable to check
        # for valid syntax here, but we should not check that the domain name exists, as an
        # external change (e.g. misconfigured DNS server) could then prevent the agent from
        # starting up.
        self.url = self._config.get("url")
        self.request_method = self._config.get("request_method")
        self.request_data = self._config.get("request_data")
        self.request_headers = self._config.get("request_headers")
        self.timeout = self._config.get("timeout")
        self.max_characters = self._config.get("max_characters")
        self.log_all_lines = self._config.get("log_all_lines")

        if self.request_headers and type(self.request_headers) != JsonArray:
            raise Exception(
                "URL Monitor has malformed optional headers: %s"
                % (repr(self.request_headers))
            )

        extract_expression = self._config.get("extract")
        if extract_expression:
            self.extractor = re.compile(extract_expression)

            # Verify that the extract expression contains a matching group, i.e. a parenthesized clause.
            # We perform a quick-and-dirty test here, which will work for most regular expressions.
            # If we miss a bad expression, it will result in a stack trace being logged when the monitor
            # executes.
            if extract_expression.find("(") < 0:
                raise Exception(
                    "extract expression [%s] must contain a matching group"
                    % extract_expression
                )
        else:
            self.extractor = None

        self._base_headers = {
            "User-Agent": "scalyr-agent-%s;monitor=url_monitor" % (SCALYR_VERSION)
        }

    def build_request(self):
        """
        Builds the HTTP request based on the request URL, HTTP headers and method
        @return: Request object
        """
        # TODO: Switch to requests
        request_data = self.request_data

        if six.PY3 and request_data:
            request_data = six.ensure_binary(request_data)

        request = six.moves.urllib.request.Request(self.url, data=request_data)

        for header_key, header_value in six.iteritems(self._base_headers):
            request.add_header(header_key, header_value)

        if self.request_headers:
            for header in self.request_headers:
                request.add_header(header["header"], header["value"])

        # seems awkward to override the GET method, but internally it flips
        # between GET and POST anyway based on the existence of request body
        request.get_method = lambda: self.request_method
        return request

    def gather_sample(self):
        # Query the URL
        try:
            opener = six.moves.urllib.request.build_opener(
                NoRedirection,
                six.moves.urllib.request.HTTPCookieProcessor(
                    six.moves.http_cookiejar.CookieJar()
                ),
            )
            request = self.build_request()
            response = opener.open(request, timeout=self.timeout)
        except six.moves.urllib.error.HTTPError as e:
            self._record_error(e, "http_error")
            return
        except six.moves.urllib.error.URLError as e:
            self._record_error(e, "url_error")
            return
        except Exception as e:
            self._record_error(e, "unknown_error", include_traceback=True)
            return

        # Read the response, and apply any extraction pattern
        try:
            response_body = response.read()
            response.close()
        except six.moves.http_client.IncompleteRead as e:
            self._record_error(e, "incomplete_read")
            return
        except Exception as e:
            self._record_error(e, "unknown_error", include_traceback=True)
            return

        response_body = six.ensure_text(response_body, errors="replace")

        if self.extractor is not None:
            match = self.extractor.search(response_body)
            if match is not None:
                response_body = match.group(1)

        # Apply log_all_lines and max_characters, and record the result.
        if self.log_all_lines:
            s = response_body
        else:
            first_line = first_line_pattern.search(response_body)
            s = ""
            if first_line is not None:
                s = first_line.group().strip()

        if len(s) > self.max_characters:
            s = s[: self.max_characters] + "..."
        self._logger.emit_value(
            "response",
            s,
            extra_fields={
                "url": self.url,
                "status": response.getcode(),
                "length": len(response_body),
                "request_method": self.request_method,
            },
        )

    def _record_error(self, e, error_type, include_traceback=False):
        """Emits a value for the URL metric that reports an error.

        Status code is set to zero and we included an extra field capturing a portion of the exception's name.
        @param e: The exception that caused the problem.
        @param error_type: The error type, used to make the fielld name to hold the exception name.
        @type e: Exception
        @type error_type: str
        """
        # Convert the exception to a string, truncated to 30 chars.
        e_to_str = six.text_type(e)

        if len(e_to_str) > 30:
            e_to_str = e_to_str[0:30] + "..."

        extra_fields = {
            "url": self.url,
            "status": 0,
            "length": 0,
            error_type: e_to_str,
        }

        if include_traceback:
            extra_fields["traceback"] = traceback.format_exc()

        self._logger.emit_value(
            "response",
            "failed",
            extra_fields=extra_fields,
        )
