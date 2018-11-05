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

from scalyr_agent.monitor_utils.k8s import KubernetesApi
import scalyr_agent.monitor_utils.annotation_config as annotation_config

from scalyr_agent.third_party.requests.exceptions import ConnectionError

import re
import traceback

import logging
import logging.handlers

from scalyr_agent import ScalyrMonitor, define_config_option, AutoFlushingRotatingFileHandler
from scalyr_agent.log_watcher import LogWatcher
from scalyr_agent.scalyr_logging import DEBUG_LEVEL_0, DEBUG_LEVEL_1, DEBUG_LEVEL_2
from scalyr_agent.scalyr_logging import DEBUG_LEVEL_3, DEBUG_LEVEL_4, DEBUG_LEVEL_5
from scalyr_agent.monitor_utils.auto_flushing_rotating_file import AutoFlushingRotatingFile
from scalyr_agent.util import StoppableThread
import scalyr_agent.json_lib as json_lib
from scalyr_agent.json_lib import JsonObject

import scalyr_agent.scalyr_logging as scalyr_logging
global_log = scalyr_logging.getLogger(__name__)

SCALYR_CONFIG_ANNOTATION_RE = re.compile( '^(agent\.config\.scalyr\.com/)(.+)' )

__monitor__ = __name__

define_config_option(__monitor__, 'module',
                     'Always ``scalyr_agent.builtin_monitors.kubernetes_events_monitor``',
                     convert_to=str, required_option=True)

define_config_option( __monitor__, 'max_log_size',
                     'Optional (defaults to None). How large the log file will grow before it is rotated. If None, then the '
                     'default value will be taken from the monitor level or the global level log_rotation_max_bytes config option.  Set to zero '
                     'for infinite size. Note that rotation is not visible in Scalyr; it is only relevant for managing '
                     'disk space on the host running the agent. However, a very small limit could cause logs to be '
                     'dropped if there is a temporary network outage and the log overflows before it can be sent to '
                     'Scalyr',
                     convert_to=int, default=None)

define_config_option( __monitor__, 'max_log_rotations',
                     'Optional (defaults to None). The maximum number of log rotations before older log files are '
                     'deleted. If None, then the value is taken from the monitor level or the global level log_rotation_backup_count option. '
                     'Set to zero for infinite rotations.',
                     convert_to=int, default=None)

define_config_option( __monitor__, 'log_flush_delay',
                     'Optional (defaults to 1.0). The time to wait in seconds between flushing the log file containing '
                     'the kubernetes event messages.',
                     convert_to=float, default=1.0)

define_config_option( __monitor__, 'message_log',
                     'Optional (defaults to ``kubernetes_events.log``). Specifies the file name under which event messages '
                     'are stored. The file will be placed in the default Scalyr log directory, unless it is an '
                     'absolute path',
                     convert_to=str, default='kubernetes_events.log')

define_config_option( __monitor__, 'event_object_filter',
                     'Optional (defaults to [\'Pod\', \'Deployment\', \'DaemonSet\', \'Node\', \'ReplicaSet\'] ). A list of event object types to filter on. '
                     'If set, only events whose `regarding` object `kind` is on this list will be included.',
                     default=['Pod', 'Deployment', 'DaemonSet', 'Node', 'ReplicaSet']
                     )

define_config_option( __monitor__, 'leader_check_interval',
                     'Optional (defaults to 60). The number of seconds to check to see if we are still the leader.',
                     convert_to=int, default=60)

