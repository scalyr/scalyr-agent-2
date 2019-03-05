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

from scalyr_agent.monitor_utils.k8s import KubernetesApi, K8sApiException, KubernetesCache
import scalyr_agent.monitor_utils.annotation_config as annotation_config

from scalyr_agent.third_party.requests.exceptions import ConnectionError

import datetime
import re
import traceback
import time
import urllib

import logging
import logging.handlers

from scalyr_agent import ScalyrMonitor, define_config_option, AutoFlushingRotatingFileHandler
from scalyr_agent.log_watcher import LogWatcher
from scalyr_agent.scalyr_logging import DEBUG_LEVEL_0, DEBUG_LEVEL_1, DEBUG_LEVEL_2
from scalyr_agent.scalyr_logging import DEBUG_LEVEL_3, DEBUG_LEVEL_4, DEBUG_LEVEL_5
from scalyr_agent.monitor_utils.auto_flushing_rotating_file import AutoFlushingRotatingFile
from scalyr_agent.util import StoppableThread
import scalyr_agent.json_lib as json_lib
import scalyr_agent.util as scalyr_util
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
                     'Optional (defaults to [ \'CronJob\', \'DaemonSet\', \'Deployment\', \'Job\', \'Node\', \'Pod\', \'ReplicaSet\', \'ReplicationController\', \'StatefulSet\' ] ). A list of event object types to filter on. '
                     'If set, only events whose `involvedObject` `kind` is on this list will be included.',
                     default=[ 'CronJob', 'DaemonSet', 'Deployment', 'Job', 'Node', 'Pod', 'ReplicaSet', 'ReplicationController', 'StatefulSet' ]
                     )

define_config_option( __monitor__, 'k8s_cache_expiry_secs',
                     'Optional (defaults to 30). The amount of time to wait between fully updating the k8s cache from the k8s api. '
                     'Increase this value if you want less network traffic from querying the k8s api.  Decrease this value if you '
                     'want dynamic updates to annotation configuration values to be processed more quickly.',
                     convert_to=int, default=30)

define_config_option( __monitor__, 'k8s_cache_purge_secs',
                     'Optional (defaults to 300). The number of seconds to wait before purging unused items from the k8s cache',
                     convert_to=int, default=300)

define_config_option( __monitor__, 'k8s_ignore_namespaces',
                      'Optional (defaults to "kube-system"). A comma-delimited list of the namespaces whose pods\'s '
                      'logs should not be collected and sent to Scalyr.', convert_to=str, default="kube-system")

define_config_option( __monitor__, 'leader_check_interval',
                     'Optional (defaults to 60). The number of seconds to check to see if we are still the leader.',
                     convert_to=int, default=60)

define_config_option( __monitor__, 'leader_node',
                     'Optional (defaults to None). Force the `leader` to be the scalyr-agent that runs on this node.',
                     convert_to=str, default=None)

define_config_option( __monitor__, 'check_labels',
                     'Optional (defaults to False). If true, then the monitor will check for any nodes with the label '
                     '`agent.config.scalyr.com/events_leader=true` and the node with this label set and that has the oldest'
                     'creation time will be the event monitor leader.',
                     convert_to=bool, default=False)

