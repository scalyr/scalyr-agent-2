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

__author__ = 'imron@scalyr.com'

import binascii
import re
import time

from scalyr_agent import ScalyrMonitor

from redis.client import Redis
from redis.exceptions import ConnectionError, TimeoutError

MORE_BYTES = re.compile( '\.\.\. \(\d+ more bytes\)$' )


class RedisHost( object ):
    """Class that holds various information about a specific redis connection
    """
    def __init__( self, host, port, password, connection_timeout ):
        #redis instance information
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


    def valid( self ):
        """Check if we are currently connected to a redis instance"""
        return self.__redis != None

    def __update_latest( self, redis ):
        """Get the most recent entry in the slow log and store its ID.

        If it's the first connection for this RedisHost just get the
        latest entry in the slowlog, otherwise ignore because we will have
        previous values for the last_id and timestamp.
        """
        if self.__first_connection:
            pipeline = redis.pipeline( transaction=False )
            results = pipeline.info().slowlog_get( 1 ).execute()
            if len( results ) != 2:
                raise Exception( "Error initializing slowlog data" )

            self.__first_connection = False
            self.check_for_reset( results[0] )
            self.__reset = False
            latest = results[1]
            if latest:
                self.last_id = latest[0]['id']
                self.last_timestamp = latest[0]['start_time']


    def check_for_reset( self, info ):
        if not 'run_id' in info:
            raise Exception( "Unsupported redis version.  redis_monitor requires a version of redis >= 2.4.17" )

        if self.__run_id != info['run_id']:
            self.__reset = True
            self.__run_id = info['run_id']

    def log_slowlog_entries( self, logger, lines_to_fetch ):
        """Fetch entries from the redis slowlog and emit them to Scalyr
        if they pass a predicate test - which will either be on the id
        or the timestamp, depending on whether or not the connection
        has been reset in between calls to this function
        """

        # pipeline info and slowlog calls
        pipe = self.redis.pipeline( transaction=False )

        results = pipe.info().slowlog_get( lines_to_fetch ).execute()

        if len( results ) != 2:
            raise Exception( "Error fetching slowlog data" )

        self.check_for_reset( results[0] )

        entries = results[1]

        # by default use the id based predicate to get the entries
        key = 'id'
        value = self.last_id

        #default warning message
        warning = "Too many log messages since last query.  Some log lines may have been dropped"

        # if our connection was reset since the last time we checked the slowlog then
        # get entries based on timestamp instead, because the server might have been restarted
        # which will invalidate any previous ids
        if self.__reset:
            warning = "Redis server reset detected for %s.  Some log lines may have been dropped" % self.display_string
            key = 'start_time'
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
        found_previous = len( entries ) == 0

        for entry in entries:
            if entry[key] > value:
                unseen_entries.append( entry )
            else:
                # If we are here then entry[key] is <= value
                # That being the case, then if the id and timestamp matches then we haven't
                # dropped any messages
                if entry['id'] == self.last_id and entry['start_time'] == self.last_timestamp:
                    found_previous = True

                # break the loop because all other entries should fail the predicate
                break

        if not found_previous:
            logger.warn( warning )

        # print it out in reverse because redis sends entries in reverse order
        for entry in reversed( unseen_entries ):
            self.log_entry( logger, entry )


    def log_entry( self, logger, entry ):
        # check to see if redis truncated the command
        match = MORE_BYTES.search( entry['command'] )
        if match:
            pos, length = match.span()
            pos -= 1
            # find the first byte which is not a 'middle' byte in utf8
            # middle bytes always begin with b10xxxxxx which means they
            # will be >= b10000000 and <= b10111111
            while pos > 0 and 0x80 <= ord( entry['command'][pos] ) <= 0xBF:
                pos -= 1

            # at this point, entry['command'][pos] will either be a single byte character or
            # the start of a truncated multibyte character.
            # If it's a single character, skip over it so it's included in the slice
            # If it's the start of a truncated multibyte character don't do anything
            # and the truncated bytes will be removed with the slice
            if ord( entry['command'][pos] ) < 0x80:
                pos += 1

            #slice off any unwanted parts of the string
            entry['command'] = entry['command'][:pos] + match.group()

        command = ""
        try:
            command = entry['command'].decode( 'utf8' )
        except UnicodeDecodeError, e:
            if self.utf8_warning_interval:
                logger.warn( "Redis command contains invalid utf8: %s" % binascii.hexlify( entry['command'] ), limit_once_per_x_secs=self.utf8_warning_interval, limit_key="redis-utf8" )
            command = entry['command'].decode( 'utf8', errors="replace" )

        time_format = "%Y-%m-%d %H:%M:%SZ"
        logger.emit_value( 'redis', 'slowlog', extra_fields={
            'host': self.display_string,
            'ts': time.strftime( time_format, time.gmtime( entry['start_time'] ) ),
            'exectime' : entry['duration'],
            'command' : command
        } )
        self.last_id = entry['id']
        self.last_timestamp = entry['start_time']

    @property
    def display_string(self):
        if not self.__display_string:
            self.__display_string = "%s:%d" % ( self.__host, self.__port )
        return self.__display_string

    @property
    def redis(self):
        """Returns the redis.client object for the given host/port
        Performing lazy initialization if it hasn't already been created
        """
        if not self.__redis:
            redis = Redis( host=self.__host, port=self.__port, password=self.__password, socket_timeout=self.__connection_timeout )
            self.__update_latest( redis )
            #__update_latest can raise an exception, so don't assign to self until it
            #completes successfully
            self.__redis = redis
        return self.__redis

