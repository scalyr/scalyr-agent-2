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
import scalyr_agent.json_lib.objects

__author__ = 'imron@scalyr.com'

from scalyr_agent.monitor_utils.k8s import KubernetesApi, K8sApiException, K8sApiAuthorizationException
import scalyr_agent.monitor_utils.k8s as k8s_utils

from scalyr_agent.third_party.requests.exceptions import ConnectionError

import datetime
import os
import re
import traceback
import time
import urllib

import logging
import logging.handlers

from scalyr_agent import ScalyrMonitor, define_config_option, AutoFlushingRotatingFileHandler
from scalyr_agent.scalyr_logging import BaseFormatter
import scalyr_agent.json_lib as json_lib
from scalyr_agent.json_lib.objects import ArrayOfStrings
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
                     convert_to=int, default=None, env_name='SCALYR_K8S_MAX_LOG_SIZE')

define_config_option( __monitor__, 'max_log_rotations',
                     'Optional (defaults to None). The maximum number of log rotations before older log files are '
                     'deleted. If None, then the value is taken from the monitor level or the global level log_rotation_backup_count option. '
                     'Set to zero for infinite rotations.',
                     convert_to=int, default=None, env_name='SCALYR_K8S_MAX_LOG_ROTATIONS')

define_config_option( __monitor__, 'log_flush_delay',
                     'Optional (defaults to 1.0). The time to wait in seconds between flushing the log file containing '
                     'the kubernetes event messages.',
                     convert_to=float, default=1.0, env_name='SCALYR_K8S_LOG_FLUSH_DELAY')

define_config_option( __monitor__, 'message_log',
                     'Optional (defaults to ``kubernetes_events.log``). Specifies the file name under which event messages '
                     'are stored. The file will be placed in the default Scalyr log directory, unless it is an '
                     'absolute path',
                     convert_to=str, default='kubernetes_events.log', env_name='SCALYR_K8S_MESSAGE_LOG')

EVENT_OBJECT_FILTER_DEFAULTS = [
    'CronJob', 'DaemonSet', 'Deployment', 'Job', 'Node', 'Pod', 'ReplicaSet', 'ReplicationController', 'StatefulSet'
]
define_config_option(__monitor__, 'event_object_filter',
                     'Optional (defaults to %s). A list of event object types to filter on. '
                     'If set, only events whose `involvedObject` `kind` is on this list will be included.'
                     % str(EVENT_OBJECT_FILTER_DEFAULTS),
                     convert_to=ArrayOfStrings, default=EVENT_OBJECT_FILTER_DEFAULTS, env_name='SCALYR_K8S_EVENT_OBJECT_FILTER')

define_config_option( __monitor__, 'leader_check_interval',
                     'Optional (defaults to 60). The number of seconds to wait between checks to see if we are still the leader.',
                     convert_to=int, default=60, env_name='SCALYR_K8S_LEADER_CHECK_INTERVAL')

define_config_option( __monitor__, 'leader_node',
                     'Optional (defaults to None). Force the `leader` to be the scalyr-agent that runs on this node.',
                     convert_to=str, default=None, env_name='SCALYR_K8S_LEADER_NODE')

define_config_option( __monitor__, 'check_labels',
                     'Optional (defaults to False). If true, then the monitor will check for any nodes with the label '
                     '`agent.config.scalyr.com/events_leader_candidate=true` and the node with this label set and that has the oldest'
                     'creation time will be the event monitor leader.',
                     convert_to=bool, default=False, env_name='SCALYR_K8S_CHECK_LABELS')

define_config_option( __monitor__, 'ignore_master',
                     'Optional (defaults to True). If true, then the monitor will ignore any nodes with the label '
                     '`node-role.kubernetes.io/master` when determining which node is the event monitor leader.',
                     convert_to=bool, default=True, env_name='SCALYR_K8S_IGNORE_MASTER')

class EventLogFormatter(BaseFormatter):
    """Formatter used for the logs produced by the event monitor.

    """
    def __init__(self):
        # TODO: It seems on Python 2.4 the filename and line number do not work correctly.  I think we need to
        # define a custom findCaller method to actually fix the problem.
        BaseFormatter.__init__(self, '%(asctime)s [kubernetes_events_monitor] %(message)s', 'k8s_events')


