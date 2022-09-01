/// DECLARE path=/help/monitors/redis-monitor
/// DECLARE title=Redis Monitor
/// DECLARE section=help
/// DECLARE subsection=monitors

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

# Redis

Import the Redis SLOWLOG.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).


## Installation


1\. Install the Scalyr Agent

If you haven't already, install the [Scalyr Agent](https://app.scalyr.com/help/welcome). We recommend you install the Agent on each server running Redis. Your data will automatically be tagged for the server it came from, and the Agent can also collect system metrics and log files.


2\. Configure the Scalyr Agent to import the Redis SLOWLOG

Open the Scalyr Agent configuration file, located at `/etc/scalyr-agent-2/agent.json`.

Find the `monitors: [ ... ]` section and add a `{...}` stanza with the `module` property set for Redis:

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.redis_monitor",
      }
    ]

This default configuration is for a Redis server without a password, located at `localhost:6379`. To change these defaults, add a `hosts [...]` array. Then add and set a `{...}` stanza for each host with the applicable `host`, `port`, and `password` properties. An example for two hosts, with passwords:

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.redis_monitor",
        hosts: [
           { "host": "redis.example.com", "password": "secret" },
           { "host": "localhost", "password": "anothersecret", port: 6380 }
        ]
      }
    ]

See [Configuration Options](#options) below for more properties you can add.


3\. Save and confirm

Save the `agent.json` file. The Agent will detect changes within 30 seconds. Wait a few minutes for the Agent to begin sending the Redis SLOWLOG.

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.

Log into Scalyr. From Search view query [monitor = 'redis_monitor'](/events&filter=monitor+%3D+%27redis_monitor%27).

For help, contact Support.

<a name="options"></a>
## Configuration Options

| Property                           | Description | 
| ---                                | --- | 
| `module`                           | Always `scalyr_agent.builtin_monitors.redis_monitor` | 
| `hosts`                            | Optional (defaults to `[{ "host": "localhost", "port": 6379, "password": none}]`). An array of `{...}` objects. Each object sets `host`, `port`, and `password` properties. | 
| `log_cluster_replication_info`     | Optional (defaults to `false`). If `true`, this plugin collects the Redis cluster's replication offsets, the difference between master and replica, and how many seconds the replica is falling behind. | 
| `lines_to_fetch`                   | Optional (defaults to `500`). Number of lines to fetch from the SLOWLOG each `sample_interval`. Set this value based on your expected load; some lines will be dropped if more than this number of messages are logged to the SLOWLOG between sample intervals. Make sure the redis-server `slowlog-max-len` configuration option is set to at least the same size. See line 1819 in this example [redis.conf](https://www.google.com/url?sa=t&rct=j&q=&esrc=s&source=web&cd=&ved=2ahUKEwiTiNXQoPj3AhXYkokEHYw8AhoQFnoECB0QAQ&url=https%3A%2F%2Fdownload.redis.io%2Fredis-stable%2Fredis.conf&usg=AOvVaw3_kFM1q_S7L9omTrS8uL23) file. Also set the `sample_interval` to match your expected traffic (see below). | 
| `connection_timeout`               | Optional (defaults to `5`). Number of seconds to wait when querying a Redis server before timing out, and giving up. | 
| `connection_error_repeat_interval` | Optional (defaults to `300`). Seconds to wait before repeating an error message (when multiple errors are detected). | 
| `utf8_warning_interval`            | Optional (defaults to `600`). Minimum seconds to wait between warnings about invalid utf8 in redis slow log messages. Set to 0 to disable the warning altogether. | 
| `sample_interval`                  | Optional (defaults to `30`). Seconds to wait between queries to the Redis SLOWLOG. If you expect a high volume of logs, set this value low enough so the number of messages you receive in this interval does not exceed the value of `lines_to_fetch`, otherwise some lines will be dropped. | 
