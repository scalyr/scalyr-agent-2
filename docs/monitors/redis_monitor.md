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

## Configuration Reference

Here is the list of all configuration options you may use to config the Redis monitor:

|||# Option                        ||| Usage
|||# ``module``                    ||| Always ``scalyr_agent.builtin_monitors.redis_monitor``
|||# ``hosts``                     ||| Optional (defaults to ``[{ "host": "localhost", "port": 6379}]``). An array of \
                                      'host' objects. Each host object can contain any or all of the following keys: \
                                      ``"host"``, ``"port"``, ``"password"``. Missing keys will be filled in with the \
                                      defaults: ``'localhost'``, ``6379``, and ``<None>``.
|||# ``lines_to_fetch``            ||| Optional (defaults to ``500``). The number of lines to fetch from the SLOWLOG \
                                       each sample interval.  This value should be set based on your expected load.  \
                                       If more than this number of messages are logged to the SLOWLOG between sample \
                                       intervals then some lines will be dropped.  You should make sure that the \
                                       redis-server slowlog-max-len config option is set to at least the same size as \
                                       this value. You should also set your sample_interval to match your expected \
                                       traffic (see below).
|||# ``connection_timeout``        ||| Optional (defaults to ``5``). The number of seconds to wait when querying a \
                                       Redis server before timing out and giving up.
|||# ``connection_error_repeat_interval``  ||| Optional (defaults to ``300``).  If multiple connection errors are \
                                               detected, the number of seconds to wait before redisplaying an error message.
|||# ``utf8_warning_interval``     ||| Optional (defaults to ``600``). The minimum amount of time in seconds to wait \
                                       between issuing warnings about invalid utf8 in redis slow log messages.  Set to 0 \
                                       to disable the warning altogether.
|||# ``sample_interval``           ||| Optional (defaults to ``30``). The number of seconds to wait between successive \
                                       queries to the Redis SLOWLOG.  If you are expecting a high volume of logs you \
                                       should set this to a low enough value such that the number of messages you \
                                       receive in this interval does not exceed the value of `lines_to_fetch`, \
                                       otherwise some log lines will be dropped.
