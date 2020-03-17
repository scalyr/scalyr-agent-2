/// DECLARE path=/help/monitors/redis-monitor
/// DECLARE title=Redis Monitor
/// DECLARE section=help
/// DECLARE subsection=monitors

# Redis Monitor

A Scalyr agent monitor that imports the Redis SLOWLOG.

The Redis monitor queries the SLOWLOG of a number of Redis servers, and uploads the logs to the Scalyr servers.

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

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->
