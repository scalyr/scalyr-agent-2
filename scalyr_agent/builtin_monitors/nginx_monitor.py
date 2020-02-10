# Copyright 2014, Scalyr, Inc.
#
# Note, this can be run in standalone mode by:
# python -m scalyr_agent.run_monitor
# scalyr_agent.builtin_monitors.nginx_monitor
from __future__ import unicode_literals
from __future__ import absolute_import

import socket

import six
import six.moves.http_client
import six.moves.urllib.request
import six.moves.urllib.error
import six.moves.urllib.parse

from scalyr_agent.scalyr_monitor import (
    ScalyrMonitor,
    define_metric,
    define_log_field,
    define_config_option,
)

httpSourceAddress = "127.0.0.1"

__monitor__ = __name__

define_config_option(
    __monitor__,
    "module",
    "Always ``scalyr_agent.builtin_monitors.nginx_monitor``",
    convert_to=six.text_type,
    required_option=True,
)
define_config_option(
    __monitor__,
    "status_url",
    "Optional (defaults to 'http://localhost/nginx_status').  The URL the monitor will fetch"
    "to retrieve the nginx status information.",
    default="http://localhost/nginx_status",
)
define_config_option(
    __monitor__,
    "source_address",
    "Optional (defaults to '%s'). The IP address to be used as the source address when fetching "
    "the status URL.  Many servers require this to be 127.0.0.1 because they only server the status "
    "page to requests from localhost." % httpSourceAddress,
    default=httpSourceAddress,
)
define_config_option(
    __monitor__,
    "id",
    "Optional (defaults to empty string).  Included in each log message generated by this monitor, "
    "as a field named ``instance``. Allows you to distinguish between different nginx instances "
    "running on the same server.",
    convert_to=six.text_type,
)

define_log_field(__monitor__, "monitor", "Always ``nginx_monitor``.")
define_log_field(
    __monitor__,
    "metric",
    "The metric name.  See the metric tables for more information.",
)
define_log_field(__monitor__, "value", "The value of the metric.")
define_log_field(
    __monitor__, "instance", "The ``id`` value from the monitor configuration."
)

define_metric(
    __monitor__,
    "nginx.connections.active",
    "This is the number of connections currently opened to the "
    "server.  The total number of allowed connections is a function "
    "of the number of worker_processes and the number of "
    "worker_connections configured within your Nginx configuration "
    "file.",
)
define_metric(
    __monitor__,
    "nginx.connections.reading",
    "The number of connections currently reading from the clients.",
)
define_metric(
    __monitor__,
    "nginx.connections.writing",
    "The number of connections currently writing to the clients.",
)
define_metric(
    __monitor__,
    "nginx.connections.waiting",
    "The number of connections currently idle/sending keep alives.",
)


# Taken from:
#   http://stackoverflow.com/questions/1150332/source-interface-with-python-and-urllib2
#
# For connecting to local machine, specifying the source IP may be required.  So, using
# this mechanism should allow that.  Since getting status requires "opening up" a
# non-standard/user-facing web page, it is best to be cautious.
#
# Note - the use of a global is ugly, but this form is more compatible than with another
# method mentioned which would not require the global.  (The cleaner version was added
# in Python 2.7.)
class BindableHTTPConnection(six.moves.http_client.HTTPConnection):
    def connect(self):
        """Connect to the host and port specified in __init__."""
        self.sock = socket.socket()
        self.sock.bind((self.source_ip, 0))
        if isinstance(self.timeout, float):
            self.sock.settimeout(self.timeout)
        self.sock.connect((self.host, self.port))


def BindableHTTPConnectionFactory(source_ip):
    def _get(host, port=None, strict=None, timeout=0):
        # pylint: disable=unexpected-keyword-arg
        bhc = BindableHTTPConnection(host, port=port, strict=strict, timeout=timeout)
        bhc.source_ip = source_ip
        return bhc

    return _get