class RedisMonitor(ScalyrMonitor):
    """
# Redis Monitor

A Scalyr agent monitor that imports the Redis SLOWLOG.

The Redis monitor queries the slowlog of a number of Redis servers, and uploads the logs
to the Scalyr servers.

@class=bg-warning docInfoPanel: An *agent monitor plugin* is a component of the Scalyr Agent. To use a plugin,
simply add it to the ``monitors`` section of the Scalyr Agent configuration file (``/etc/scalyr/agent.json``).
For more information, see [Agent Plugins](/help/scalyr-agent#plugins).


## Configuration

The following example will configure the agent to query a redis server located at localhost:6379 and that does not require
a password

    monitors: [
      {
        module:                    "scalyr_agent.builtin_monitors.redis_monitor",
      }
    ]

Additional configuration options are as follows:

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

    """
    def _initialize(self):
        """Performs monitor-specific initialization."""
        # The number of entries to request each pass
        self.__lines_to_fetch = self._config.get('lines_to_fetch', default=500, convert_to=int, min_value=10, max_value=5000)

        # The number of seconds to wait before redisplaying connection errors
        self.__connection_error_repeat_interval = self._config.get('connection_error_repeat_interval', default=300, convert_to=int, min_value=10, max_value=6000)

        # The number of seconds to wait when querying the redis server
        self.__connection_timeout = self._config.get('connection_timeout', default=5, convert_to=int, min_value=0, max_value=60)

        # The number of seconds to wait before reissuing warnings about invalid utf8 in slowlog messages.
        self.__utf8_warning_interval = self._config.get('utf8_warning_interval', default=600, convert_to=int, min_value=0, max_value=6000)

        # Redis-py requires None rather than 0 if no timeout
        if self.__connection_timeout == 0:
            self.__connection_timeout = None

        # A list of RedisHosts
        self.__redis_hosts = []

        hosts = self._config.get( 'hosts' )

        default_config = { "host" : "localhost", "port" : 6379, "password" : None }

        # add at least one host if none were specified
        if not hosts:
            hosts = [ default_config ]

        for host in hosts:
            #update the config, using default values for anything that was unspecified
            config = default_config.copy()
            config.update( host )

            #create a new redis host
            redis_host = RedisHost( config['host'], config['port'], config['password'], self.__connection_timeout ) 
            redis_host.utf8_warning_interval = self.__utf8_warning_interval
            self.__redis_hosts.append( redis_host )

    def gather_sample(self):

        for host in self.__redis_hosts:
            new_connection = not host.valid()
            try:
                entries = host.log_slowlog_entries( self._logger, self.__lines_to_fetch )
            except ConnectionError, e:
                if new_connection:
                    self._logger.error( "Unable to establish connection: %s" % ( host.display_string ), limit_once_per_x_secs=self.__connection_error_repeat_interval, limit_key=host.display_string )
                else:
                    self._logger.error( "Connection to redis lost: %s" % host.display_string )
            except TimeoutError, e:
                self._logger.warn( "Connection timed out: %s" % host.display_string )


