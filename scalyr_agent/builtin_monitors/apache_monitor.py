# Copyright 2014, Scalyr, Inc.
#
# Note, this can be run in standalone mode by:
# python -m scalyr_agent.run_monitor
# scalyr_agent.builtin_monitors.apache_monitor
from __future__ import absolute_import
from __future__ import unicode_literals

import six
import six.moves.http_client
import six.moves.urllib.request
import six.moves.urllib.error
import six.moves.urllib.parse
import socket

from scalyr_agent import (
    ScalyrMonitor,
    define_config_option,
    define_log_field,
    define_metric,
)

httpSourceAddress = "127.0.0.1"

__monitor__ = __name__

define_config_option(
    __monitor__,
    "module",
    "Always `scalyr_agent.builtin_monitors.apache_monitor`",
    convert_to=six.text_type,
    required_option=True,
)
define_config_option(
    __monitor__,
    "id",
    "Optional (defaults to empty string). An id, included with each event. Shows in the UI as a value "
    "for the `instance` field. If you are running multiple instances of this plugin, "
    "id lets you distinguish between them. This is especially "
    "useful if you are running multiple Apache instances on a single server; you can monitor each "
    "instance with separate `{...}` stanzas in the configuration "
    "file (`/etc/scalyr-agent-2/agent.json`).",
    convert_to=six.text_type,
)
define_config_option(
    __monitor__,
    "status_url",
    "Optional (defaults to `http://localhost/server-status/?auto`). The URL, in particular the port "
    "number, at which the Apache status module is served. The URL should end in `/?auto` to "
    "indicate that the machine-readable version of the page should be returned.",
    default="http://localhost/server-status/?auto",
)
define_config_option(
    __monitor__,
    "source_address",
    "Optional (defaults to `%s`). The source IP address to use when fetching "
    "the status page. Many servers require this to be `127.0.0.1`, because they "
    "only serve the status page to requests from localhost." % httpSourceAddress,
    default=httpSourceAddress,
)

define_log_field(__monitor__, "monitor", "Always `apache_monitor`.")
define_log_field(
    __monitor__,
    "metric",
    "The metric name.  See the metric tables for more information.",
)
define_log_field(__monitor__, "value", "The value of the metric.")
define_log_field(
    __monitor__,
    "instance",
    "The `id` value, if specified. See [Configuration Options](#options).",
)

