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

import time

from scalyr_agent import ScalyrMonitor

from redis.client import Redis
from redis.exceptions import ConnectionError


class RedisHost( object ):
    """Class that holds various information about a specific redis connection
    """
    def __init__( self, host, port, password ):
        #redis instance information
        self.__host = host
        self.__port = port
        self.__password = password

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


        # String for display purposes
        self.__display_string = ""


    def valid( self ):
        """Check if we are currently connected to a redis instance"""
        return self.__redis != None

    def __update_latest( self ):
        """Get the most recent entry in the slow log and store its ID.

        If it's the first connection for this RedisHost just get the
        latest entry in the slowlog, otherwise ignore because we will have
        previous values for the last_id and timestamp.
        """
        if self.__redis and self.__first_connection:
            self.__first_connection = False
            latest = self.__redis.slowlog_get( 1 )
            if latest:
                self.last_id = latest[0]['id']
                self.last_timestamp = latest[0]['start_time']


    def reset_connection( self ):
        """Called when the connection is reset
        """
        self.__reset = True
        self.__redis = None

    def log_slowlog_entries( self, logger, lines_to_fetch ):
        """Fetch entries from the redis slowlog and emit them to Scalyr
        if they pass a predicate test - which will either be on the id
        or the timestamp, depending on whether or not the connection
        has been reset in between calls to this function
        """

        # fetch the entries
        entries = self.redis.slowlog_get( lines_to_fetch )

        # by default use the id based predicate to get the entries
        key = 'id'
        value = self.last_id

        # if our connection was reset since the last time we checked the slowlog then
        # get entries based on timestamp instead, because the server might have been restarted
        # which will invalidate any previous ids
        if self.__reset:
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
            logger.warn( "Too many log messages since last query.  Some log lines may have been dropped" )

        # print it out in reverse because redis sends entries in reverse order
        for entry in reversed( unseen_entries ):
            self.log_entry( logger, entry )


    def log_entry( self, logger, entry ):

        time_format = "%Y-%m-%d %H:%M:%SZ"
        logger.emit_value( 'host', self.display_string, extra_fields={
            'ts': time.strftime( time_format, time.gmtime( entry['start_time'] ) ),
            'exectime' : entry['duration'],
            'command' : entry['command']
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
            self.__redis = Redis( host=self.__host, port=self.__port, password=self.__password )
            self.__update_latest()
        return self.__redis

class RedisMonitor(ScalyrMonitor):
    """A Scalyr agent monitor that imports the Redis SLOWLOG.
    """
    def _initialize(self):
        """Performs monitor-specific initialization."""
        # The number of entries to request each pass
        self.__lines_to_fetch = self._config.get('lines_to_fetch', default=500, convert_to=int, min_value=10, max_value=5000)

        # The number of seconds to wait before redisplaying connection errors
        self.__connection_error_repeat_interval = self._config.get('connection_error_repeat_interval', default=300, convert_to=int, min_value=10, max_value=6000)

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
            self.__redis_hosts.append( RedisHost( config['host'], config['port'], config['password'] ) )

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

                host.reset_connection()