class KubernetesEventsMonitor( ScalyrMonitor ):
    """
# Kubernetes Events Monitor

The Kuberntes Events monitor streams Kubernetes events from the Kubernetes API

    """

    def _initialize( self ):

        #our disk logger and handler
        self.__disk_logger = None
        self.__log_handler = None

        self.__log_watcher = None
        self.__module = None

        self._node_name = None
        self._pod_name = None

        #configure the logger and path
        self.__message_log = self._config.get( 'message_log' )

        self.log_config = {
            'parser': self._config.get( 'parser' ),
            'path': self.__message_log,
        }

        self._leader_check_interval = self._config.get( 'leader_check_interval' )

        self.__flush_delay = self._config.get('log_flush_delay')
        try:
            attributes = JsonObject( { "monitor": "json" } )
            self.log_config['attributes'] = attributes
        except Exception, e:
            global_log.error( "Error setting monitor attribute in KubernetesEventMonitor" )

        default_rotation_count, default_max_bytes = self._get_log_rotation_configuration()

        self.__event_object_filter = self._config.get( 'event_object_filter', [ 'Pod', 'Deployment', 'DaemonSet', 'Node', 'ReplicaSet' ] )

        self.__max_log_size = self._config.get( 'max_log_size' )
        if self.__max_log_size is None:
            self.__max_log_size = default_max_bytes

        self.__max_log_rotations = self._config.get( 'max_log_rotations' )
        if self.__max_log_rotations is None:
            self.__max_log_rotations = default_rotation_count


    def open_metric_log( self ):
        """Override open_metric_log to prevent a metric log from being created for the Kubernetes Events Monitor
        and instead create our own logger which will log raw messages out to disk.
        """
        self.__disk_logger = logging.getLogger( self.__message_log )

        #assume successful for when the logger handler has already been created
        success = True

        #only configure once -- assumes all configuration happens on the same thread
        if len( self.__disk_logger.handlers ) == 0:
            #logger handler hasn't been created yet, so assume unsuccssful
            success = False
            try:
                self.__log_handler = AutoFlushingRotatingFileHandler( filename = self.log_config['path'],
                                                                      maxBytes = self.__max_log_size,
                                                                      backupCount = self.__max_log_rotations,
                                                                      flushDelay = self.__flush_delay)

                formatter = logging.Formatter()
                self.__log_handler.setFormatter( formatter )
                self.__disk_logger.addHandler( self.__log_handler )
                self.__disk_logger.setLevel( logging.INFO )
                self.__disk_logger.propagate = False
                success = True
            except Exception, e:
                global_log.error( "Unable to open KubernetesEventsMonitor log file: %s" % str( e ) )

        return success

    def close_metric_log( self ):
        if self.__log_handler:
            self.__disk_logger.removeHandler( self.__log_handler )
            self.__log_handler.close()

    def set_log_watcher( self, log_watcher ):
        self.__log_watcher = log_watcher

    def _is_leader(self, k8s):
        """
        Detects if this agent is the `leader` for events in a cluster.  In order to prevent duplicates, only `leader` agents will log events.
        """
        if self._pod_name is None:
            return False

        result = k8s.query_pod( k8s.namespace, self._pod_name )
        if result is None:
            return False

        metadata = result.get( 'metadata', {} )
        annotations = metadata.get( 'annotations', {} )

        try:
            annotations = annotation_config.process_annotations( annotations, annotation_prefix_re=SCALYR_CONFIG_ANNOTATION_RE )
        except BadAnnotationConfig, e:
            self._logger.warning( "Bad Annotation config for %s/%s.  All annotations ignored. %s" % (k8s.namespace, self._pod_name, str( e )),
                                  limit_once_per_x_secs=300, limit_key='bad-annotation-config-%s/%s' % (k8s.namespace, self._pod_name) )
            annotations = JsonObject()

        result = True
        try:
            result = annotations.get_bool( 'is_leader', False )
        except Exception, e:
            result = False
    
        return result

    def run(self):
        """Begins executing the monitor, writing metric output to logger.
        """
        k8s = KubernetesApi()

        if self.__log_watcher:
            self.log_config = self.__log_watcher.add_log_config( self, self.log_config )

        self._pod_name = k8s.get_pod_name()
        try:
            last_event = None
            last_resource = 0
            while not self._is_stopped():
                if not self._is_leader( k8s ):
                    self._sleep_but_awaken_if_stopped(self._leader_check_interval)
                    continue

                try:
                    # start streaming events
                    lines = k8s.stream_events( last_event=last_event )

                    json = {}
                    for line in lines:
                        try:
                            json = json_lib.parse(line)
                        except Exception, e:
                            global_log.warning( "Error parsing event json: %s, %s, %s" % (line, str(e), traceback.format_exc() ) )
                            continue

                        obj = json.get( "object", JsonObject() )

                        # check to see if the resource version we are using has expired
                        if json.get( 'type', '' ) == 'ERROR':
                            if obj.get( 'kind', '' ) == 'Status' and obj.get( 'reason', '' ) == 'Expired':
                                # if so, reset to None to get all events, we'll skip over the already seen
                                # ones later
                                last_event = None
                                continue

                        # resource version hasn't expired, so update it to the most recently seen version
                        last_event = last_resource

                        metadata = obj.get( "metadata", JsonObject() )

                        # skip any events with resourceVersions higher than ones we've already seen
                        resource_version = metadata.get_int( "resourceVersion", None, none_if_missing=True )
                        if resource_version and resource_version <= last_resource:
                            continue

                        last_resource = resource_version
                        last_event = resource_version

                        # see if this event is about an object we are interested in
                        regarding = obj.get( "regarding", JsonObject())
                        kind = regarding.get( 'kind', None, none_if_missing=True )
                        if kind and kind not in self.__event_object_filter:
                            continue

                        # if so, log to disk
                        self.__disk_logger.info( "%s" % str( line ) )
                    
                except ConnectionError, e:
                    # ignore these, and just carry on querying in the next iteration
                    pass
                except Exception, e:
                    global_log.exception('Failed to stream k8s events due to the following exception: %s, %s, %s' % (repr(e), str(e), traceback.format_exc() ) )

        except Exception:
            # TODO:  Maybe remove this catch here and let the higher layer catch it.  However, we do not
            # right now join on the monitor threads, so no one would catch it.  We should change that.
            global_log.exception('Monitor died from due to exception:', error_code='failedMonitor')

    def stop(self, wait_on_join=True, join_timeout=5):

        #stop the main server
        ScalyrMonitor.stop( self, wait_on_join=wait_on_join, join_timeout=join_timeout )