define_metric(
    __monitor__,
    "apache.connections.active",
    "The number of asynchronous connections (not using "
    " workers) currently open on the server.",
)
define_metric(
    __monitor__,
    "apache.connections.writing",
    "The number of asynchronous connections (not using "
    "workers) that are currently writing response data.",
)
define_metric(
    __monitor__,
    "apache.connections.idle",
    "The number of asynchronous connections (not using "
    "workers) that are currently idle / sending keepalives.",
)
define_metric(
    __monitor__,
    "apache.connections.closing",
    "The number of asynchronous connections (not using "
    "workers) that are currently closing.",
)
define_metric(
    __monitor__,
    "apache.workers.active",
    "The number of currently active workers. Each worker is a process "
    "handling an incoming request.",
)
define_metric(
    __monitor__,
    "apache.workers.idle",
    "The number of currently idle workers. Each worker is a "
    "process that can handle an incoming request.",
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


class ApacheMonitor(ScalyrMonitor):
    # fmt: off
    """
# Apache

Import performance and usage data from an Apache server.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).


## Installation

1\\. Install the Scalyr Agent

If you haven't already done so, install the [Scalyr Agent](https://app.scalyr.com/help/welcome) on servers running Apache.


2\\. Check requirements

The `status_module` [module](https://httpd.apache.org/docs/current/mod/mod_status.html) must be enabled on the Apache server. On most Linux installations you can run:

    ls /etc/apache2/mods-enabled

If you see `status.conf` and `status.load`, the module is enabled. If not, you can enable the module on most Linux installations by running:

    sudo /usr/sbin/a2enmod status

On some platforms, different commands will enable the `status_module` (filename `mod_status.so`). Consult the documentation for your particular platform. You can also consult:
- [CentOS](https://www.linuxcnf.com/2018/11/how-to-configure-apache-modstatus.html)
- [RHEL, see "Working with modules" section](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/8/html/deploying_different_types_of_servers/setting-apache-http-server_deploying-different-types-of-servers)
- [Ubuntu](https://ubuntu.com/server/docs/web-servers-apache)
- [Windows](http://httpd.apache.org/docs/2.0/platform/windows.html#cust)


3\\. Configure access to the `server-status` page.

You must allow localhost access to to the `server-status` page, usually in the `VirtualHost` configuration section of your
Apache server. On Linux, this is typically found in the `/etc/apache2/sites-available` directory, in the file for your site.

Add to the `VirtualHost` section (between `<VirtualHost>` and `</VirtualHost>`):

    <Location /server-status>
       SetHandler server-status
       Order deny,allow
       Deny from all
       Allow from 127.0.0.1
    </Location>

This sets the status page, served at `http://<address>/server-status`. Access is denied for all except localhost.


4\\. Restart and confirm

When you make the configuration change, restart Apache.  On most Linux systems, run:

    sudo service apache2 restart

To confirm the status module, run this command, substituting the port number as applicable:

    curl http://localhost:80/server-status


5\\. Configure the Scalyr Agent to import status module data

Open the Scalyr Agent configuration file, found at `/etc/scalyr-agent-2/agent.json`.

Find the `monitors: [ ... ]` section and add a `{...}` stanza for the Apache `module` property. Set the `status_url` property, replacing `80` with the applicable port number if you are on a nonstandard port:

    monitors: [
      {
          module: "scalyr_agent.builtin_monitors.apache_monitor",
          status_url: "http://localhost:80/server-status/?auto"
      }
    ]

See [Configuration Options](#options) below for more properties you can add.


6\\. Configure the Scalyr Agent to import Apache access logs

If haven't already done so when installing the Scalyr Agent, find the location of the access log. On most Linux systems this is saved at `/var/log/apache2/access.log`.

Add to the `logs: [ ... ]` section of the Scalyr Agent configuration file, found at `/etc/scalyr-agent-2/agent.json`:


<pre><code>logs: [
   ...

   <strong>{
     path: "/var/log/apache2/access.log",
     attributes: {parser: "accessLog", serverType: "apache"}
   }</strong>
]</code></pre>


Edit the `path` field as applicable for your system setup.


7\\. Save and confirm

Save the `agent.json` file. The Agent will detect changes within 30 seconds. Wait a few minutes for the Scalyr Agent to begin sending Apache data.

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.

Log into Scalyr and click Dashboards > Apache. You will see an overview of Apache data, across all servers, configured for this plugin.

The [Event Reference](#events) below explains the fields created by this plugin.

For help, contact us at [support@scalyr.com](mailto:support@scalyr.com).


## Further Reading

See [Analyze Access Logs](https://app.scalyr.com/solutions/analyze-access-logs) for more information about working with web access logs.
    """
    # fmt: on

    def _initialize(self):
        global httpSourceAddress
        self.__url = self._config.get(
            "status_url", default="http://localhost/server-status/?auto"
        )
        self.__sourceaddress = self._config.get(
            "source_addresss", default=httpSourceAddress
        )
        httpSourceAddress = self.__sourceaddress

    def _parse_data(self, data):
        fields = {
            b"Total Accesses:": "total_accesses",
            b"Total kBytes:": "total_kbytes_sent",
            b"Uptime:": "uptime",
            b"ReqPerSec:": "request_per_sec",
            b"BytesPerSec:": "bytes_per_sec",
            b"BytesPerReq:": "bytes_per_req",
            b"BusyWorkers:": "busy_workers",
            b"IdleWorkers:": "idle_workers",
            b"ConnsTotal:": "connections_total",
            b"ConnsAsyncWriting:": "async_connections_writing",
            b"ConnsAsyncKeepAlive:": "async_connections_keep_alive",
            b"ConnsAsyncClosing:": "async_connections_closing",
        }
        result = {}
        lines = data.splitlines()
        i = 0
        # skip any blank lines
        while len(lines[i]) == 0:
            i = i + 1
        while i < len(lines):
            for key in fields:
                if lines[i].startswith(key):
                    values = lines[i].split()
                    result[fields[key]] = values[1]
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
                message = "The URL used to request the status page appears to be incorrect.  Please verify the correct URL and update your apache_monitor configuration."
            elif err.code == 403:
                message = "The server is denying access to the URL specified for requesting the status page.  Please verify that permissions to access the status page are correctly configured in your server configuration and that your apache_monitor configuration reflects the same configuration requirements."
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
                % (six.text_type(err))
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
            data = subprocess.Popen("ps aux | grep apache | grep -v grep | grep -v scalyr | awk '{print $2, $3, $4}'", shell=True, stdout=subprocess.PIPE).stdout.read()
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
                ("busy_workers", "apache.workers.active"),
                ("idle_workers", "apache.workers.idle"),
                ("connections_total", "apache.connections.active"),
                ("async_connections_writing", "apache.connections.writing"),
                ("async_connections_keep_alive", "apache.connections.idle"),
                ("async_connections_closing", "apache.connections.closing"),
            ]

            statsEmitted = 0
            for key, metric_name in samplesToEmit:
                if key in data:
                    self._logger.emit_value(metric_name, int(data[key]))
                    statsEmitted += 1

            if statsEmitted == 0:
                self._logger.error(
                    "Status page did not match expected format.  Check to make sure you included "
                    'the "?auto" option in the status url'
                )
