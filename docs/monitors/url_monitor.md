/// DECLARE path=/help/monitors/url
/// DECLARE title=URL Monitor
/// DECLARE section=help
/// DECLARE subsection=monitors

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


<a name="options"></a>
## Configuration Options

| Option                   | Usage |
|---|---|
| `module`               | Always `scalyr_agent.builtin_monitors.url_monitor`. |
| `id`                   | An id, included with each event. Shows in the UI as a value for the `instance` field. This is especially useful if you are running multiple instances of this plugin to send requests to multiple URLs. Each instance has a separate `{...}` stanza in the configuration file (`/etc/scalyr-agent-2/agent.json`).|
| `url`                  | URL for the request. Must be HTTP or HTTPS. |
| `request_method`       | Optional (defaults to `GET`). The HTTP request method. |
| `request_headers`      | Optional. HTTP headers for the request. A list of dictionaries, each with `header`, and  `value` key-value pairs. For example, `request_headers: [{"header": "Accept-Encoding", "value": "gzip"}]`. |
| `request_data`         | Optional. A string of data to pass when `request_method` is POST. |
| `timeout`              | Optional. (defaults to `10`). Seconds to wait for the URL to load.|
| `extract`              | Optional. A regular expression, applied to the request response, that lets you discard unnecessary data. Must contain a matching group (i.e. a subexpression enclosed in parentheses). Only the content of the matching group is imported. |
| `log_all_lines`        | Optional (defaults to `false`). If `true`, all from the request response are imported. If 'false`, only the first line is imported. |
| `max_characters`       | Optional (defaults to `200`). Maximum characters to import from the request. You may set a value up to `10000`, however we currently truncate all fields to `3500` characters. |

&nbsp;

<a name="events"></a>
## Event Reference

In the UI, each event has the fields:

| Field                    | Meaning |
|---|---|
| `monitor`              | Always `url_monitor` |
| `metric`               | Always `response` |
| `instance`             | The `id` value from the monitor configuration, for example `instance-type` |
| `url`                  | The request URL, for example `http://169.254.169.254/latest/meta-data/instance-type` |
| `status`               | The HTTP response code, for example 200 or 404 |
| `length`               | The length of the HTTP response |
| `value`                | The body of the HTTP response |

&nbsp;
