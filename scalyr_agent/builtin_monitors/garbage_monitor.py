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

import gc
import traceback

from scalyr_agent import ScalyrMonitor, define_config_option
from scalyr_agent.scalyr_monitor import BadMonitorConfiguration

import scalyr_agent.scalyr_logging as scalyr_logging
global_log = scalyr_logging.getLogger(__name__)

__monitor__ = __name__

define_config_option(__monitor__, 'module',
                     'Always ``scalyr_agent.builtin_monitors.garbage_monitor``',
                     convert_to=str, required_option=True)

define_config_option(__monitor__, 'disable_garbage_collection_before_dump',
                     'Optional (defaults to False). By default the garbage_monitor will perform a garbage collection before it '
                     'dumps the list of unreachable objects to ensure that objects are actually leaking.  If this flag is set to '
                     'True then then garbage monitor will not perform this collection.  This is useful when trying to find objects '
                     'with cyclic references that are not being readily collected by the garbage collector, but that would eventually '
                     'be collected.',
                     default=False, convert_to=bool)

define_config_option(__monitor__, 'max_type_dump',
                     'Optional (defaults to 20). The maximum number of unreachable types to output each gather_sample',
                     default=20, convert_to=int)

define_config_option(__monitor__, 'max_object_dump',
                     'Optional (defaults to 0). The maximum number of unreachable objects to dump for each type on the ``object_dump_types`` list. '
                     'Set to -1 to include all objects',
                     default=0, convert_to=int)

define_config_option(__monitor__, 'monitor_garbage_objects',
                     'Optional (defaults to True).  If False, garbage objects are not dumped.',
                     default=True, convert_to=bool)

define_config_option(__monitor__, 'monitor_live_objects',
                     'Optional (defaults to False).  If True, monitors live objects - i.e. those still in use and not read for garbage collection.',
                     default=False, convert_to=bool)

define_config_option(__monitor__, 'monitor_all_unreachable_objects',
                     'Optional (defaults to False).  If True, monitors all unreachable objects, not just ones that have circular __del__ dependencies. '
                     'See the python gc documentation for details: https://docs.python.org/2/library/gc.html#gc.garbage',
                     default=False, convert_to=bool)

define_config_option( __monitor__, 'object_dump_types',
                     'Optional.  A list of type names as strings.  For all types on this list, the garbage_monitor '
                     'will dump a string representation of unreachable objects of this type, up to ``max_object_dump`` objects. '
                     'The strings should match the type names printed out in the normal output of the garbage_monitor.'
                     )

