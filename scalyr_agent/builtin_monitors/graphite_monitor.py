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
# A ScalyrMonitor plugin that acts as a Graphite server, accepting metrics using either the
# text or pickle protocol and sends them to Scalyr.
#
# Note, this can be run in standalone mode by:
#     python -m scalyr_agent.run_monitor scalyr_agent.builtin_monitors.graphite_monitor
#
# author:  Steven Czerwinski <czerwin@scalyr.com>

from __future__ import unicode_literals
from __future__ import absolute_import

__author__ = "czerwin@scalyr.com"

import six

try:
    # noinspection PyPep8Naming
    import six.moves.cPickle as pickle
except ImportError:
    import pickle  # type: ignore

from scalyr_agent import StoppableThread
from scalyr_agent import ScalyrMonitor, define_config_option, define_log_field
from scalyr_agent.monitor_utils import (
    ServerProcessor,
    LineRequestParser,
    Int32RequestParser,
)

__monitor__ = __name__

# Configuration parameters are:
# only_accept_local: (defaults to True)
# accept_plaintext: (defaults to True)
# accept_pickle: (defaults to True)
# plaintext_port: (defaults to 2003)
# pickle_port: (defaults to 2004)
# max_connection_idle_time: (defaults to 300)
# max_request_size: (defaults to 100K)
# buffer_size: (defaults to 100K)
define_config_option(
    __monitor__,
    "module",
    "Always `scalyr_agent.builtin_monitors.graphite_monitor`",
    convert_to=six.text_type,
    required_option=True,
)
define_config_option(
    __monitor__,
    "only_accept_local",
    "Optional (defaults to `true`). If true, then the plugin only accepts connections from localhost. "
    "If false, all network connections are accepted.",
    default=True,
    convert_to=bool,
)
define_config_option(
    __monitor__,
    "accept_plaintext",
    "Optional (defaults to `true`). If true, then the plugin accepts connections in Graphite's \"plain "
    'text" procotol.',
    default=True,
    convert_to=bool,
)
define_config_option(
    __monitor__,
    "accept_pickle",
    "Optional (defaults to `true`). If true, then the plugin accepts connections in Graphite's "
    '"pickle" procotol.',
    default=True,
    convert_to=bool,
)
define_config_option(
    __monitor__,
    "plaintext_port",
    "Optional (defaults to `2003`). The port number on which the plugin listens for plain text "
    "connections. Unused if `accept_plaintext` is false.",
    default=2003,
    min_value=1,
    max_value=65535,
    convert_to=int,
)
define_config_option(
    __monitor__,
    "pickle_port",
    "Optional (defaults to `2004`). The port number on which the plugin listens for pickle connections. "
    "Not applicable if `accept_pickle` is false.",
    default=2004,
    min_value=1,
    max_value=65535,
    convert_to=int,
)
define_config_option(
    __monitor__,
    "max_connection_idle_time",
    "Optional (defaults to `300`). The maximum number of seconds allowed between requests before the "
    "Graphite server will close the connection.",
    default=300.0,
    min_value=1,
    convert_to=float,
)
define_config_option(
    __monitor__,
    "max_request_size",
    "Optional (defaults to `100K`). The maximum size in bytes of a single request.",
    default=100 * 1024,
    min_value=1000,
    convert_to=int,
)
define_config_option(
    __monitor__,
    "buffer_size",
    "Optional (defaults to `100KB`). The maximum size in bytes to buffer incoming requests "
    "per connection",
    default=100 * 1024,
    min_value=10 * 1024,
    convert_to=int,
)

define_log_field(__monitor__, "monitor", "Always `graphite_monitor`.")
define_log_field(__monitor__, "metric", "The Graphite metric name.")
define_log_field(__monitor__, "value", "The Graphite metric value.")
define_log_field(__monitor__, "orig_time", "The Graphite timestamp.")


