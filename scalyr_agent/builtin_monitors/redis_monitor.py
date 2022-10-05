# Copyright 2015 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ------------------------------------------------------------------------
#
# This monitor imports the Redis SLOWLOG.
#
# author:  Imron Alston <imron@scalyr.com>
from __future__ import unicode_literals
from __future__ import absolute_import

__author__ = "imron@scalyr.com"

import binascii
import re
import time

from six.moves import range

from scalyr_agent import ScalyrMonitor, define_config_option

from redis.client import Redis, parse_info  # pylint: disable=import-error
from redis.exceptions import (  # pylint: disable=import-error
    ConnectionError,
    TimeoutError,
)

MORE_BYTES = re.compile(b"\.\.\. \(\d+ more bytes\)$")  # NOQA

__monitor__ = __name__

define_config_option(
    __monitor__,
    "module",
    "Always `scalyr_agent.builtin_monitors.redis_monitor`",
    required_option=True,
)

define_config_option(
    __monitor__,
    "hosts",
    'Optional (defaults to `[{ "host": "localhost", "port": 6379, "password": none}]`). '
    "An array of host objects; each sets `host`, "
    "`port`, and `password` properties.",
    default={"host": "localhost", "port": 6379, "password": None},
)

define_config_option(
    __monitor__,
    "log_cluster_replication_info",
    "Optional (defaults to `false`). If `true`, this plugin collects the Redis cluster's "
    "replication offsets, the difference between master and replica, and how many seconds "
    "the replica is falling behind.",
    default=False,
)

define_config_option(
    __monitor__,
    "lines_to_fetch",
    "Optional (defaults to `500`). Number of lines to fetch from the SLOWLOG each `sample_interval`. "
    "Set this value based on your expected load; some lines will be dropped if "
    "more than this number of messages are logged to the SLOWLOG between sample intervals. "
    "Make sure the redis-server `slowlog-max-len` configuration option is set to at least "
    "the same size. See line 1819 in this [redis.conf](https://www.google.com/url?sa=t&rct=j&q=&esrc=s&source=web&cd=&ved=2ahUKEwiTiNXQoPj3AhXYkokEHYw8AhoQFnoECB0QAQ&url=https%3A%2F%2Fdownload.redis.io%2Fredis-stable%2Fredis.conf&usg=AOvVaw3_kFM1q_S7L9omTrS8uL23) example file. Also set the "
    "`sample_interval` to match your expected traffic (see below).",
    default=500,
    convert_to=int,
    min_value=10,
    max_value=5000,
)

define_config_option(
    __monitor__,
    "connection_timeout",
    "Optional (defaults to `5`). Number of seconds to wait when querying a Redis server "
    "before timing out and giving up.",
    default=5,
    convert_to=int,
    min_value=0,
    max_value=60,
)

define_config_option(
    __monitor__,
    "connection_error_repeat_interval",
    "Optional (defaults to `300`). Seconds to wait before repeating an "
    "error message (when multiple errors are detected).",
    default=300,
    convert_to=int,
    min_value=10,
    max_value=6000,
)

define_config_option(
    __monitor__,
    "utf8_warning_interval",
    "Optional (defaults to `600`). Minimum seconds to wait between "
    "warnings about invalid utf8 in redis slow log messages. Set to 0 to disable "
    "the warning altogether.",
    default=600,
    convert_to=int,
    min_value=0,
    max_value=6000,
)

define_config_option(
    __monitor__,
    "sample_interval",
    "Optional (defaults to `30`). Seconds to wait between queries "
    "to the Redis SLOWLOG. If you expect a high volume of logs, set this value low "
    "enough so the number of messages you receive in this interval does not "
    "exceed the value of `lines_to_fetch`, otherwise some lines will be dropped.",
)


