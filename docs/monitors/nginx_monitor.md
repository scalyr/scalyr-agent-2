/// DECLARE path=/help/monitors/nginx
/// DECLARE title=Nginx Monitor
/// DECLARE section=help
/// DECLARE subsection=monitors

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

# Nginx

Import performance and usage data from an nginx server.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).


## Installation

1\. Install the Scalyr Agent

If you haven't done so already, install the [Scalyr Agent](https://app.scalyr.com/help/welcome) on servers running nginx.


2\. Check requirements

Make sure your nginx server supports the status module. Run this command:

    nginx -V 2>&1 | grep -o with-http_stub_status_module

The output must be:

    with-http_stub_status_module

If not, you will need to either recompile nginx and add the `--with-http_stub_status_module` flag to `./configure`, or upgrade to a full version of nginx compiled with this flag.

To recompile, see the section on "Building Nginx From Source" in the [install tutorial](https://www.nginx.com/resources/wiki/start/topics/tutorials/install/). You can also consult the status module [documentation](https://nginx.org/en/docs/http/ngx_http_stub_status_module.html).


3\. Enable the nginx status module

Find the `nginx.conf` file, or the file corresponding to your site in the `sites-available` directory. For most Linux systems, these are located at `/etc/nginx/nginx.conf` and `/etc/nginx/sites-available`.

Add to the `server { ... }` section:

    location /nginx_status {
      stub_status on;      # enable the status module
      allow 127.0.0.1;     # allow connections from localhost only
      deny all;            # deny every other connection
    }

This sets the status page, served at `http://<address>/nginx_status`. Access is denied for all except localhost.

Each time the Scalyr Agent fetches `/nginx_status`, an entry will be added to the nginx access log. To stop this, add the line `access_log off;` to the above configuration.


4\. Restart nginx and confirm

To restart on most Linux systems:

    sudo service nginx restart

To confirm the status module is working, run this command on the server, substituting the applicable port number:

    curl http://localhost:80/nginx_status


5\. Configure the Scalyr Agent to import status module data

Open the Scalyr Agent configuration file, located at `/etc/scalyr-agent-2/agent.json`.

Find the `monitors: [ ... ]` section and add a `{...}` stanza with the `module` property set for nginx. Set the `status_url` property, replacing `80` with the applicable port number if you are on a nonstandard port:

    monitors: [
      {
          module: "scalyr_agent.builtin_monitors.nginx_monitor",
          status_url: "http://localhost:80/nginx_status"
      }
    ]

See "Configuration Options" below for more properties you can add.


6\. Configure the Scalyr Agent to import the nginx access log

If haven't already done so when installing the Scalyr Agent, add the following entry to the `logs: [ ... ]` section of the Scalyr Agent configuration file, found at `/etc/scalyr-agent-2/agent.json`:

<pre><code>logs: [
   ...

   <strong>{
     path: "/var/log/nginx/access.log",
     attributes: {parser: "accessLog", serverType: "nginx"}
   }</strong>
]</pre></code>

For most Linux systems the `access.log` file is saved in `/var/log/nginx/access.log`. Adjust the `path` property if applicable.


7\. Save and confirm

Save the `agent.json` file. The Agent will detect changes within 30 seconds. Wait a few minutes for the Scalyr Agent to begin sending nginx data.

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.

Log into Scalyr and click Dashboards > nginx. You will see an overview of nginx data, across all servers configured for this plugin.

The [Event Reference](#events) below explains the fields created by this plugin.

For help, contact us at [support@scalyr.com](mailto:support@scalyr.com).


## Further Reading

Our [In-Depth Guide to Nginx Metrics](https://github.com/scalyr/scalyr-community/blob/master/guides/an-in-depth-guide-to-nginx-metrics.md) has more information on the metrics collected by this plugin.

Our [Essential Guide to Monitoring Nginx](https://github.com/scalyr/scalyr-community/blob/master/guides/how-to-monitor-nginx-the-essential-guide.md) explains how to use these metrics to monitor nginx.

See [Analyze Access Logs](https://app.scalyr.com/solutions/analyze-access-logs) for more information about working with web access logs.

<a name="options"></a>
## Configuration Options

| Property         | Description | 
| ---              | --- | 
| `module`         | Always `scalyr_agent.builtin_monitors.nginx_monitor` | 
| `status_url`     | Optional (defaults to `http://localhost/nginx_status`). The URL the plugin will fetch nginx status information from. | 
| `source_address` | Optional (defaults to `127.0.0.1`). The source IP address to use when fetching the status page. Many servers require this to be `127.0.0.1`, because they only serve the status page to requests from localhost. | 
| `id`             | Optional (defaults to empty string). An id, included with each event. Shows in the UI as a value for the `instance` field. If you are running multiple instances of this plugin, id lets you distinguish between them. This is especially useful if you are running multiple nginx instances on a single server; you can monitor each instance with separate `{...}` stanzas in the configuration file (`/etc/scalyr-agent-2/agent.json`). | 

<a name="events"></a>
## Event Reference

In the UI, each event has the fields:

| Field      | Description | 
| ---        | --- | 
| `monitor`  | Always `nginx_monitor`. | 
| `metric`   | The metric name.  See the metric tables for more information. | 
| `value`    | The value of the metric. | 
| `instance` | The `id` value, if specified. See [Configuration Options](#options). | 

<a name="metrics"></a>
## Metrics Reference

Metrics recorded by this plugin:

| Metric                         | Description | 
| ---                            | --- | 
| `nginx.connections.active`     | The number of connections currently open on the server. The total number of allowed connections is a function of the number of worker_processes and the number of worker_connections in your Nginx configuration file. | 
| `nginx.connections.reading`    | The number of connections currently reading request data. | 
| `nginx.connections.writing`    | The number of connections currently writing response data. | 
| `nginx.connections.waiting`    | The number of connections currently idle / sending keepalives. | 