class GraphiteMonitor(ScalyrMonitor):
    # fmt: off
    """
# Graphite

Import metrics from Graphite-compatible tools.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).

This plugin enables the Agent to act as a carbon server. It can receive metrics in the pickle or plaintext protocols. You can import metrics from any [Graphite-compatible tool](https://graphite.readthedocs.io/en/latest/tools.html).


## Installation

1\\. Install the Scalyr Agent

If you haven't already done so, install the [Scalyr Agent](https://app.scalyr.com/help/welcome). We recommend you install the Agent on each server you want to monitor. Your Graphite data will automatically be tagged for the server it came from, and the Agent can also collect system metrics, and log files.


2\\. Configure the Scalyr Agent to receive Graphite metrics

Open the Scalyr Agent configuration file at `/etc/scalyr-agent-2/agent.json`.

Find the `monitors: [ ... ]` section and add a `{...}` stanza with the `module` property set for graphite.

monitors: [
  {
    module: "scalyr_agent.builtin_monitors.graphite_monitor"
  }
]

By default, the plugin will listen on port 2003 for the `plaintext` protocol, and 2004 for `pickle` protocol. These are the standard Graphite TCP ports. For security, the plugin will only accept connections from localhost (i.e. from processes running on the same server). To allow connections from other servers, add the `only_accept_local` property to the above `{...}` stanza, and set it to `false`.

See [Configuration Options](#options) below to set custom ports, or to disallow a protocol.


3\\. Save and confirm

Save the `agent.json` file. The Agent will detect changes within 30 seconds.

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.


4\\. Configure your Graphite-compatible tools to send metrics

These steps will differ, depending on your preferred architecture. You can configure [Graphite-compatible tools](https://graphite.readthedocs.io/en/latest/tools.html) to send metrics directly to the Scalyr Agent. In this scenario you can stop the carbon daemon(s).

If you wish to retain your carbon architecture, you can relay metrics to Scalyr. Edit `DESTINATIONS`in [carbon.conf](https://github.com/graphite-project/carbon/blob/master/conf/carbon.conf.example), and `destinations` in [relay-rules.conf](https://github.com/graphite-project/carbon/blob/master/conf/relay-rules.conf.example). See the Graphite [documentation](https://graphite.readthedocs.io/en/latest/config-carbon.html) for more information.

If you are using `carbon-c-relay`, you can set up a [forward cluster](https://github.com/grobian/carbon-c-relay/blob/master/carbon-c-relay.md#configuration-syntax). If you are using `carbon-relay-ng`, see the "Routes" section of the [documentation](https://github.com/grafana/carbon-relay-ng/blob/master/docs/config.md).


5\\. Confirm

Log in to your account and search for [monitor = 'graphite_monitor'](https://app.scalyr.com/events?filter=$monitor%20%3D%20%27graphite_monitor%27). This will show all Graphite data imported by the Scalyr Agent.

For help, contact us at [support@scalyr.com](mailto:support@scalyr.com).


## Data Representation

The Scalyr Agent converts Graphite measurements into our data model. Consider the following Graphite value:

    requests.500.host1 1.03 123456789

This is converted into an **event** with the following fields:

    path      = requests.500.host1
    value     = 1.03
    timestamp = 123456789
    path1     = requests
    path2     = 500
    path3     = host1

The first three fields are a direct representation of the Graphite data. The pathN fields break the
path into components, allowing for flexible queries and aggregation. For instance, the search `path1='requests'
path3='host1'` will match all requests on host1.


## Generating Graphs

A typical workflow for graphing involves using the [Search view](https://www.scalyr.com/events) page to view Graphite data.
In the Search box, specify a query using the fields described above. Some examples:
- `source='graphite' path = 'requests.500.host1'` (a single metric)
- `source='graphite' path1 = 'requests' path2=500` (requests.500.*)
- `source='graphite' path1 = 'requests' path3='host1'` (requests.*.host1)

Examples for TSDB data:

    source='tsdb' metric = 'mysql.bytes_received' host='db1'
    source='tsdb' metric = 'mysql.bytes_received'

Once you have filtered for the data you wish to graph, see the [Graphs](https://app.scalyr.com/help/graphs#display) overview page for instructions on how to access and utilize Graphs view.
    """
    # fmt: on

    def _initialize(self):
        """Performs monitor-specific initialization."""
        self.__only_accept_local = self._config.get("only_accept_local")
        self.__accept_plaintext = self._config.get("accept_plaintext")
        self.__accept_pickle = self._config.get("accept_pickle")
        self.__plaintext_port = self._config.get("plaintext_port")
        self.__pickle_port = self._config.get("pickle_port")
        self.__max_connection_idle_time = self._config.get("max_connection_idle_time")
        self.__max_request_size = self._config.get("max_request_size")
        self.__buffer_size = self._config.get("buffer_size")
        # We may need an extra thread for this monitor if we are accepting traffic on both the text and pickle
        # ports since our server abstractions require a thread per port.
        self.__extra_thread = None

        if not self.__accept_plaintext and not self.__accept_pickle:
            raise Exception(
                "Invalid config state for Graphite Monitor.  At least one of accept_plaintext or "
                "accept_pickle must be true"
            )

        if self.__max_request_size > self.__buffer_size:
            raise Exception(
                "The max_request_size of %d cannot be greater than the buffer size of %d"
                % (self.__max_request_size, self.__buffer_size)
            )

        # We use different defaults for the log metric values so we need to update those variables.
        self._log_write_rate = self._config.get(
            "monitor_log_write_rate", convert_to=int, default=-1
        )
        self._log_max_write_burst = self._config.get(
            "monitor_log_max_write_burst", convert_to=int, default=-1
        )
        self._log_flush_delay = self._config.get(
            "monitor_log_flush_delay", convert_to=float, default=1.0, min_value=0
        )

        self.__text_server = None
        self.__pickle_server = None

    def run(self):
        # We have to (maybe) start up two servers.  Since each server requires its own thread, we may have
        # to create a new one (since we can use this thread to run one of the servers).
        if self.__accept_plaintext:
            text_server = GraphiteTextServer(
                self.__only_accept_local,
                self.__plaintext_port,
                self._run_state,
                self.__buffer_size,
                self.__max_request_size,
                self.__max_connection_idle_time,
                self._logger,
            )
        else:
            text_server = None

        if self.__accept_pickle:
            pickle_server = GraphitePickleServer(
                self.__only_accept_local,
                self.__pickle_port,
                self._run_state,
                self.__buffer_size,
                self.__max_request_size,
                self.__max_connection_idle_time,
                self._logger,
            )
        else:
            pickle_server = None

        # NOTE: We assign those variables so we can access them during the tests to verify
        # corectness
        self.__text_server = text_server
        self.__pickle_server = pickle_server

        if not self.__accept_plaintext:
            pickle_server.run()
        elif not self.__accept_pickle:
            text_server.run()
        else:
            # We need a callback to start the text_server.  We cannot use text_server.run directly since it does
            # not take a run_state argument.
            # noinspection PyUnusedLocal
            def run_text_server(run_state):
                text_server.run()

            # If we are accepting both kinds of traffic, we need a second thread to handle one of the ports.. the
            # other one will be handled by this thread.
            # noinspection PyAttributeOutsideInit
            self.__extra_thread = StoppableThread(
                target=run_text_server, name="Graphite monitor text server thread"
            )
            self.__extra_thread.start()
            pickle_server.run()

    def stop(self, wait_on_join=True, join_timeout=5):
        # The order here is important.  Since our servers use self._run_state to know when to stop, we need to
        # invoke the inherited method first since that is what actually stops self._run_state.  Then we can join
        # on the threads.
        ScalyrMonitor.stop(self, wait_on_join=wait_on_join, join_timeout=join_timeout)
        if self.__extra_thread is not None:
            self.__extra_thread.stop(
                wait_on_join=wait_on_join, join_timeout=join_timeout
            )