define_config_option( __monitor__, 'ignore_master',
                     'Optional (defaults to True). If true, then the monitor will ignore any nodes with the label '
                     '`node-role.kubernetes.io/master` when determining which node is the event monitor leader.',
                     convert_to=bool, default=True)

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

        #configure the logger and path
        self.__message_log = self._config.get( 'message_log' )

        self.log_config = {
            'parser': self._config.get( 'parser' ),
            'path': self.__message_log,
        }

        self._leader_check_interval = self._config.get( 'leader_check_interval' )
        self._leader_node = self._config.get( 'leader_node' )
        self._check_labels = self._config.get( 'check_labels' )
        self._ignore_master = self._config.get( 'ignore_master' )

        self._current_leader = self._leader_node

        self.__flush_delay = self._config.get('log_flush_delay')
        try:
            attributes = JsonObject( { "monitor": "json" } )
            self.log_config['attributes'] = attributes
        except Exception, e:
            global_log.error( "Error setting monitor attribute in KubernetesEventMonitor" )

        self.__k8s_cache_expiry_secs = self._config.get( 'k8s_cache_expiry_secs' )
        self.__k8s_cache_purge_secs = self._config.get( 'k8s_cache_purge_secs' )

        # The namespace whose logs we should not collect.
        self.__k8s_namespaces_to_ignore = []
        for x in self._config.get('k8s_ignore_namespaces').split():
            self.__k8s_namespaces_to_ignore.append(x.strip())

        default_rotation_count, default_max_bytes = self._get_log_rotation_configuration()

        self.__event_object_filter = self._config.get( 'event_object_filter', [  'CronJob', 'DaemonSet', 'Deployment', 'Job', 'Node', 'Pod', 'ReplicaSet', 'ReplicationController', 'StatefulSet' ] )

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

    def _check_if_alive( self, k8s, node ):
        """
            Checks to see if the node specified by `node` is alive
        """
        if node is None:
            return False

        result = {}
        try:
            # this call will throw an exception on failure
            result = k8s.query_api( '/api/v1/nodes/%s' % node )
        except Exception, e:
            return False

        # if we are here, then the above node exists so return True
        return True

    def _get_oldest_node( self, nodes, ignore_master ):
        """
            Takes a list of nodes returned from querying the k8s api, and returns the name
            of the node with the oldest creationTimestamp or None if nodes is empty or doesn't
            contain Node objects.

            if `ignore_master` is true, then any nodes with the label `node-role.kubernetes.io/master` are ignored.
        """

        oldest_time = datetime.datetime.utcnow()
        oldest = None

        # loop over all nodes and find the one with the oldest create time
        for node in nodes:
            metadata = node.get( 'metadata', {} )
            create_time = metadata.get( 'creationTimestamp', None )
            if create_time is None:
                continue

            name = metadata.get( 'name', None )
            if name is None:
                continue

            # skip the master node if necessary
            labels = metadata.get( 'labels', {} )
            if ignore_master and 'node-role.kubernetes.io/master' in labels:
                continue

            #convert to datetime
            create_time = scalyr_util.rfc3339_to_datetime( create_time )

            # if we are older than the previous oldest datetime, then update the oldest time
            if create_time is not None and create_time < oldest_time:
                oldest_time = create_time
                oldest = name

        return oldest

    def _check_nodes_for_leader( self, k8s, query_fields='' ):
        """
            Checks all nodes on the cluster to see which one has the oldest creationTime
            If `ignore_master` is True then any node with the label `node-role.kubernetes.io/master`
            is ignored.
        """
        response = k8s.query_api( '/api/v1/nodes%s' % query_fields )
        nodes = response.get( 'items', [] )

        # sort the list by node name to ensure consistent processing order
        # if two nodes have exactly the same creation time
        nodes.sort( key=lambda n: n.get( 'metadata', {} ).get( 'name', '' ) )

        # the leader is the longest running node
        return self._get_oldest_node( nodes, self._ignore_master )

    def _get_current_leader( self, k8s ):
        """
            Queries the kubernetes api to see which node is the current leader node.

            If there is currently a leader node, then only that node is polled to see if it still
            exists.

            Check to see if the leader is specified as a node label.
            If not, then if there is not a current leader node, or if the current leader node no longer exists
            then query all nodes for the leader
        """

        try:
            leader = None
            # first check to see if the leader node is specified as a label
            # we do this first in case the label has been moved to a different node but the old node is still
            # alive
            if self._check_labels:
                query = "?labelSelector=%s" % (urllib.quote( 'agent.config.scalyr.com/events_leader=true' ) )
                leader = self._check_nodes_for_leader( k8s, query )

            # if no labelled leader was found, then check to see if the previous leader is still alive
            if leader is None:
                if self._check_if_alive( k8s, self._current_leader ):
                    # still the same leader
                    global_log.log( scalyr_logging.DEBUG_LEVEL_0, "New leader same as the old leader" )
                    leader = self._current_leader
                else:
                    # previous leader is not alive so check all nodes for the leader
                    global_log.log( scalyr_logging.DEBUG_LEVEL_0, "Checking for a new leader" )
                    leader = self._check_nodes_for_leader( k8s )
            else:
                global_log.log( scalyr_logging.DEBUG_LEVEL_0, "Leader set from label" )

            # update the global leader (leader can be None)
            self._current_leader = leader

        except K8sApiException, e:
            global_log.error( "get current leader: %s, %s" %( str(e), traceback.format_exc() ) )

        return self._current_leader


    def _is_leader(self, k8s):
        """
        Detects if this agent is the `leader` for events in a cluster.  In order to prevent duplicates, only `leader` agents will log events.
        """
        if self._node_name is None:
            return False

        # see if we have a fixed leader node specified
        leader = self._leader_node

        try:
            # if not then query the k8s api for the leader
            if leader is None:
                leader = self._get_current_leader( k8s )

            # check if this node is the current leader node
        except Exception, e:
            global_log.log( scalyr_logging.DEBUG_LEVEL_0, "Unexpected error checking for leader: %s" % (str(e)))

        return leader is not None and self._node_name == leader

    def run(self):
        """Begins executing the monitor, writing metric output to logger.
        """
        try:
            k8s = KubernetesApi()

            # create the k8s cache
            k8s_cache = KubernetesCache( k8s, self._logger,
                cache_expiry_secs=self.__k8s_cache_expiry_secs,
                cache_purge_secs=self.__k8s_cache_purge_secs,
                namespaces_to_ignore=self.__k8s_namespaces_to_ignore
                )

            if self.__log_watcher:
                self.log_config = self.__log_watcher.add_log_config( self, self.log_config )

            pod_name = k8s.get_pod_name()
            self._node_name = k8s.get_node_name( pod_name )
            cluster_name = k8s.get_cluster_name()

            last_event = None
            last_resource = 0

            last_check = time.time() - self._leader_check_interval

            while not self._is_stopped():
                current_time = time.time()

                # if we are the leader, we could be going through this loop before the leader_check_interval
                # has expired, so make sure to only check for a new leader if the interval has expired
                if last_check + self._leader_check_interval <= current_time:
                    last_check = current_time
                    # check if we are the leader
                    if not self._is_leader( k8s ):
                        #if not, then sleep and try again
                        global_log.log( scalyr_logging.DEBUG_LEVEL_0, "Leader is %s" % (str(self._current_leader)) )
                        self._sleep_but_awaken_if_stopped(self._leader_check_interval)
                        continue

                    global_log.log( scalyr_logging.DEBUG_LEVEL_0, "Leader is %s" % (str(self._current_leader)) )
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
                                global_log.log( scalyr_logging.DEBUG_LEVEL_1, "K8S resource expired" )
                                continue

                        # resource version hasn't expired, so update it to the most recently seen version
                        last_event = last_resource

                        metadata = obj.get( "metadata", JsonObject() )

                        # skip any events with resourceVersions higher than ones we've already seen
                        resource_version = metadata.get_int( "resourceVersion", None, none_if_missing=True )
                        if resource_version and resource_version <= last_resource:
                            global_log.log( scalyr_logging.DEBUG_LEVEL_2, "Skipping older resource events" )
                            continue

                        last_resource = resource_version
                        last_event = resource_version

                        # see if this event is about an object we are interested in
                        involved = obj.get( "involvedObject", JsonObject())
                        kind = involved.get( 'kind', None, none_if_missing=True )
                        if kind and kind not in self.__event_object_filter:
                            global_log.log( scalyr_logging.DEBUG_LEVEL_1, "Ignoring event due to unknown kind %s - %s" % (kind, str(metadata) ) )
                            continue

                        # get cluster and deployment information
                        k8s_fields = "cluster-name=%s" % cluster_name
                        if kind:
                            name = involved.get( 'name', None, none_if_missing=True )
                            namespace = involved.get( 'namespace', None, none_if_missing=True )

                            if kind == 'Pod':
                                pod = k8s_cache.pod( namespace, name, current_time )
                                if pod and pod.controller:
                                    k8s_fields += " deployment-name=%s" % pod.controller.name
                            elif kind == 'Node':
                                pass # don't add deployment info for node events
                            else:
                                controller = k8s_cache.controller( namespace, name, kind, current_time )
                                if controller:
                                    k8s_fields += " deployment-name=%s" % controller.name

                        # if so, log to disk
                        self.__disk_logger.info( "%s %s" % (k8s_fields, str( line )) )

                        # see if we need to check for a new leader
                        if last_check + self._leader_check_interval <= current_time:
                            global_log.log( scalyr_logging.DEBUG_LEVEL_1, "Time to check for a new event leader" )
                            continue
                    
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

