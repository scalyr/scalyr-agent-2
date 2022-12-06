/// DECLARE path=/help/monitors/syslog-monitor
/// DECLARE title=Syslog Monitor
/// DECLARE section=help
/// DECLARE subsection=monitors

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

# Syslog

Import logs from an application or device that supports syslog.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).

TCP and UDP protocols are supported. We recommend TCP for reliability and performance, whenever possible.

**For Docker**: We recommend the `json` logging driver. This plugin imports Docker logs configured for the `syslog` driver. Containers on localhost must run the Scalyr Agent and this plugin. Set the `mode` [configuration option](#options) to `docker`.


## Installation

1\. Install the Scalyr Agent

If you haven't already, install the [Scalyr Agent](https://app.scalyr.com/help/welcome). We recommend installing the Agent on each server you want to monitor. Your data will automatically be tagged for the server it came from. The Agent can also collect system metrics and log files.

You can install the Agent on a single server and configure this plugin to accept messages from all hosts.

If you are on Linux, running Python 3, this [memory leak](https://bugs.python.org/issue37193) was fixed in versions [3.8.9](https://docs.python.org/3.8/whatsnew/changelog.html), [3.9.3 final](https://docs.python.org/3.9/whatsnew/changelog.html), and [3.10.0 alpha 4](https://docs.python.org/3/whatsnew/changelog.html).


2\. Configure the Scalyr Agent

Open the Scalyr Agent configuration file at `/etc/scalyr-agent-2/agent.json`.

Find the `monitors: [ ... ]` section, and add a `{...}` stanza with the `module` property set for syslog.

    monitors: [
      {
        module:                    "scalyr_agent.builtin_monitors.syslog_monitor",
        protocols:                 "tcp:601, udp:514",
        accept_remote_connections: false
      }
    ]

The `protocols` property is a string of `protocol:port` combinations, separated by commas. In the above example, the Agent accepts syslog messages on TCP port 601, and UDP port 514. Note that on Linux, the Scalyr Agent must run as root to use port numbers 1024 or lower.

To accept syslog connections from devices other than localhost, for example a firewall or router on the network, add and set  `accept_remote_connections: true`. The Agent will accept connections from any host.

If you are using this plugin to upload dissimilar log formats (ex. firewall, system services, and application logs), we recommend using multiple instances (denoted in the example below by the {...} stanzas). This lets you associate a separate parser and log file for each log type.

    monitors: [
        {
          module: "scalyr_agent.builtin_monitors.syslog_monitor",
          protocols: "tcp:601, udp:514",
          accept_remote_connections: true,
          message_log: "firewall.log",
          parser: "firewall"
        },
        {
          module: "scalyr_agent.builtin_monitors.syslog_monitor",
          protocols: "tcp:602, udp:515",
          accept_remote_connections: true,
          message_log: "system.log", //send ntpdate, chrond, and dhcpd logs here
          parser: "system"
        },
        {
          module: "scalyr_agent.builtin_monitors.syslog_monitor",
          protocols: "tcp:603, udp:516",
          accept_remote_connections: true,
          message_log: "sonicwall.log", //send SonicWall logs here
          parser: "sonicwall"
        }
    ]

The `message_log` property sets the file name to store syslog messages. It defaults to `agent_syslog.log`. The file is placed in the default Scalyr log directory, unless it is an absolute path.

The `parser` property defaults to "agentSyslog". As a best practice, we recommend creating one parser per distinct log type, as this improves maintainability and scalability. More information on configuring parsers can be found [here](https://app.scalyr.com/parsers).

See [Configuration Options](#options) below for more properties you can add.

If you expect a throughput in excess of 2.5 MB/s (216 GB per day), contact Support. We can recommend an optimal configuration.


3\. Configure your application or network device

You must configure each device to send logs to the correct port. Consult the documentation for your application, or device.

To send logs from a different Linux host, you may wish to use the popular `rsyslogd` utility, which has a
powerful configuration language. You can forward some or all logs. For example, suppose this plugin listens on TCP port 601, and you wish to use `rsyslogd` on the local host to import `authpriv` system logs. Add these lines to your `rsyslogd` configuration, typically found at `/etc/rsyslogd.conf`:

    # Send all authpriv messasges.
    authpriv.*                                              @@localhost:601

Make sure you place this line before any other filters that match the authpriv messages. The `@@` prefix
specifies TCP.

In Ubuntu, you must edit the file in `/etc/rsyslog.d/50-default.conf` to include the following line:

<pre><code>*.warn                         @&lt;ip of agent&gt;:514</code></pre>

Where, `<ip of agent>` is replaced with the IP address of the host running the Scalyr Agent. This will forward
all messages of `warning` severity level or higher to the Agent. You must execute
`sudo service rsyslog restart` for the changes to take affect.


4\. Save and confirm

Save the `agent.json` file. The Scalyr Agent will detect changes within 30 seconds. Wait a few minutes for the Agent to send data.

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.

Log in to Scalyr and go to the [Logs](https://app.scalyr.com/logStart) overview page. The log file, which defaults to "agent_syslog.log", should show for each server running this plugin.

From Search view, query [monitor = 'syslog_monitor'](https://app.scalyr.com/events?filter=monitor+%3D+%27syslog_monitor%27). This will show all data collected by this plugin, across all servers.

<a name="options"></a>
## Configuration Options

| Property                             | Description | 
| ---                                  | --- | 
| `module`                             | Always `scalyr_agent.builtin_monitors.syslog_monitor` | 
| `protocols`                          | Optional (defaults to `"tcp:601, udp:514"`). A string of `protocol:port`s, separated by commas. Sets the ports on which the Scalyr Agent will accept messages. We recommend TCP for reliability and performance, whenever possible. | 
| `accept_remote_connections`          | Optional (defaults to `false`). If `true`, this plugin accepts network connections from any host. If `false`, only connections from localhost are accepted. | 
| `message_log`                        | Optional (defaults to `agent_syslog.log`). File name to store syslog messages. The file is put in the default Scalyr log directory, unless it is an absolute path. This is especially useful when running multiple instances of this plugin, to send dissimilar log types to different files. Add and set a separate `{...}` stanza for each instance. | 
| `message_log_template`               | Optional (defaults to `None`, overrides `message_log` when set). Template used to create log file paths to store syslog messages.  The variables $PROTO, $SRCIP, $DESTPORT, $HOSTNAME, $APPNAME will be substituted appropriately.  If the path is not absolute, then it is assumed to be relative to the main Scalyr Agent log directory.  Note that this option is currently only available via a Dockerized Scalyr Agent due to an external dependency. | 
| `parser`                             | Optional (defaults to `agentSyslog`). Parser name for the log file. We recommend using a single parser for each distinct log type, as this improves maintainability and scalability. More information on configuring parsers can be found [here](https://app.scalyr.com/parsers). | 
| `tcp_buffer_size`                    | Optional (defaults to `8192`). Maximum buffer size for a single TCP syslog message. Per [RFC 5425](https://datatracker.ietf.org/doc/html/rfc5425#section-4.3.1) (syslog over TCP/TLS), syslog receivers MUST be able to support messages at least 2048 bytes long, and SHOULD support messages up to 8192 bytes long. | 
| `message_size_can_exceed_tcp_buffer` | Optional (defaults to `false`). If `true`, syslog messages larger than the configured `tcp_buffer_size` are supported. We use `tcp_buffer_size` as the bytes we try to read from the socket in a single recv() call. A single message can span multiple TCP packets, or reads from the socket. | 
| `max_log_size`                       | Optional (defaults to `none`). Maximum size of the log file, before rotation. If `none`, the default value is set from the global `log_rotation_max_bytes` [Agent configuration option](https://app.scalyr.com/help/scalyr-agent-env-aware), which defaults to `20*1024*1024`. Set to `0` for infinite size. Rotation does not show in Scalyr; this property is only relevant for managing disk space on the host running the Agent. A very small limit could cause dropped logs if there is a temporary network outage, and the log overflows before it can be sent. | 
| `max_log_rotations`                  | Optional (defaults to `none`). Maximum number of log rotations, before older log files are deleted. If `none`, the value is set from the global level `log_rotation_backup_count` [Agent configuration option](https://app.scalyr.com/help/scalyr-agent-env-aware), which defaults to `2`. Set to `0` for infinite rotations. | 
| `log_flush_delay`                    | Optional (defaults to `1.0`). Time in seconds to wait between flushing the log file containing the syslog messages. | 
| `tcp_request_parser`                 | Optional (defaults to `"default"`). Sets the TCP packet data request parser. Most users should leave this as is. The `"default"` setting supports framed and line-delimited syslog messages. When set to "batch", all lines are written in a single batch, at the end of processing a packet. This offers better performance at the expense of increased buffer memory. When set to "raw", received data is written as-is: this plugin will not handle framed messages, and received lines are not always written as an atomic unit, but as part of multiple write calls. We recommend this setting when you wish to avoid expensive framed message parsing, and only want to write received data as-is. | 
| `tcp_incomplete_frame_timeout`       | How long to wait (in seconds) for a complete frame / syslog message, when running in TCP mode with batch request parser, before giving up and flushing what has accumulated in the buffer. | 
| `tcp_message_delimiter`              | Which character sequence to use for a message delimiter or suffix. Defaults to `\ n`. Some implementations, such as the Python syslog handler, use the null character `\ 000`; messages can have new lines without the use of framing. | 
| `mode`                               | Optional (defaults to `syslog`). If set to `docker`, this plugin imports log lines sent from the `docker_monitor`. In particular, the plugin will check for container ids in the tags of incoming lines, and create log files based on their container names. | 
| `docker_regex`                       | Regular expression to parse docker logs from a syslog message, when the tag sent to syslog has the container id. Defaults to `"^.*([a-z0-9]{12})\[\d+\]: ?"`. If a message matches this regex, then everything *after* the full matching expression is logged to a file named `docker-<container-name>.log`. | 
| `docker_regex_full`                  | Regular expression for parsing docker logs from a syslog message, when the tag sent to syslog has the container name and id. Defaults to `"^.*([^/]+)/([^[]+)\[\d+\]: ?"`. If a message matches this regex, then everything *after* the full matching expression is logged to a file named `docker-<container-name>.log`. | 
| `docker_expire_log`                  | Optional (defaults to `300`). The number of seconds of inactivity from a specific container before the log file is removed. The log will be created again if a new message is received from the container. | 
| `docker_accept_ips`                  | Optional. A list of ip addresses to accept connections from, if run in a docker container. Defaults to a list with the ip address of the default docker bridge gateway. If `accept_remote_connections` is `true`, this option does nothing. | 
| `docker_api_socket`                  | Optional (defaults to `/var/scalyr/docker.sock`). Sets the Unix socket to communicate with the docker API. Only relevant when `mode` is set to `docker`, to look up container names by their ids. You must set the `api_socket` configuration option in the docker monitor to the same value. You must also map the host's `/run/docker.sock` to the same value as specified here, with the -v parameter, for example `docker run -v /run/docker.sock:/var/scalyr/docker.sock ...`. | 
| `docker_api_version`                 | Optional (defaults to `auto`). Version of the Docker API to use when communicating. WARNING: you must set the `docker_api_version` configuration option in the docker monitor to the same value. | 
| `docker_logfile_template`            | Optional (defaults to `containers/${CNAME}.log`). Template used to create log file paths to save docker logs sent by other containers with syslog. The variables $CNAME and $CID will be substituted with the name and id of the container that is emitting the logs. If the path is not absolute, then it is assumed to be relative to the main Scalyr Agent log directory. | 
| `docker_cid_cache_lifetime_secs`     | Optional (defaults to `300`). Controls the docker id to container name cache expiration. After this number of seconds of inactivity, the cache entry is evicted. | 
| `docker_cid_clean_time_secs`         | Optional (defaults to `5.0`). Number of seconds to wait between cleaning the docker id to container name cache. Fractional values are supported. | 
| `docker_use_daemon_to_resolve`       | Optional (defaults to `true`). When `true`, the Docker daemon resolves container ids to container names, with the `docker_api_socket`.  When `false`, you must add the `--log-opt tag="/{{.Name}}/{{.ID}}"` to your running containers, to include the container name in log messages. | 
| `check_for_unused_logs_mins`         | Optional (defaults to `60`). Number of minutes to wait between checks for log files matching the `message_log_template` that haven't been written to for a while, and can be deleted. | 
| `delete_unused_logs_hours`           | Optional (defaults to `24`). Number of hours to wait before deleting log files matching the `message_log_template`. | 
| `check_rotated_timestamps`           | Optional (defaults to `true`). When `true` the timestamps of all file rotations are checked for deletion, based on the log deletion configuration options. When `false`, only the file modification time of the main log file is checked, and rotated files are deleted when the main log file is deleted. | 
| `expire_log`                         | Optional (defaults to `300`). The number of seconds of inactivity from a specific log source before the log file is removed. The log will be created again if a new message is received from its source. | 
| `docker_check_for_unused_logs_mins`  | Optional (defaults to `60`). Number of minutes to wait between checks for log files matching the `docker_logfile_template` that haven't been written to for a while, and can be deleted. | 
| `docker_delete_unused_logs_hours`    | Optional (defaults to `24`). Number of hours to wait before deleting log files matching the `docker_logfile_template`. | 
| `docker_check_rotated_timestamps`    | Optional (defaults to `true`). When `true` the timestamps of all file rotations are checked for deletion, based on the log deletion configuration options. When `false`, only the file modification time of the main log file is checked, and rotated files are deleted when the main log file is deleted. | 