class GraphiteTextServer(ServerProcessor):
    """Accepts connections on a server socket and handles them using Graphite's plaintext protocol format, emitting
    the received metrics to the log.
    """

    def __init__(
        self,
        only_accept_local,
        port,
        run_state,
        buffer_size,
        max_request_size,
        max_connection_idle_time,
        logger,
    ):
        """Creates a new instance.

        @param only_accept_local: If true, only accept local connections.
        @param port: The port on which to accept connections.
        @param run_state: The run_state to use to control when this server should stop accepting connections and new
            requests. If 'run_state's 'stop' method is invoked, then 'run' will terminate.
        @param buffer_size: The maximum buffer size for buffering incoming requests per connection.
        @param max_request_size: The maximum size of an individual request. If this is exceeded, then the connection
            responsible is terminated.
        @param max_connection_idle_time: The maximum time to wait on a connection between requests before closing it.
        @param logger: The logger to use to record errors and metrics.
        """
        self.__logger = logger
        self.__parser = LineRequestParser(max_request_size)
        ServerProcessor.__init__(
            self,
            port,
            localhost_socket=only_accept_local,
            max_request_size=max_request_size,
            max_connection_idle_time=max_connection_idle_time,
            buffer_size=buffer_size,
            run_state=run_state,
        )

    def execute_request(self, request):
        try:
            # This is how the carbon graphite server parses the line.  We could be more forgiving but if it works
            # for them, then we can do it as well.
            metric, value, orig_timestamp = request.strip().split()
            # Metric name can be of bytes type, but we need to make sure it's unicode type
            metric = six.ensure_text(metric)
            value = float(value)
            orig_timestamp = float(orig_timestamp)
            # Include the time that the original graphite request said to associate with the metric value.
            self.__logger.emit_value(
                metric, value, extra_fields={"orig_time": orig_timestamp}
            )
        except ValueError:
            self.__logger.warn(
                "Could not parse incoming metric line from graphite plaintext server, ignoring",
                error_code="graphite_monitor/badPlainTextLine",
            )

    def parse_request(self, request_input, num_available_bytes):
        return self.__parser.parse_request(request_input, num_available_bytes)

    def report_connection_problem(self, exception):
        self.__logger.exception(
            "Exception seen while processing Graphite connect on text port, "
            'closing connection: "%s"' % six.text_type(exception)
        )


