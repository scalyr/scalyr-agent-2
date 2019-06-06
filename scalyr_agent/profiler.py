# Copyright 2018 Scalyr Inc.
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
# author:  Imron Alston <imron@scalyr.com>

__author__ = 'imron@scalyr.com'

import errno
import os
import random
from scalyr_agent.json_lib import JsonObject
import scalyr_agent.scalyr_logging as scalyr_logging
import time
import traceback

try:
    import yappi
except ImportError:
    yappi = None

global_log = scalyr_logging.getLogger(__name__)

class Profiler( object ):
    """
        Profiles the agent
    """

    def __init__( self, config ):

        enable_profiling = config.enable_profiling

        if enable_profiling:
            if yappi is None:
                global_log.warning( "Profiling is enabled, but the `yappi` module couldn't be loaded. "
                                    "You need to install `yappi` in order to use profiling.  This can be done "
                                    "via pip:  pip install yappi" )

        self._is_enabled = False
        self._allowed_clocks = [ 'wall', 'cpu', 'random' ]
        self._profile_clock = self._get_clock_type( config.profile_clock, self._allowed_clocks, config.profile_clock )

        # random is only allowed during initialization, and not via config file changes to
        # ensure the random clock is consistent for the life of the agent.
        # random clocks can still be manually overridden in the agent.json
        self._allowed_clocks = self._allowed_clocks[:2]

        self._profile_start = 0
        self._profile_end = 0

    def _get_clock_type( self, clock_type, allowed, default_value ):
        """
            gets the clock type.  If clock type is `random` then
            randomly choose from the first 2 elements of the `allowed` array.
        """
        result = default_value
        if clock_type in allowed:
            result = clock_type

        if result == 'random':
            r = random.randint( 0, 1 )
            result = allowed[r]

        return result

    def _get_random_start_time( self, current_time, maximum_interval_minutes ):
        if maximum_interval_minutes < 1:
            maximum_interval_minutes = 1
        r = random.randint( 1, maximum_interval_minutes ) * 60
        return current_time + r

    def _update_start_interval( self, config, current_time ):
        self._profile_start = self._get_random_start_time( current_time, config.max_profile_interval_minutes )
        self._profile_end = self._profile_start + (config.profile_duration_minutes * 60)

    def _start( self, config, current_time ):

        yappi.clear_stats()
        clock = self._get_clock_type( config.profile_clock, self._allowed_clocks, self._profile_clock )
        if clock != self._profile_clock:
            self._profile_clock = clock
            yappi.set_clock_type( self._profile_clock )
        global_log.log( scalyr_logging.DEBUG_LEVEL_0, "Starting profiling using '%s' clock. Duration: %d seconds" % (self._profile_clock, self._profile_end - self._profile_start) )
        yappi.start()

    def _stop( self, config, current_time ):
        yappi.stop()
        global_log.log( scalyr_logging.DEBUG_LEVEL_0, 'Stopping profiling' )
        stats = yappi.get_func_stats()
        path = os.path.join( config.agent_log_path, config.profile_log_name )
        if os.path.exists( path ):
            os.remove( path )
        stats.save( path, 'callgrind' )

        lines = 0

        # count the lines
        f = open(path)
        try:
            for line in f:
                lines += 1
        finally:
            f.close()

        # write a status message to make it easy to find the end of each profile session
        f = open( path, "a" )
        try:
            f.write( "\n# %s, %s clock, total lines: %d\n" % (path, self._profile_clock, lines) )
        finally:
            f.close()

        yappi.clear_stats()
        del stats

    def update( self, config, current_time=None ):
        """
            Updates the state of the profiler - either enabling or disabling it, based on
            the current time and whether or not the current profiling interval has started/stopped
        """
        # no profiling if the profiler isn't available
        if yappi is None:
            return

        if current_time is None:
            current_time = time.time()

        try:
            # check if profiling is enabled in the config and turn it on/off if necessary
            if config.enable_profiling:
                if not self._is_enabled:
                    self._update_start_interval( config, current_time )
                    self._is_enabled = True
            else:
                if yappi.is_running():
                    self._stop( config, current_time )
                self._is_enabled = False

            # only do profiling if we are still enabled
            if not self._is_enabled:
                return

            # check if the current profiling interval needs to start or stop
            if yappi.is_running():
                if current_time > self._profile_end:
                    self._stop( config, current_time )
                    self._update_start_interval( config, current_time )

            else:
                if current_time > self._profile_start:
                    self._start( config, current_time )
        except Exception, e:
            global_log.log( scalyr_logging.DEBUG_LEVEL_0, 'Failed to update profiler: %s, %s' % (str(e), traceback.format_exc() ),
                            limit_once_per_x_secs=300,
                            limit_key='profiler-update')

