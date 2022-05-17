/// DECLARE path=/help/monitors/apache
/// DECLARE title=Apache Monitor
/// DECLARE section=help
/// DECLARE subsection=monitors

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

# Apache

Import performance and usage data from an Apache server.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).


## Installation

1\. Install the Scalyr Agent

If you haven't already done so, install the [Scalyr Agent](https://app.scalyr.com/help/welcome) on servers running Apache.


2\. Check requirements

The `status_module` [module](https://httpd.apache.org/docs/current/mod/mod_status.html) must be enabled on the Apache server. On most Linux installations you can run:

    ls /etc/apache2/mods-enabled

If you see `status.conf` and `status.load`, the module is enabled. If not, you can enable the module on most Linux installations by running:

    sudo /usr/sbin/a2enmod status

On some platforms, different commands will enable the `status_module` (filename `mod_status.so`). Consult the documentation for your particular platform. You can also consult:
- [CentOS](https://www.linuxcnf.com/2018/11/how-to-configure-apache-modstatus.html)
- [RHEL, see "Working with modules" section](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/8/html/deploying_different_types_of_servers/setting-apache-http-server_deploying-different-types-of-servers)
- [Ubuntu](https://ubuntu.com/server/docs/web-servers-apache)
- [Windows](http://httpd.apache.org/docs/2.0/platform/windows.html#cust)


3\. Configure access to the `server-status` page.

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


4\. Restart and confirm

When you make the configuration change, restart Apache.  On most Linux systems, run:

    sudo service apache2 restart

To confirm the status module, run this command, substituting the port number as applicable:

    curl http://localhost:80/server-status


5\. Configure the Scalyr Agent to import status module data

Open the Scalyr Agent configuration file, found at `/etc/scalyr-agent-2/agent.json`.

Find the `monitors: [ ... ]` section and add a `{...}` stanza for the Apache `module` property. Set the `status_url` property, replacing `80` with the applicable port number if you are on a nonstandard port:

    monitors: [
      {
          module: "scalyr_agent.builtin_monitors.apache_monitor",
          status_url: "http://localhost:80/server-status/?auto"
      }
    ]

See [Configuration Options](#options) below for more properties you can add.


6\. Configure the Scalyr Agent to import Apache access logs

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


7\. Save and confirm

Save the `agent.json` file. The Agent will detect changes within 30 seconds. Wait a few minutes for the Scalyr Agent to begin sending Apache data.

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.

Log into Scalyr and click Dashboards > Apache. You will see an overview of Apache data, across all servers, configured for this plugin.

The [Event Reference](#events) below explains the fields created by this plugin.

For help, contact us at [support@scalyr.com](mailto:support@scalyr.com).


## Further Reading

See [Analyze Access Logs](https://app.scalyr.com/solutions/analyze-access-logs) for more information about working with web access logs.

<a name="options"></a>
## Configuration Options

| Property         | Description | 
| ---              | --- | 
| `module`         | Always `scalyr_agent.builtin_monitors.apache_monitor` | 
| `id`             | Optional (defaults to empty string). An id, included with each event. Shows in the UI as a value for the `instance` field. If you are running multiple instances of this plugin, id lets you distinguish between them. This is especially useful if you are running multiple Apache instances on a single server; you can monitor each instance with separate `{...}` stanzas in the configuration file (`/etc/scalyr-agent-2/agent.json`). | 
| `status_url`     | Optional (defaults to `http://localhost/server-status/?auto`). The URL, in particular the port number, at which the Apache status module is served. The URL should end in `/?auto` to indicate that the machine-readable version of the page should be returned. | 
| `source_address` | Optional (defaults to `127.0.0.1`). The source IP address to use when fetching the status page. Many servers require this to be `127.0.0.1`, because they only serve the status page to requests from localhost. | 

<a name="events"></a>
## Event Reference

In the UI, each event has the fields:

| Field      | Description | 
| ---        | --- | 
| `monitor`  | Always `apache_monitor`. | 
| `metric`   | The metric name.  See the metric tables for more information. | 
| `value`    | The value of the metric. | 
| `instance` | The `id` value, if specified. See [Configuration Options](#options). | 

<a name="metrics"></a>
## Metrics Reference

Metrics recorded by this plugin:

| Metric                          | Description | 
| ---                             | --- | 
| `apache.connections.active`     | The number of asynchronous connections (not using  workers) currently open on the server. | 
| `apache.connections.writing`    | The number of asynchronous connections (not using workers) that are currently writing response data. | 
| `apache.connections.idle`       | The number of asynchronous connections (not using workers) that are currently idle / sending keepalives. | 
| `apache.connections.closing`    | The number of asynchronous connections (not using workers) that are currently closing. | 
| `apache.workers.active`         | The number of currently active workers. Each worker is a process handling an incoming request. | 
| `apache.workers.idle`           | The number of currently idle workers. Each worker is a process that can handle an incoming request. | 