class GraphitePickleServer(ServerProcessor):
    """Accepts connections on a server socket and handles them using Graphite's pickle protocol format, emitting
    the received metrics to the log.

    NOTE (Tomaz): Pickle can contain arbitrary Python object data so we should note in the docs that
    accepting arbitrary pickle data could be very dangerous and advise users against using it -
    and in case they do need to use it, the should have additonal step in between which sanitized
    pickled data and ensures it's safe.
    """

    def __init__(
        self,
        only_accept_local,
        port,
        run_state,
        buffer_size,
        max_request_size,
        max_connection_idle_time,
        logger,
    ):
        """Creates a new instance.

        @param only_accept_local: If true, only accept local connections.
        @param port: The port on which to accept connections.
        @param run_state: The run_state to use to control when this server should stop accepting connections and new
            requests. If 'run_state's 'stop' method is invoked, then 'run' will terminate.
        @param buffer_size: The maximum buffer size for buffering incoming requests per connection.
        @param max_request_size: The maximum size of an individual request. If this is exceeded, then the connection
            responsible is terminated.
        @param max_connection_idle_time: The maximum time to wait on a connection between requests before closing it.
        @param logger: The logger to use to record errors and metrics.
        """
        self.__logger = logger
        self.__request_parser = Int32RequestParser(max_request_size)
        ServerProcessor.__init__(
            self,
            port,
            localhost_socket=only_accept_local,
            max_request_size=max_request_size,
            max_connection_idle_time=max_connection_idle_time,
            buffer_size=buffer_size,
            run_state=run_state,
        )

    def execute_request(self, request):
        # noinspection PyBroadException
        try:
            # Use pickle to read the binary data.
            data_object = pickle.loads(request)
        except Exception:  # pickle.loads is document as raising any type of exception, so have to catch them all.
            self.__logger.warn(
                "Could not parse incoming metric line from graphite pickle server, ignoring",
                error_code="graphite_monitor/badUnpickle",
            )
            return

        try:
            # The format should be [[ metric [ timestamp, value]] ... ]
            for (metric, datapoint) in data_object:
                value = float(datapoint[1])
                orig_timestamp = float(datapoint[0])
                self.__logger.emit_value(
                    metric, value, extra_fields={"orig_time": orig_timestamp}
                )
        except ValueError:
            self.__logger.warn(
                "Could not parse incoming metric line from graphite pickle server, ignoring",
                error_code="graphite_monitor/badPickleLine",
            )

    def parse_request(self, request_input, num_available_bytes):
        return self.__request_parser.parse_request(request_input, num_available_bytes)

    def report_connection_problem(self, exception):
        self.__logger.exception(
            'Exception seen while processing Graphite connect on pickle port, closing connection: "%s"'
            % six.text_type(exception)
        )