class GarbageMonitor( ScalyrMonitor ):
    """
# GarbageMonitor

The garbage monitor outputs statistics returned by python's builtin garbage collection module.

@class=bg-warning docInfoPanel: An *agent monitor plugin* is a component of the Scalyr Agent. To use a plugin,
simply add it to the ``monitors`` section of the Scalyr Agent configuration file (``/etc/scalyr/agent.json``).
For more information, see [Agent Plugins](/help/scalyr-agent#plugins).

By default it outputs a list of types and a count of objects of that type that cannot be reclaimed
by the garbage collector.

It can also be configured to dump a string representation of unreachable objects of specific types.

## Sample Configuration

This sample will configure the garbage monitor to output the top 10 types with the most unreachable objects.

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.garbage_monitor",
        max_type_dump: 10
      }
    ]

This sample will configure the garbage monitor to output the top 10 types with the most unreachable objects,
along with dumping up to 20 objects of the types 'list' and 'dict'.

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.garbage_monitor",
        max_type_dump: 10,
        object_dump_types: [ "list", "dict" ],
        max_object_dump: 20
      }
    ]
    """

    def _initialize( self ):
        
        # validate the list of types to dump objects for
        object_dump_types = self._config.get( 'object_dump_types' )

        if object_dump_types is None:
            object_dump_types = []

        for t in object_dump_types:
            if not isinstance( t, basestring ):
                raise BadMonitorConfiguration( "object_dump_types contains a non-string value: %s" % str( t ) )

        # and convert the JsonArray to a python list
        self._object_dump_types = [t for t in object_dump_types]

        # original debug flags of the gc
        self._old_debug_flags = None

        self._monitor_all_unreachable = self._config.get( 'monitor_all_unreachable_objects' )

        self._max_type_dump = self._config.get( 'max_type_dump' )
        self._max_object_dump = self._config.get( 'max_object_dump' )
        self._monitor_garbage = self._config.get( 'monitor_garbage_objects' )
        self._monitor_live = self._config.get( 'monitor_live_objects' )

    def run( self ):
        # get the current debug flags
        self._old_debug_flags = gc.get_debug()

        if self._monitor_all_unreachable:
            # and set the new ones we are interested in
            gc.set_debug( gc.DEBUG_SAVEALL )

        # Output some log information here so we can tell from the logs when the garbage monitor has been reloaded
        self._logger.info( "Starting garbage monitor. Outputting max %d types" % self._max_type_dump )
        if len( self._object_dump_types ):
            self._logger.info( "\tDumping %d objects of type(s) %s" % (self._max_object_dump, str( self._object_dump_types ) ) )
        else:
            self._logger.info( "\tNot dumping individual objects." )
            
        ScalyrMonitor.run( self )

    def _dump_string( self, rubbish ):
        if hasattr(rubbish, '__name__'):
            if rubbish.__name__ == "function":
                return rubbish.__name__
            return str( rubbish )
        else:
            return str( rubbish )

    def _dump_objects( self, all_objects, object_dump_types, max_type_dump, max_object_dump, dump_kind  ):
        self._logger.info( "*** Garbage Detector *** %d %s objects found" % (len( all_objects ), dump_kind) )

        # get the names and object counts of objects
        type_count = {}
        for item in all_objects:
            object_type = type( item ).__name__
            if object_type not in type_count:
                type_count[object_type] = []
            type_count[object_type].append( item )

        # get the top objects, sorted by descending object count
        sorted_objects = sorted( type_count.items(), key=lambda (k,v):len(v), reverse=True)[:max_type_dump]

        #print the overview
        for type_name, object_list in sorted_objects:
            self._logger.info( "\t\t%s=%d" % (type_name, len(object_list)) )

        #print the objects
        if object_dump_types:
            for type_name, object_list in sorted_objects:
                if type_name in object_dump_types:
                    objects = object_list
                    if max_object_dump > 0:
                        objects = objects[:max_object_dump]

                    if max_object_dump == 0:
                        self._logger.info( "No objects to print for '%s'- set `max_object_dump` to a value > 0" % type_name )
                    else:
                        self._logger.info( "Objects for %s" % (type_name))
                        for r in object_list[:max_object_dump]:
                            self._logger.info( "\t\t%s" % (self._dump_string(r)) )

    def gather_sample( self ):
        try:
            # collect everything that can be collected
            if not self._config.get('disable_garbage_collection_before_dump'):
                gc.collect()

            # dump garbage objects
            if self._monitor_garbage:
                garbage = gc.garbage
                self._dump_objects( all_objects=garbage,
                                    object_dump_types=self._object_dump_types,
                                    max_type_dump=self._max_type_dump,
                                    max_object_dump=self._max_object_dump,
                                    dump_kind="garbage"
                                  )

            # dump live objects
            if self._monitor_live:
                objects = gc.get_objects()
                self._dump_objects( all_objects=objects,
                                    object_dump_types=self._object_dump_types,
                                    max_type_dump=self._max_type_dump,
                                    max_object_dump=self._max_object_dump,
                                    dump_kind="live"
                                  )

        except Exception, e:
            global_log.info( "error gathering sample %s", traceback.format_exc() )

    def stop(self, wait_on_join=True, join_timeout=5):

        # output some info so we can tell from the logs when the monitor is being shut down
        self._logger.info( "Garbage Monitor shutting down" )

        #restore the original debug flags
        if self._monitor_all_unreachable and self._old_debug_flags is not None:
            gc.set_debug( self._old_debug_flags )

        #stop the main server
        ScalyrMonitor.stop( self, wait_on_join=wait_on_join, join_timeout=join_timeout )

