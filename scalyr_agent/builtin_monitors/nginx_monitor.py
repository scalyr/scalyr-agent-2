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
    "Always `scalyr_agent.builtin_monitors.nginx_monitor`",
    convert_to=six.text_type,
    required_option=True,
)
define_config_option(
    __monitor__,
    "status_url",
    "Optional (defaults to `http://localhost/nginx_status`). The URL the plugin will fetch "
    "nginx status information from.",
    default="http://localhost/nginx_status",
)
define_config_option(
    __monitor__,
    "source_address",
    "Optional (defaults to `%s`). The source IP address to use when fetching "
    "the status page. Many servers require this to be `127.0.0.1`, because they "
    "only serve the status page to requests from localhost." % httpSourceAddress,
    default=httpSourceAddress,
)
define_config_option(
    __monitor__,
    "id",
    "Optional (defaults to empty string). An id, included with each event. Shows in the UI as a value "
    "for the `instance` field. If you are running multiple instances of this plugin, "
    "id lets you distinguish between them. This is especially "
    "useful if you are running multiple nginx instances on a single server; you can monitor each "
    "instance with separate `{...}` stanzas in the configuration "
    "file (`/etc/scalyr-agent-2/agent.json`).",
    convert_to=six.text_type,
)

define_log_field(__monitor__, "monitor", "Always `nginx_monitor`.")
define_log_field(
    __monitor__,
    "metric",
    "The metric name.  See the metric tables for more information.",
)
define_log_field(
    __monitor__,
    "value",
    "The value of the metric.",
)
define_log_field(
    __monitor__,
    "instance",
    "The `id` value, if specified. See [Configuration Options](#options).",
)

define_metric(
    __monitor__,
    "nginx.connections.active",
    "The number of connections currently open on the server. "
    "The total number of allowed connections is a function "
    "of the number of worker_processes and the number of "
    "worker_connections in your Nginx configuration file.",
)
define_metric(
    __monitor__,
    "nginx.connections.reading",
    "The number of connections currently reading request data.",
)
define_metric(
    __monitor__,
    "nginx.connections.writing",
    "The number of connections currently writing response data.",
)
define_metric(
    __monitor__,
    "nginx.connections.waiting",
    "The number of connections currently idle / sending keepalives.",
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
        # NOTE: "strict" argument is not supported by Python 3 class
        # TODO: We should switch to using urllib Request object directly or requests library
        if six.PY2:
            kwargs = {"strict": strict}
        else:
            kwargs = {}
        bhc = BindableHTTPConnection(host, port=port, timeout=timeout, **kwargs)
        bhc.source_ip = source_ip
        return bhc

    return _get


class BindableHTTPHandler(six.moves.urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(BindableHTTPConnectionFactory(httpSourceAddress), req)


class NginxMonitor(ScalyrMonitor):
    # fmt: off
    """
# Nginx

Import performance and usage data from an nginx server.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).


## Installation

1\\. Install the Scalyr Agent

If you haven't done so already, install the [Scalyr Agent](https://app.scalyr.com/help/welcome) on servers running nginx.


2\\. Check requirements

Make sure your nginx server supports the status module. Run this command:

    nginx -V 2>&1 | grep -o with-http_stub_status_module

The output must be:

    with-http_stub_status_module

If not, you will need to either recompile nginx and add the `--with-http_stub_status_module` flag to `./configure`, or upgrade to a full version of nginx compiled with this flag.

To recompile, see the section on "Building Nginx From Source" in the [install tutorial](https://www.nginx.com/resources/wiki/start/topics/tutorials/install/). You can also consult the status module [documentation](https://nginx.org/en/docs/http/ngx_http_stub_status_module.html).


3\\. Enable the nginx status module

Find the `nginx.conf` file, or the file corresponding to your site in the `sites-available` directory. For most Linux systems, these are located at `/etc/nginx/nginx.conf` and `/etc/nginx/sites-available`.

Add to the `server { ... }` section:

    location /nginx_status {
      stub_status on;      # enable the status module
      allow 127.0.0.1;     # allow connections from localhost only
      deny all;            # deny every other connection
    }

This sets the status page, served at `http://<address>/nginx_status`. Access is denied for all except localhost.

Each time the Scalyr Agent fetches `/nginx_status`, an entry will be added to the nginx access log. To stop this, add the line `access_log off;` to the above configuration.


4\\. Restart nginx and confirm

To restart on most Linux systems:

    sudo service nginx restart

To confirm the status module is working, run this command on the server, substituting the applicable port number:

    curl http://localhost:80/nginx_status


5\\. Configure the Scalyr Agent to import status module data

Open the Scalyr Agent configuration file, located at `/etc/scalyr-agent-2/agent.json`.

Find the `monitors: [ ... ]` section and add a `{...}` stanza with the `module` property set for nginx. Set the `status_url` property, replacing `80` with the applicable port number if you are on a nonstandard port:

    monitors: [
      {
          module: "scalyr_agent.builtin_monitors.nginx_monitor",
          status_url: "http://localhost:80/nginx_status"
      }
    ]

See "Configuration Options" below for more properties you can add.


6\\. Configure the Scalyr Agent to import the nginx access log

If haven't already done so when installing the Scalyr Agent, add the following entry to the `logs: [ ... ]` section of the Scalyr Agent configuration file, found at `/etc/scalyr-agent-2/agent.json`:

<pre><code>logs: [
   ...

   <strong>{
     path: "/var/log/nginx/access.log",
     attributes: {parser: "accessLog", serverType: "nginx"}
   }</strong>
]</pre></code>

For most Linux systems the `access.log` file is saved in `/var/log/nginx/access.log`. Adjust the `path` property if applicable.


7\\. Save and confirm

Save the `agent.json` file. The Agent will detect changes within 30 seconds. Wait a few minutes for the Scalyr Agent to begin sending nginx data.

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.

Log into Scalyr and click Dashboards > nginx. You will see an overview of nginx data, across all servers configured for this plugin.

The [Event Reference](#events) below explains the fields created by this plugin.

For help, contact us at [support@scalyr.com](mailto:support@scalyr.com).


## Further Reading

Our [In-Depth Guide to Nginx Metrics](https://github.com/scalyr/scalyr-community/blob/master/guides/an-in-depth-guide-to-nginx-metrics.md) has more information on the metrics collected by this plugin.

Our [Essential Guide to Monitoring Nginx](https://github.com/scalyr/scalyr-community/blob/master/guides/how-to-monitor-nginx-the-essential-guide.md) explains how to use these metrics to monitor nginx.

See [Analyze Access Logs](https://app.scalyr.com/solutions/analyze-access-logs) for more information about working with web access logs.

    """
    # fmt: on

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
            if lines[i].startswith(b"Active connections:"):
                result["active_connections"] = int(
                    lines[i][len(b"Active connections: ") :]
                )
            elif lines[i].startswith(b"server accepts handled requests"):
                i = i + 1
                values = lines[i].split()
                result["server_accepts"] = values[0]
                result["server_handled"] = values[1]
                result["server_requests"] = values[2]
            elif lines[i].startswith(b"Reading:"):
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
        except Exception:
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
                "The was an error attempting to reach the server.  Make sure the server is running and properly configured.  The error reported is: %s"
                % (str(err))
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
            samplesToEmit = [
                ("active_connections", "nginx.connections.active"),
                ("reading", "nginx.connections.reading"),
                ("writing", "nginx.connections.writing"),
                ("waiting", "nginx.connections.waiting"),
            ]

            for key, metric_name in samplesToEmit:
                if key in data:
                    self._logger.emit_value(metric_name, int(data[key]))
