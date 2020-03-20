/// DECLARE path=/help/monitors/syslog-monitor
/// DECLARE title=Syslog Monitor
/// DECLARE section=help
/// DECLARE subsection=monitors

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

# Syslog Monitor

The Syslog monitor allows the Scalyr Agent to act as a syslog server, proxying logs from any application or device
that supports syslog. It can recieve log messages via the syslog TCP or syslog UDP protocols.

@class=bg-warning docInfoPanel: An *agent monitor plugin* is a component of the Scalyr Agent. To use a plugin,
simply add it to the ``monitors`` section of the Scalyr Agent configuration file (``/etc/scalyr/agent.json``).
For more information, see [Agent Plugins](/help/scalyr-agent#plugins).


## Sample Configuration

This sample will configure the agent to accept syslog messages on TCP port 601 and UDP port 514, from localhost
only:

    monitors: [
      {
        module:                    "scalyr_agent.builtin_monitors.syslog_monitor",
        protocols:                 "tcp:601, udp:514",
        accept_remote_connections: false
      }
    ]

You can specify any number of protocol/port combinations. Note that on Linux, to use port numbers 1024 or lower,
the agent must be running as root.

You may wish to accept syslog connections from other devices on the network, such as a firewall or router which
exports logs via syslog. Set ``accept_remote_connections`` to true to allow this.

Additional options are documented in the Configuration Reference section, below.


## Log files and parsers

By default, all syslog messages are written to a single log file, named ``agentSyslog.log``. You can use the
``message_log`` option to specify a different file name (see Configuration Reference).

If you'd like to send messages from different devices to different log files, you can include multiple syslog_monitor
stanzas in your configuration file. Specify a different ``message_log`` for each monitor, and have each listen on a
different port number. Then configure each device to send to the appropriate port.

syslog_monitor logs use a parser named ``agentSyslog``. To set up parsing for your syslog messages, go to the
[Parser Setup Page](/parsers?parser=agentSyslog) and click {{menuRef:Leave it to Us}} or
{{menuRef:Build Parser By Hand}}. If you are using multiple syslog_monitor stanzas, you can specify a different
parser for each one, using the ``parser`` option.


## Sending messages via syslog

To send messages to the Scalyr Agent using the syslog protocol, you must configure your application or network
device. The documentation for your application or device should include instructions. We'll be happy to help out;
please drop us a line at [support@scalyr.com](mailto:support@scalyr.com).


### Rsyslogd

To send messages from another Linux host, you may wish to use the popular ``rsyslogd`` utility. rsyslogd has a
powerful configuration language, and can be used to forward all logs or only a selected set of logs.

Here is a simple example. Suppose you have configured Scalyr's Syslog Monitor to listen on TCP port 601, and you
wish to use rsyslogd on the local host to upload system log messages of type ``authpriv``. You would add the following
lines to your rsyslogd configuration, which is typically in ``/etc/rsyslogd.conf``:

    # Send all authpriv messasges to Scalyr.
    authpriv.*                                              @@localhost:601

Make sure that this line comes before any other filters that could match the authpriv messages. The ``@@`` prefix
specifies TCP.


## Viewing Data

Messages uploaded by the Syslog Monitor will appear as an independent log file on the host where the agent is
running. You can find this log file in the [Overview](/logStart) page. By default, the file is named "agentSyslog.log".
## Configuration Reference

|||# Option                               ||| Usage
|||# ``module``                           ||| Always ``scalyr_agent.builtin_monitors.syslog_monitor``
|||# ``protocols``                        ||| Optional (defaults to ``tcp:601``). Lists the protocols and ports on \
                                              which the agent will accept messages. You can include one or more \
                                              entries, separated by commas. Each entry must be of the form ``tcp:NNN`` \
                                              or ``udp:NNN``. Port numbers are optional, defaulting to 601 for TCP and \
                                              514 for UDP
|||# ``accept_remote_connections``        ||| Optional (defaults to false). If true, the plugin will accept network \
                                              connections from any host; otherwise, it will only accept connections \
                                              from localhost.
|||# ``message_log``                      ||| Optional (defaults to ``agent_syslog.log``). Specifies the file name \
                                              under which syslog messages are stored. The file will be placed in the \
                                              default Scalyr log directory, unless it is an absolute path
|||# ``parser``                           ||| Optional (defaults to ``agentSyslog``). Defines the parser name \
                                              associated with the log file
|||# ``tcp_buffer_size``                  ||| Optional (defaults to 8K).  The maximum buffer size for a single TCP \
                                              syslog message.  Note: RFC 5425 (syslog over TCP/TLS) says syslog \
                                              receivers MUST be able to support messages at least 2048 bytes long, and \
                                              recommends they SHOULD support messages up to 8192 bytes long.
|||# ``max_log_size``                     ||| Optional (defaults to None). How large the log file will grow before it \
                                              is rotated. If None, then the default value will be taken from the \
                                              monitor level or the global level log_rotation_max_bytes config option.  \
                                              Set to zero for infinite size. Note that rotation is not visible in \
                                              Scalyr; it is only relevant for managing disk space on the host running \
                                              the agent. However, a very small limit could cause logs to be dropped if \
                                              there is a temporary network outage and the log overflows before it can \
                                              be sent to Scalyr
|||# ``max_log_rotations``                ||| Optional (defaults to None). The maximum number of log rotations before \
                                              older log files are deleted. If None, then the value is taken from the \
                                              monitor level or the global level log_rotation_backup_count option. Set \
                                              to zero for infinite rotations.
|||# ``log_flush_delay``                  ||| Optional (defaults to 1.0). The time to wait in seconds between flushing \
                                              the log file containing the syslog messages.
|||# ``mode``                             ||| Optional (defaults to "syslog"). If set to "docker", the plugin will \
                                              enable extra functionality to properly receive log lines sent via the \
                                              `docker_monitor`.  In particular, the plugin will check for container \
                                              ids in the tags of the incoming lines and create log files based on \
                                              their container names.
|||# ``docker_regex``                     ||| Regular expression for parsing out docker logs from a syslog message \
                                              when the tag sent to syslog only has the container id.  If a message \
                                              matches this regex then everything *after* the full matching expression \
                                              will be logged to a file called docker-<container-name>.log
|||# ``docker_regex_full``                ||| Regular expression for parsing out docker logs from a syslog message \
                                              when the tag sent to syslog included both the container name and id.  If \
                                              a message matches this regex then everything *after* the full matching \
                                              expression will be logged to a file called docker-<container-name>.log
|||# ``docker_expire_log``                ||| Optional (defaults to 300).  The number of seconds of inactivity from a \
                                              specific container before the log file is removed.  The log will be \
                                              created again if a new message comes in from the container
|||# ``docker_accept_ips``                ||| Optional.  A list of ip addresses to accept connections from if being \
                                              run in a docker container. Defaults to a list with the ip address of the \
                                              default docker bridge gateway. If accept_remote_connections is true, \
                                              this option does nothing.
|||# ``docker_api_socket``                ||| Optional (defaults to /var/scalyr/docker.sock). Defines the unix socket \
                                              used to communicate with the docker API. This is only used when `mode` \
                                              is set to `docker` to look up container names by their ids.  WARNING, \
                                              you must also set the `api_socket` configuration option in the docker \
                                              monitor to this same value.
Note:  You need to map the host's \
                                              /run/docker.sock to the same value as specified here, using the -v \
                                              parameter, e.g.
	docker run -v /run/docker.sock:/var/scalyr/docker.sock \
                                              ...
|||# ``docker_api_version``               ||| Optional (defaults to 'auto'). The version of the Docker API to use when \
                                              communicating to docker.  WARNING, you must also set the \
                                              `docker_api_version` configuration option in the docker monitor to this \
                                              same value.
|||# ``docker_logfile_template``          ||| Optional (defaults to 'containers/${CNAME}.log'). The template used to \
                                              create the log file paths for save docker logs sent by other containers \
                                              via syslog.  The variables $CNAME and $CID will be substituted with the \
                                              name and id of the container that is emitting the logs.  If the path is \
                                              not absolute, then it is assumed to be relative to the main Scalyr Agent \
                                              log directory.
|||# ``docker_cid_cache_lifetime_secs``   ||| Optional (defaults to 300). Controls the docker id to container name \
                                              cache expiration.  After this number of seconds of inactivity, the cache \
                                              entry will be evicted.
|||# ``docker_cid_clean_time_secs``       ||| Optional (defaults to 5.0). The number seconds to wait between cleaning \
                                              the docker id to container name cache.
|||# ``docker_use_daemon_to_resolve``     ||| Optional (defaults to True). If True, will use the Docker daemon (via \
                                              the docker_api_socket to resolve container ids to container names.  If \
                                              you set this to False, you must be sure to add the --log-opt \
                                              tag="/{{.Name}}/{{.ID}}" to your running containers to pass the \
                                              container name in the log messages.
|||# ``docker_check_for_unused_logs_mins``||| Optional (defaults to 60). The number of minutes to wait between \
                                              checking to see if there are any log files matchings the \
                                              docker_logfile_template that haven't been written to for a while and can \
                                              be deleted
|||# ``docker_delete_unused_logs_hours``  ||| Optional (defaults to 24). The number of hours to wait before deleting \
                                              any log files matchings the docker_logfile_template
|||# ``docker_check_rotated_timestamps``  ||| Optional (defaults to True). If True, will check timestamps of all file \
                                              rotations to see if they should be individually deleted based on the the \
                                              log deletion configuration options. If False, only the file modification \
                                              time of the main log file is checked, and the rotated files will only be \
                                              deleted when the main log file is deleted.
