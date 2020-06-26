/// DECLARE path=/help/monitors/redis-monitor
/// DECLARE title=Redis Monitor
/// DECLARE section=help
/// DECLARE subsection=monitors

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

# Redis Monitor

A Scalyr agent monitor that imports the Redis SLOWLOG.

The Redis monitor queries the slowlog of a number of Redis servers, and uploads the logs
to the Scalyr servers.

@class=bg-warning docInfoPanel: An *agent monitor plugin* is a component of the Scalyr Agent. To use a plugin,
simply add it to the ``monitors`` section of the Scalyr Agent configuration file (``/etc/scalyr/agent.json``).
For more information, see [Agent Plugins](/help/scalyr-agent#plugins).

## Sample Configuration

The following example will configure the agent to query a redis server located at ``localhost:6379`` and that does not require
a password

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.redis_monitor",
      }
    ]

Here is an example with two hosts with passwords:

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.redis_monitor",
        hosts: [
           { "host": "redis.example.com", "password": "secret" },
           { "host": "localhost", "password": "anothersecret", port: 6380 }
        ]
      }
    ]

*   hosts - an array of 'host' objects. Each host object can contain any or all of the following keys: "host", "port", "password".
    Missing keys will be filled in with the defaults: 'localhost', 6379, and <None>.

    For example:

    hosts: [
        { "host": "redis.example.com", "password": "secret" },
        { "port": 6380 }
    ]

    Will create connections to 2 Redis servers: redis.example.com:6379 with the password 'secret' and
    localhost:6380 without a password.

    Each host in the list will be queried once per sample interval.

*   lines_to_fetch - the number of lines to fetch from the slowlog each sample interval.  Defaults to 500.
    This value should be set based on your expected load.  If more than this number of messages are logged to the
    slowlog between sample intervals then some lines will be dropped.

    You should make sure that the redis-server slowlog-max-len config option is set to at least the same size as
    this value.

    You should also set your sample_interval to match your expected traffic (see below).

*   connection_timeout - the number of seconds to wait when querying a Redis server before timing out and giving up.
    Defaults to 5.

*   connection_error_repeat_interval - if multiple connection errors are detected, the number of seconds to wait before
    redisplaying an error message.  Defaults to 300.

*   utf8_warning_interval - the minimum amount of time in seconds to wait between issuing warnings about invalid utf8 in redis slow
    log messages.  Set to 0 to disable the warning altogether. Defaults to 600


*   sample_interval - the number of seconds to wait between successive queryies to the Redis slowlog.  This defaults to 30 seconds
    for most monitors, however if you are expecting a high volume of logs you should set this to a low enough value
    such that the number of messages you receive in this interval does not exceed the value of `lines_to_fetch`, otherwise
    some log lines will be dropped.

## Configuration Reference

|||# Option                          ||| Usage
|||# ``log_cluster_replication_info``||| Optional (defaults to false). If true, the monitor will record redis \
                                         cluster's replication offsets, difference between master and replica, and how \
                                         many seconds the replica is falling behind