class BindableHTTPHandler(six.moves.urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(BindableHTTPConnectionFactory(httpSourceAddress), req)


class NginxMonitor(ScalyrMonitor):
    """
# Nginx Monitor

The Nginx monitor allows you to collect data about the usage and performance of your Nginx server.

Each monitor can be configured to monitor a specific Nginx instance, thus allowing you to configure alerts and the
dashboard entries independently (if desired) for each instance.

## Configuring Nginx

To use Scalyr's Nginx monitor, you will first need to configure your Nginx server to enable the status module,
which servers a status page containing information the monitor will extract.

To enable the status module, you must update the server configuration section of your Nginx server.  Details on the
status module can be found [here](http://nginx.org/en/docs/http/ngx_http_stub_status_module.html).  You should also
review the [reference documentation to restrict access](http://nginx.com/resources/admin-guide/restricting-access/)
to a particular URL since it is important for the status module's URL not to be public.

The configuration you will want to add to your Nginx config is:

    location /nginx_status {
      stub_status on;      # enable the status module
      allow 127.0.0.1;     # allow connections from localhost only
      deny all;            # deny every other connection
    }

This block does a couple of very important things.  First, it specifies that the status page will be exposed on the
local server at ``http://<address>/nginx_status``.  ``stub_status on`` is what actually enables the module.  The next
two  statements work together and are probably the most important for security purposes.  ``allow 127.0.0.1`` says
that server status URL can only be accessed by the localhost.  The second entry ``deny all`` tells the server to
disallow  connections from every other machine but the one specified in the allow clause.

If you decide that there is a need to allow access to the server status beyond just the local machine, it is
recommended that you consult the Nginx documentation.

One thing to consider in the above stanzas, each access to the ``/nginx_status`` URL will be logged in the Nginx access
log.  If you wish to change this, add the line ``access_log off;`` to the above configuration.

The specific location to place this block depends upon the server operating system.  To configure it for the default
site on Ubuntu (and Debian variants), look for the file ``/etc/nginx/sites-enabled/default``.

Once you make the configuration change, you will need to restart Nginx.


## Configuring the Nginx Monitor

The Nginx monitor is included with the Scalyr agent.  In order to configure it, you will need to add its monitor
configuration to the Scalyr agent config file.

A basic Nginx monitor configuration entry might resemble:

    monitors: [
      {
          module: "scalyr_agent.builtin_monitors.nginx_monitor",
      }
    ]

If you were running an instances of Nginx on a non-standard port (say 8080), your config might resemble:

    monitors: [
      {
          module: "scalyr_agent.builtin_monitors.nginx_monitor",
          status_url: "http://localhost:8080/nginx_status"
          id: "customers"
      }
    ]

Note the ``id`` field in the configurations.  This is an optional field that allows you to specify an identifier
specific to a particular instance of Nginx and will make it easier to filter on metrics specific to that
instance."""

    def _initialize(self):
        global httpSourceAddress
        self.__url = self._config.get("status_url")
        self.__sourceaddress = self._config.get("source_address")
        httpSourceAddress = self.__sourceaddress

    def _parse_data(self, data):
        result = {}
        lines = data.splitlines()
        i = 0
        # skip any blank lines
        while len(lines[i]) == 0:
            i = i + 1
        while i < len(lines):
            if lines[i].startswith("Active connections:"):
                result["active_connections"] = int(
                    lines[i][len("Active connections: ") :]
                )
            elif lines[i].startswith("server accepts handled requests"):
                i = i + 1
                values = lines[i].split()
                result["server_accepts"] = values[0]
                result["server_handled"] = values[1]
                result["server_requests"] = values[2]
            elif lines[i].startswith("Reading:"):
                values = lines[i].split()
                result["reading"] = values[1]
                result["writing"] = values[3]
                result["waiting"] = values[5]
            i = i + 1
        return result

    def _get_status(self):
        data = None
        # verify that the URL is valid
        try:
            url = six.moves.urllib.parse.urlparse(self.__url)
        except Exception as e:
            self._logger.error(
                "The URL configured for requesting the status page appears to be invalid.  Please verify that the URL is correct in your monitor configuration.  The specified url: %s"
                % self.__url
            )
            return data
        # attempt to request server status
        try:
            opener = six.moves.urllib.request.build_opener(BindableHTTPHandler)
            handle = opener.open(self.__url)
            data = handle.read()
            if data is not None:
                data = self._parse_data(data)
        except six.moves.urllib.error.HTTPError as err:
            message = (
                "An HTTP error occurred attempting to retrieve the status.  Please consult your server logs to determine the cause.  HTTP error code: ",
                err.code,
            )
            if err.code == 404:
                message = "The URL used to request the status page appears to be incorrect.  Please verify the correct URL and update your nginx_monitor configuration."
            elif err.code == 403:
                message = "The server is denying access to the URL specified for requesting the status page.  Please verify that permissions to access the status page are correctly configured in your server configuration and that your nginx_monitor configuration reflects the same configuration requirements."
            elif err.code >= 500 or err.code < 600:
                message = (
                    "The server failed to fulfill the request to get the status page.  Please consult your server logs to determine the cause.  HTTP error code: ",
                    err.code,
                )
            self._logger.error(message)
            data = None
        except six.moves.urllib.error.URLError as err:
            message = (
                "The was an error attempting to reach the server.  Make sure the server is running and properly configured.  The error reported is: ",
                err,
            )
            if err.reason.errno == 111:
                message = (
                    "The HTTP server does not appear to running or cannot be reached.  Please check that it is running and is reachable at the address: %s"
                    % url.netloc
                )
            self._logger.error(message)
            data = None
        except Exception as e:
            self._logger.error(
                "An error occurred attempting to request the server status: %s" % e
            )
            data = None
        return data

    """
    # Currently disabled as it requires platform specific functionality.  This will need
    # be reactivated once a cross platform solution is implemented.
    def _get_procinfo(self):
        try:
            data = subprocess.Popen("ps aux | grep \"nginx: worker\" | grep -v grep | awk '{print $2, $3, $4}'", shell=True, stdout=subprocess.PIPE).stdout.read()
            result = {}
            lines = data.splitlines()
            i = 0
            while i < len(lines):
                if len(lines[i]) != 0:
                    values = lines[i].split()
                    if len(values) == 3:
                        result[values[0]] = {
                            "cpu": values[1],
                            "mem": values[2]
                        }
                i = i + 1
        except Exception, e:
            self._logger.error("Unable to check process status: %s" % e)
            result = None
        return result
    """

    def gather_sample(self):
        data = self._get_status()
        if data is None:
            self._logger.error("No data returned.")
        else:
            samplesToEmit = {
                "active_connections": "nginx.connections.active",
                "reading": "nginx.connections.reading",
                "writing": "nginx.connections.writing",
                "waiting": "nginx.connections.waiting",
            }

            for key in samplesToEmit:
                if key in data:
                    self._logger.emit_value(samplesToEmit[key], int(data[key]))