class KubernetesEventsMonitor( ScalyrMonitor ):
    """
    # Kubernetes Events Monitor

    The Kuberntes Events monitor streams Kubernetes events from the Kubernetes API

    This monitor fetches Kubernetes Events from the Kubernetes API server and uploads them to Scalyr. [Kubernetes Events](https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.10/#event-v1-core) record actions taken by the Kubernetes master, such as starting or killing pods. This information can be extremely useful in debugging issues with your Pods and investigating the general health of your K8s cluster. By default, this monitor collects all events related to Pods (including objects that control Pods such as DaemonSets and Deployments) as well as Nodes.

    Each Event is uploaded to Scalyr as a single log line. The format is described in detail below, but in general, it has two JSON objects, one holding the contents of the Event as described by the Kubernetes API and the second holding additional information the Scalyr Agent has added to provide more context for the Event, such as the Deployment to which the Pod belongs.

    This monitor powers the [Kubernetes Events dashboard](https://www.scalyr.com/dash?page=k8s%20Events). Additionally, you can see all Events uploaded by [searching for monitor="kubernetes_events_monitor"](https://www.scalyr.com/events?filter=monitor%3D%22kubernetes_events_monitor%22)

    ## Event Collection Leader

    The Scalyr Agent uses a simple leader election algorithm to decide which Scalyr Agent should retrieve the cluster's Events and upload them to Scalyr. This is necessary because the Events pertain to the entire cluster (and not necessarily just one Node). Duplicate information would be uploaded if each Scalyr Agent Pod retrieved the cluster's Events and uploaded them.

    By default, the leader election algorithm selects the Scalyr Agent Pod running on the oldest Node, excluding the Node running the master. To determine which is the oldest node, each Scalyr Agent Pod will retrieve the entire cluster Node list at start up, and then query the API Server once every `leader_check_interval` seconds (defaults to 60 seconds) to ensure the leader is still alive. For large clusters, performing these checks can place noticeable load on the K8s API server. There are two ways to address this issue, with different impacts on load and flexibility.

    ### Node Labels

    The first approach is to add the label `agent.config.scalyr.com/events_leader_candidate=true` to any node that you wish to be eligible to become the events collector.  This can be done with the following command:

    `kubectl label node <nodename> agent.config.scalyr.com/events_leader_candidate=true`

    Where `<nodename>` is the name of the node in question.  You can set this label on multiple nodes, and the agent will use the oldest of them as the event collector leader.  If the leader node is shutdown, it will fallback to the next oldest node and so on.

    Once the labels have been set, you also need to configure the agent to query these labels.  This is done via the `check_labels` configuration option in the Kubernetes Events monitor config (which is off by default):

    ```
    ...
    monitors: [
      {
        "module": "scalyr_agent.builtin_monitors.kubernetes_events_monitor",
        ...
        "check_labels": true
      }
    ]
    ...
    ```

    If `check_labels` is true then instead of querying the API server for all nodes on the cluster, the Scalyr agents will only query the API server for nodes with this label set.  In order to reduce load on the API server, it is recommended to only set this label on a small number of nodes.

    This approach reduces the load placed on the API server and also provides a convenient fallback mechanism for when an exister event collector leader node is shutdown.

    ### Hardcoded Event Collector

    The second approach is to manually assign a leader node in the agent config.  This is done via the `leader_node` option of the Kubernetes Events monitor:

    ```
    ...
    monitors: [
      {
        "module": "scalyr_agent.builtin_monitors.kubernetes_events_monitor",
        ...
        "leader_node": "<name of leader node>"
      }
    ]
    ...
    ```

    When the leader node is explicitly set like this, no API queries are made to the K8s API server and only the node with that name will be used to query K8s events.  The downside to this approach is that it is less flexible, especially in the event of the node shutting down unexpectedly.

    The leader election algorithm relies on a few assumptions to work correctly and could, for large clusters, impact performance. If necessary, the events monitor can also be disabled.

    ## Disabling the Kubernetes Events Monitor

    This monitor was released and enabled by default in Scalyr Agent version `2.0.43`. If you wish to disable this monitor, you may do so by setting `k8s_events_disable` to `true` in the `scalyr-config` ConfigMap used to run your ScalyrAgent DaemonSet. You must restart the ScalyrAgent DaemonSet once you have made this configuration change. Here is one way to perform these actions:

    1. Fetch the `scalyr-config` ConfigMap from your cluster.

       ```
       kubectl get configmap scalyr-config -o yaml --export >> scalyr-config.yaml
       ```

    2. Add the following line to the data section of scalyr-config.yaml:

      ```
      k8s_events_disable: true
      ```

    3. Update the scalyr-config ConfigMap.

       ```
       kubectl delete configmap scalyr-config
       kubectl create -f scalyr-config.yaml
       ```

    4. Delete the existing Scalyr k8s DaemonSet.

       ```
       kubectl delete -f https://raw.githubusercontent.com/scalyr/scalyr-agent-2/release/k8s/scalyr-agent-2.yaml
       ```

    5. Run the new Scalyr k8s DaemonSet.

       ```
       kubectl create -f https://raw.githubusercontent.com/scalyr/scalyr-agent-2/release/k8s/scalyr-agent-2.yaml
       ```
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
            'parser': 'k8sEvents',
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

        # The namespace whose logs we should not collect.
        self.__k8s_namespaces_to_ignore = []
        for x in self._global_config.k8s_ignore_namespaces.split():
            self.__k8s_namespaces_to_ignore.append(x.strip())

        default_rotation_count, default_max_bytes = self._get_log_rotation_configuration()

        self.__event_object_filter = self._config.get( 'event_object_filter', [  'CronJob', 'DaemonSet', 'Deployment', 'Job', 'Node', 'Pod', 'ReplicaSet', 'ReplicationController', 'StatefulSet' ] )

        self.__max_log_size = self._config.get( 'max_log_size' )
        if self.__max_log_size is None:
            self.__max_log_size = default_max_bytes

        self.__max_log_rotations = self._config.get( 'max_log_rotations' )
        if self.__max_log_rotations is None:
            self.__max_log_rotations = default_rotation_count

        # TODO: This should be a config option but we will wait until we have general support for options set via
        # K8s ConfigMap
        disable = str(os.environ.get('K8S_EVENTS_DISABLE', "false")).lower()
        # Note, accepting just a single `t` here due to K8s ConfigMap issues with having a value of `true`
        self.__disable_monitor = disable == 'true' or disable == 't'

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

                self.__log_handler.setFormatter(EventLogFormatter())
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
            If `self._ignore_master` is True then any node with the label `node-role.kubernetes.io/master`
            is ignored.
            @param: k8s - a KubernetesApi object for querying the k8s api
            @query_fields - optional query string appended to the node endpoint to allow for filtering
        """
        response = k8s.query_api( '/api/v1/nodes%s' % query_fields )
        nodes = response.get( 'items', [] )

        if len(nodes) > 100:
            # TODO: Add in URL for how to use labels to rectify this once we have the documentation written up.
            global_log.warning('Warning, Kubernetes Events monitor leader election is finding more than 100 possible '
                               'candidates.  This could impact performance.  Contact support@scalyr.com for more '
                               'information', limit_once_per_x_secs=300, limit_key='k8s-too-many-event-leaders')
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
            @param: k8s - a KubernetesApi object for querying the k8s api
        """

        try:
            new_leader = None
            # first check to see if the leader node is specified as a label
            # we do this first in case the label has been moved to a different node but the old node is still
            # alive
            if self._check_labels:
                query = "?labelSelector=%s" % (urllib.quote( 'agent.config.scalyr.com/events_leader_candidate=true' ) )
                new_leader = self._check_nodes_for_leader( k8s, query )

            # if no labelled leader was found, then check to see if the previous leader is still alive
            if new_leader is not None:
                global_log.log( scalyr_logging.DEBUG_LEVEL_1, "Leader set from label" )
            else:
                if self._current_leader is not None and self._check_if_alive( k8s, self._current_leader ):
                    # still the same leader
                    global_log.log( scalyr_logging.DEBUG_LEVEL_1, "New leader same as the old leader" )
                    new_leader = self._current_leader
                else:
                    # previous leader is not alive so check all nodes for the leader
                    global_log.log( scalyr_logging.DEBUG_LEVEL_1, "Checking for a new leader" )
                    new_leader = self._check_nodes_for_leader( k8s )

            # update the global leader (leader can be None)
            self._current_leader = new_leader

        except K8sApiAuthorizationException:
            global_log.warning("Could not determine K8s event leader due to authorization error.  The "
                               "Scalyr Service Account does not have permission to retrieve the list of "
                               "available nodes.  Please recreate the role with the latest definition which can be found "
                               "at https://raw.githubusercontent.com/scalyr/scalyr-agent-2/release/k8s/scalyr-service-account.yaml "
                               "K8s event collection will be disabled until this is resolved.  See the K8s install "
                               "directions for instructions on how to create the role "
                               "https://www.scalyr.com/help/install-agent-kubernetes", limit_once_per_x_secs=300,
                               limit_key='k8s-events-no-permission')
            self._current_leader = None
            return None
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

    def _is_resource_expired( self, response ):
        """
            Checks to see if the resource identified in `response` is expired or not.
            @param: response - a response from querying the k8s api for a resource
        """
        obj = response.get( "object", JsonObject() )

        # check to see if the resource version we are using has expired
        return response.get( 'type', '' ) == 'ERROR' and obj.get( 'kind', '' ) == 'Status' and obj.get( 'reason', '' ) == 'Expired'

    def _get_involved_object( self, obj ):
        """
            Processes an object returned from querying the k8s api, and determines whether the object
            has an `involvedObject` and if so returns a tuple containing the kind, namespace and name of the involved object.
            Otherwise returns (None, None, None)
            @param: obj - an object returned from querying th k8s api
        """
        involved = obj.get( "involvedObject", JsonObject())
        kind = involved.get( 'kind', None, none_if_missing=True )
        namespace = None
        name = None

        if kind:
            name = involved.get( 'name', None, none_if_missing=True )
            namespace = involved.get( 'namespace', None, none_if_missing=True )

        return ( kind, namespace, name )

    def run(self):
        """Begins executing the monitor, writing metric output to logger.
        """
        if self.__disable_monitor:
            global_log.info('kubernetes_events_monitor exiting because it has been disabled.')
            return

        try:
            k8s_api_url = self._global_config.k8s_api_url
            k8s_verify_api_queries = self._global_config.k8s_verify_api_queries

            # We only create the k8s_cache while we are the leader
            k8s_cache = None

            if self.__log_watcher:
                self.log_config = self.__log_watcher.add_log_config( self, self.log_config )

            k8s = None
            if k8s_verify_api_queries:
                k8s = KubernetesApi(k8s_api_url=k8s_api_url)
            else:
                k8s = KubernetesApi( ca_file=None, k8s_api_url=k8s_api_url)

            pod_name = k8s.get_pod_name()
            self._node_name = k8s.get_node_name( pod_name )
            cluster_name = k8s.get_cluster_name()

            last_event = None
            last_resource = 0

            last_check = time.time() - self._leader_check_interval

            last_reported_leader = None
            while not self._is_stopped():
                current_time = time.time()

                # if we are the leader, we could be going through this loop before the leader_check_interval
                # has expired, so make sure to only check for a new leader if the interval has expired
                if last_check + self._leader_check_interval <= current_time:
                    last_check = current_time
                    # check if we are the leader
                    if not self._is_leader( k8s ):
                        #if not, then sleep and try again
                        global_log.log( scalyr_logging.DEBUG_LEVEL_1, "Leader is %s" % (str(self._current_leader)) )
                        if self._current_leader is not None and last_reported_leader != self._current_leader:
                            global_log.info('Kubernetes event leader is %s' % str(self._current_leader))
                            last_reported_leader = self._current_leader
                        if k8s_cache is not None:
                            k8s_cache.stop()
                            k8s_cache = None
                        self._sleep_but_awaken_if_stopped(self._leader_check_interval)
                        continue

                    global_log.log( scalyr_logging.DEBUG_LEVEL_1, "Leader is %s" % (str(self._current_leader)) )
                try:
                    if last_reported_leader != self._current_leader:
                        global_log.info("Acting as Kubernetes event leader")
                        last_reported_leader = self._current_leader

                    if k8s_cache is None:
                        # create the k8s cache
                        k8s_cache = k8s_utils.cache( self._global_config )

                    # start streaming events
                    lines = k8s.stream_events( last_event=last_event )

                    json = {}
                    for line in lines:
                        try:
                            json = json_lib.parse(line)
                        except Exception, e:
                            global_log.warning( "Error parsing event json: %s, %s, %s" % (line, str(e), traceback.format_exc() ) )
                            continue

                        # check to see if the resource version we are using has expired
                        if self._is_resource_expired( json ):
                            last_event = None
                            global_log.log( scalyr_logging.DEBUG_LEVEL_1, "K8S resource expired" )
                            continue

                        obj = json.get( "object", JsonObject() )
                        event_type = json.get("type", "UNKNOWN")

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
                        (kind, namespace, name) = self._get_involved_object( obj )

                        if kind is None:
                            global_log.log( scalyr_logging.DEBUG_LEVEL_1, "Ignoring event due to None kind" )
                            continue

                        # exclude any events that don't involve objects we are interested in
                        if self.__event_object_filter and kind not in self.__event_object_filter:
                            global_log.log( scalyr_logging.DEBUG_LEVEL_1, "Ignoring event due to unknown kind %s - %s" % (kind, str(metadata) ) )
                            continue

                        # ignore events that belong to namespaces we are not interested in
                        if namespace in self.__k8s_namespaces_to_ignore:
                            global_log.log( scalyr_logging.DEBUG_LEVEL_1, "Ignoring event due to belonging to an excluded namespace '%s'" % (namespace) )
                            continue

                        # get cluster and deployment information
                        extra_fields = {'k8s-cluster': cluster_name, 'watchEventType': event_type}
                        if kind:
                            if kind == 'Pod':
                                extra_fields['pod_name'] = name
                                extra_fields['pod_namespace'] = namespace
                                pod = k8s_cache.pod( namespace, name, current_time )
                                if pod and pod.controller:
                                    extra_fields['k8s-controller'] = pod.controller.name
                                    extra_fields['k8s-kind'] = pod.controller.kind
                            elif kind != 'Node':
                                controller = k8s_cache.controller( namespace, name, kind, current_time )
                                if controller:
                                    extra_fields['k8s-controller'] = controller.name
                                    extra_fields['k8s-kind'] = controller.kind

                        # if so, log to disk
                        self.__disk_logger.info( 'event=%s extra=%s' % (str(json_lib.serialize(obj)),
                                                                        str(json_lib.serialize(extra_fields))))

                        # see if we need to check for a new leader
                        if last_check + self._leader_check_interval <= current_time:
                            global_log.log( scalyr_logging.DEBUG_LEVEL_1, "Time to check for a new event leader" )
                            break
                    
                except K8sApiAuthorizationException:
                    global_log.warning("Could not stream K8s events due to an authorization error.  The "
                                       "Scalyr Service Account does not have permission to watch available events.  "
                                       "Please recreate the role with the latest definition which can be found "
                                       "at https://raw.githubusercontent.com/scalyr/scalyr-agent-2/release/k8s/scalyr-service-account.yaml "
                                       "K8s event collection will be disabled until this is resolved.  See the K8s install "
                                       "directions for instructions on how to create the role "
                                       "https://www.scalyr.com/help/install-agent-kubernetes", limit_once_per_x_secs=300,
                                       limit_key='k8s-stream-events-no-permission')
                except ConnectionError, e:
                    # ignore these, and just carry on querying in the next iteration
                    pass
                except Exception, e:
                    global_log.exception('Failed to stream k8s events due to the following exception: %s, %s, %s' % (repr(e), str(e), traceback.format_exc() ) )

            if k8s_cache is not None:
                k8s_cache.stop()
                k8s_cache = None

        except Exception:
            # TODO:  Maybe remove this catch here and let the higher layer catch it.  However, we do not
            # right now join on the monitor threads, so no one would catch it.  We should change that.
            global_log.exception('Monitor died due to exception:', error_code='failedMonitor')

    def stop(self, wait_on_join=True, join_timeout=5):
        #stop the main server
        ScalyrMonitor.stop( self, wait_on_join=wait_on_join, join_timeout=join_timeout )