class RedisHost(object):
    """Class that holds various information about a specific redis connection"""

    def __init__(self, host, port, password, connection_timeout):
        # redis instance information
        self.__host = host
        self.__port = port
        self.__password = password
        self.__connection_timeout = connection_timeout

        # how long to delay between invalid utf8 warnings
        # 0 is never show warnings
        self.utf8_warning_interval = 0

        # ID of the last slowlog entry
        self.last_id = 0

        # Timestamp of the last slowlog entry
        self.last_timestamp = 0

        # master offset of the last replication entry
        self.last_master_offset = 0

        # Timestamp of the last replication entry
        self.last_replication_sample_timestamp = 0

        # Redis object
        self.__redis = None

        # Boolean flag to see if it's the first time we are connecting to
        # this redis instance
        self.__first_connection = True

        # Boolean flag to tell if the connection to the redis instance
        # was reset
        self.__reset = False

        # run_id of the redis server
        self.__run_id = None

        # String for display purposes
        self.__display_string = ""

    def valid(self):
        """Check if we are currently connected to a redis instance"""
        return self.__redis is not None

    def __update_latest(self, redis):
        """Get the most recent entry in the slow log and store its ID.

        If it's the first connection for this RedisHost just get the
        latest entry in the slowlog, otherwise ignore because we will have
        previous values for the last_id and timestamp.
        """
        if self.__first_connection:
            pipeline = redis.pipeline(transaction=False)
            results = pipeline.info().slowlog_get(1).execute()
            if len(results) != 2:
                raise Exception("Error initializing slowlog data")

            self.__first_connection = False
            self.check_for_reset(results[0])
            self.__reset = False
            latest = results[1]
            if latest:
                self.last_id = latest[0]["id"]
                self.last_timestamp = latest[0]["start_time"]

    def check_for_reset(self, info):
        if "run_id" not in info:
            raise Exception(
                "Unsupported redis version.  redis_monitor requires a version of redis >= 2.4.17"
            )

        if self.__run_id != info["run_id"]:
            self.__reset = True
            self.__run_id = info["run_id"]

    def log_slowlog_entries(self, logger, lines_to_fetch):
        """Fetch entries from the redis slowlog and emit them to Scalyr
        if they pass a predicate test - which will either be on the id
        or the timestamp, depending on whether or not the connection
        has been reset in between calls to this function
        """

        # pipeline info and slowlog calls
        pipe = self.redis.pipeline(transaction=False)

        results = pipe.info().slowlog_get(lines_to_fetch).execute()

        if len(results) != 2:
            raise Exception("Error fetching slowlog data")

        self.check_for_reset(results[0])

        entries = results[1]

        # by default use the id based predicate to get the entries
        key = "id"
        value = self.last_id

        # default warning message
        warning = "Too many log messages since last query.  Some log lines may have been dropped"

        # if our connection was reset since the last time we checked the slowlog then
        # get entries based on timestamp instead, because the server might have been restarted
        # which will invalidate any previous ids
        if self.__reset:
            warning = (
                "Redis server reset detected for %s.  Some log lines may have been dropped"
                % self.display_string
            )
            key = "start_time"
            value = self.last_timestamp

            # reset the last id to 0 if there were no entries
            # we do this here instead of in reset_connection in case
            # the lost connection was not caused by a server reset
            if not entries:
                self.last_id = 0

        self.__reset = False

        # build a list of unseen entries. We do this because it's likely that only the
        # first few entries in the list will pass the predicate, meaning we don't need
        # to scan the entire list each time
        unseen_entries = []

        # True if entries is empty, false if it contains items
        # This is to prevent issuing a warning message when nothing
        # was returned
        found_previous = len(entries) == 0

        for entry in entries:
            if entry[key] > value:
                unseen_entries.append(entry)
            else:
                # If we are here then entry[key] is <= value
                # That being the case, then if the id and timestamp matches then we haven't
                # dropped any messages
                if (
                    entry["id"] == self.last_id
                    and entry["start_time"] == self.last_timestamp
                ):
                    found_previous = True

                # break the loop because all other entries should fail the predicate
                break

        if not found_previous:
            logger.warn(warning)

        # print it out in reverse because redis sends entries in reverse order
        for entry in reversed(unseen_entries):
            self.log_entry(logger, entry)

    def log_cluster_replication_info(self, logger):
        # Gather replication information from Redis
        replication_info = parse_info(self.redis.execute_command("INFO REPLICATION"))

        # We only care about information from Redis master, which contains offsets from both master and replica
        if replication_info["role"] != "master":
            return

        master_repl_offset = replication_info["master_repl_offset"]

        if master_repl_offset == 0:
            return

        master_replid = replication_info["master_replid"]
        connected_replicas = replication_info["connected_slaves"]

        # If there are more than one replicas, log the most up-to-date
        max_replica_offset = 0
        for n in range(connected_replicas):
            max_replica_offset = max(
                max_replica_offset, replication_info["slave%d" % n]["offset"]
            )

        offset_difference = int(master_repl_offset - max_replica_offset)

        now = time.time()

        # Offset difference between master and replica doesn't indicate how far behind the slave is, in wall clock time
        #
        # we calculate how many seconds the replica is falling behind, by comparing
        # a. offset difference between master and replica
        # and
        # b. master offset's change rate (per second)
        master_offset_change_per_sec = int(
            (master_repl_offset - self.last_master_offset)
            / (now - self.last_replication_sample_timestamp)
        )
        replica_lag_secs = int(offset_difference / master_offset_change_per_sec)

        time_format = "%Y-%m-%d %H:%M:%SZ"
        logger.emit_value(
            "redis",
            "replication",
            extra_fields={
                "host": self.display_string,
                "ts": time.strftime(time_format, time.gmtime(now)),
                "masterId": master_replid,
                "masterOffset": master_repl_offset,
                "connectedReplicas": connected_replicas,
                "maxReplicaOffset": max_replica_offset,
                "offsetDiff": offset_difference,
                "masterOffsetDiffPerSec": master_offset_change_per_sec,
                "replicaLagSecs": replica_lag_secs,
            },
        )

        self.last_master_offset = master_repl_offset
        self.last_replication_sample_timestamp = now

    def log_entry(self, logger, entry):
        # check to see if redis truncated the command
        entry_command = entry["command"]
        match = MORE_BYTES.search(entry_command)
        if match:
            pos, length = match.span()
            pos -= 1
            # find the first byte which is not a 'middle' byte in utf8
            # middle bytes always begin with b10xxxxxx which means they
            # will be >= b10000000 and <= b10111111
            # 2->TODO use bytes slicing to get single element bytes array in both python versions.
            while pos > 0 and 0x80 <= ord(entry_command[pos : pos + 1]) <= 0xBF:
                pos -= 1

            # at this point, entry['command'][pos] will either be a single byte character or
            # the start of a truncated multibyte character.
            # If it's a single character, skip over it so it's included in the slice
            # If it's the start of a truncated multibyte character don't do anything
            # and the truncated bytes will be removed with the slice
            # 2->TODO use bytes slicing to get single element bytes array in both python versions.
            if ord(entry_command[pos : pos + 1]) < 0x80:
                pos += 1

            # slice off any unwanted parts of the string
            entry_command = entry_command[:pos] + match.group()

        try:
            command = entry_command.decode("utf8")
        except UnicodeDecodeError:
            if self.utf8_warning_interval:
                logger.warn(
                    "Redis command contains invalid utf8: %s"
                    % binascii.hexlify(entry_command),
                    limit_once_per_x_secs=self.utf8_warning_interval,
                    limit_key="redis-utf8",
                )
            command = entry_command.decode("utf8", "replace")

        time_format = "%Y-%m-%d %H:%M:%SZ"
        logger.emit_value(
            "redis",
            "slowlog",
            extra_fields={
                "host": self.display_string,
                "ts": time.strftime(time_format, time.gmtime(entry["start_time"])),
                "exectime": entry["duration"],
                "command": command,
            },
        )
        self.last_id = entry["id"]
        self.last_timestamp = entry["start_time"]

    @property
    def display_string(self):
        if not self.__display_string:
            self.__display_string = "%s:%d" % (self.__host, self.__port)
        return self.__display_string

    @property
    def redis(self):
        """Returns the redis.client object for the given host/port
        Performing lazy initialization if it hasn't already been created
        """
        if not self.__redis:
            redis = Redis(
                host=self.__host,
                port=self.__port,
                password=self.__password,
                socket_timeout=self.__connection_timeout,
            )
            self.__update_latest(redis)
            # __update_latest can raise an exception, so don't assign to self until it
            # completes successfully
            self.__redis = redis
        return self.__redis


