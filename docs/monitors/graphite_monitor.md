/// DECLARE path=/help/monitors/graphite
/// DECLARE title=Graphite Monitor
/// DECLARE section=help
/// DECLARE subsection=monitors

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

# Graphite

Import metrics from Graphite-compatible tools.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).

This plugin enables the Agent to act as a carbon server. It can receive metrics in the pickle or plaintext protocols. You can import metrics from any [Graphite-compatible tool](https://graphite.readthedocs.io/en/latest/tools.html).


## Installation

1\. Install the Scalyr Agent

If you haven't already done so, install the [Scalyr Agent](https://app.scalyr.com/help/welcome). We recommend you install the Agent on each server you want to monitor. Your Graphite data will automatically be tagged for the server it came from, and the Agent can also collect system metrics, and log files.


2\. Configure the Scalyr Agent to receive Graphite metrics

Open the Scalyr Agent configuration file at `/etc/scalyr-agent-2/agent.json`.

Find the `monitors: [ ... ]` section and add a `{...}` stanza with the `module` property set for graphite.

monitors: [
  {
    module: "scalyr_agent.builtin_monitors.graphite_monitor"
  }
]

By default, the plugin will listen on port 2003 for the `plaintext` protocol, and 2004 for `pickle` protocol. These are the standard Graphite TCP ports. For security, the plugin will only accept connections from localhost (i.e. from processes running on the same server). To allow connections from other servers, add the `only_accept_local` property to the above `{...}` stanza, and set it to `false`.

See [Configuration Options](#options) below to set custom ports, or to disallow a protocol.


3\. Save and confirm

Save the `agent.json` file. The Agent will detect changes within 30 seconds.

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.


4\. Configure your Graphite-compatible tools to send metrics

These steps will differ, depending on your preferred architecture. You can configure [Graphite-compatible tools](https://graphite.readthedocs.io/en/latest/tools.html) to send metrics directly to the Scalyr Agent. In this scenario you can stop the carbon daemon(s).

If you wish to retain your carbon architecture, you can relay metrics to Scalyr. Edit `DESTINATIONS`in [carbon.conf](https://github.com/graphite-project/carbon/blob/master/conf/carbon.conf.example), and `destinations` in [relay-rules.conf](https://github.com/graphite-project/carbon/blob/master/conf/relay-rules.conf.example). See the Graphite [documentation](https://graphite.readthedocs.io/en/latest/config-carbon.html) for more information.

If you are using `carbon-c-relay`, you can set up a [forward cluster](https://github.com/grobian/carbon-c-relay/blob/master/carbon-c-relay.md#configuration-syntax). If you are using `carbon-relay-ng`, see the "Routes" section of the [documentation](https://github.com/grafana/carbon-relay-ng/blob/master/docs/config.md).


5\. Confirm

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

<a name="options"></a>
## Configuration Options

| Property                   | Description | 
| ---                        | --- | 
| `module`                   | Always `scalyr_agent.builtin_monitors.graphite_monitor` | 
| `only_accept_local`        | Optional (defaults to `true`). If true, then the plugin only accepts connections from localhost. If false, all network connections are accepted. | 
| `accept_plaintext`         | Optional (defaults to `true`). If true, then the plugin accepts connections in Graphite's "plain text" procotol. | 
| `accept_pickle`            | Optional (defaults to `true`). If true, then the plugin accepts connections in Graphite's "pickle" procotol. | 
| `plaintext_port`           | Optional (defaults to `2003`). The port number on which the plugin listens for plain text connections. Unused if `accept_plaintext` is false. | 
| `pickle_port`              | Optional (defaults to `2004`). The port number on which the plugin listens for pickle connections. Not applicable if `accept_pickle` is false. | 
| `max_connection_idle_time` | Optional (defaults to `300`). The maximum number of seconds allowed between requests before the Graphite server will close the connection. | 
| `max_request_size`         | Optional (defaults to `100K`). The maximum size in bytes of a single request. | 
| `buffer_size`              | Optional (defaults to `100KB`). The maximum size in bytes to buffer incoming requests per connection | 

<a name="events"></a>
## Event Reference

In the UI, each event has the fields:

| Field       | Description | 
| ---         | --- | 
| `monitor`   | Always `graphite_monitor`. | 
| `metric`    | The Graphite metric name. | 
| `value`     | The Graphite metric value. | 
| `orig_time` | The Graphite timestamp. | 