class RedisMonitor(ScalyrMonitor):  # pylint: disable=monitor-not-included-for-win32
    # fmt: off
    r"""
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

    """
    # fmt: on

    def _initialize(self):
        """Performs monitor-specific initialization."""
        # The number of entries to request each pass
        self.__lines_to_fetch = self._config.get(
            "lines_to_fetch", default=500, convert_to=int, min_value=10, max_value=5000
        )

        # The number of seconds to wait before redisplaying connection errors
        self.__connection_error_repeat_interval = self._config.get(
            "connection_error_repeat_interval",
            default=300,
            convert_to=int,
            min_value=10,
            max_value=6000,
        )

        # The number of seconds to wait when querying the redis server
        self.__connection_timeout = self._config.get(
            "connection_timeout", default=5, convert_to=int, min_value=0, max_value=60
        )

        # The number of seconds to wait before reissuing warnings about invalid utf8 in slowlog messages.
        self.__utf8_warning_interval = self._config.get(
            "utf8_warning_interval",
            default=600,
            convert_to=int,
            min_value=0,
            max_value=6000,
        )

        # Whether to record cluster replication information
        self.log_cluster_replication_info = self._config.get(
            "log_cluster_replication_info"
        )

        # Redis-py requires None rather than 0 if no timeout
        if self.__connection_timeout == 0:
            self.__connection_timeout = None

        # A list of RedisHosts
        self.__redis_hosts = []

        hosts = self._config.get("hosts")

        default_config = {"host": "localhost", "port": 6379, "password": None}

        # add at least one host if none were specified
        if not hosts:
            hosts = [default_config]

        for host in hosts:
            # update the config, using default values for anything that was unspecified
            config = default_config.copy()
            config.update(host)

            # create a new redis host
            redis_host = RedisHost(
                config["host"],
                config["port"],
                config["password"],
                self.__connection_timeout,
            )
            redis_host.utf8_warning_interval = self.__utf8_warning_interval
            self.__redis_hosts.append(redis_host)

    def gather_sample(self):
        for host in self.__redis_hosts:
            new_connection = not host.valid()
            try:
                host.log_slowlog_entries(self._logger, self.__lines_to_fetch)

                if self.log_cluster_replication_info:
                    host.log_cluster_replication_info(self._logger)

            except ConnectionError:
                if new_connection:
                    self._logger.error(
                        "Unable to establish connection: %s" % (host.display_string),
                        limit_once_per_x_secs=self.__connection_error_repeat_interval,
                        limit_key=host.display_string,
                    )
                else:
                    self._logger.error(
                        "Connection to redis lost: %s" % host.display_string
                    )
            except TimeoutError:
                self._logger.warn("Connection timed out: %s" % host.display_string)
