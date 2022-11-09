# Copyright 2018-2022 Scalyr Inc.
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
# author: scalyr-cloudtech@scalyr.com

from __future__ import unicode_literals
from __future__ import absolute_import

__author__ = "scalyr-cloudtech@scalyr.com"

from scalyr_agent import compat

from scalyr_agent.monitor_utils.k8s import (
    KubernetesApi,
    K8sApiException,
    K8sApiAuthorizationException,
    ApiQueryOptions,
    K8sNamespaceFilter,
)
import scalyr_agent.monitor_utils.k8s as k8s_utils

from scalyr_agent.third_party.requests.exceptions import ConnectionError

import datetime
import re
import traceback
import time
import logging
import logging.handlers

import six
import six.moves.urllib.request
import six.moves.urllib.error
import six.moves.urllib.parse


from scalyr_agent import (
    ScalyrMonitor,
    define_config_option,
    AutoFlushingRotatingFileHandler,
)
from scalyr_agent.scalyr_logging import BaseFormatter
from scalyr_agent.json_lib.objects import ArrayOfStrings
import scalyr_agent.util as scalyr_util
from scalyr_agent.json_lib import JsonObject
from scalyr_agent.date_parsing_utils import rfc3339_to_datetime

import scalyr_agent.scalyr_logging as scalyr_logging

global_log = scalyr_logging.getLogger(__name__)

SCALYR_CONFIG_ANNOTATION_RE = re.compile(r"^(agent\.config\.scalyr\.com/)(.+)")

__monitor__ = __name__

define_config_option(
    __monitor__,
    "module",
    "Always ``scalyr_agent.builtin_monitors.kubernetes_events_monitor``",
    convert_to=six.text_type,
    required_option=True,
)

define_config_option(
    __monitor__,
    "max_log_size",
    "Optional (defaults to None). How large the log file will grow before it is rotated. If None, then the "
    "default value will be taken from the monitor level or the global level log_rotation_max_bytes config option.  Set to zero "
    "for infinite size. Note that rotation is not visible in Scalyr; it is only relevant for managing "
    "disk space on the host running the agent. However, a very small limit could cause logs to be "
    "dropped if there is a temporary network outage and the log overflows before it can be sent to "
    "Scalyr",
    convert_to=int,
    default=None,
    env_name="SCALYR_K8S_MAX_LOG_SIZE",
)

define_config_option(
    __monitor__,
    "max_log_rotations",
    "Optional (defaults to None). The maximum number of log rotations before older log files are "
    "deleted. If None, then the value is taken from the monitor level or the global level log_rotation_backup_count option. "
    "Set to zero for infinite rotations.",
    convert_to=int,
    default=None,
    env_name="SCALYR_K8S_MAX_LOG_ROTATIONS",
)

define_config_option(
    __monitor__,
    "log_flush_delay",
    "Optional (defaults to 1.0). The time to wait in seconds between flushing the log file containing "
    "the kubernetes event messages.",
    convert_to=float,
    default=1.0,
    env_name="SCALYR_K8S_LOG_FLUSH_DELAY",
)

define_config_option(
    __monitor__,
    "message_log",
    "Optional (defaults to ``kubernetes_events.log``). Specifies the file name under which event messages "
    "are stored. The file will be placed in the default Scalyr log directory, unless it is an "
    "absolute path",
    convert_to=six.text_type,
    default="kubernetes_events.log",
    env_name="SCALYR_K8S_MESSAGE_LOG",
)

EVENT_OBJECT_FILTER_DEFAULTS = [
    "CronJob",
    "DaemonSet",
    "Deployment",
    "Job",
    "Node",
    "Pod",
    "ReplicaSet",
    "ReplicationController",
    "StatefulSet",
    "Endpoint",
]
define_config_option(
    __monitor__,
    "event_object_filter",
    "Optional (defaults to %s). A list of event object types to filter on. "
    "Only events whose ``involvedObject`` ``kind`` is on this list will be included.  "
    "To not perform filtering and to send all event kinds, set the environment variable "
    "``SCALYR_K8S_EVENT_OBJECT_FILTER=null``."
    % six.text_type(EVENT_OBJECT_FILTER_DEFAULTS),
    convert_to=ArrayOfStrings,
    default=EVENT_OBJECT_FILTER_DEFAULTS,
    env_name="SCALYR_K8S_EVENT_OBJECT_FILTER",
)

define_config_option(
    __monitor__,
    "leader_check_interval",
    "Optional (defaults to 60). The number of seconds to wait between checks to see if we are still the leader.",
    convert_to=int,
    default=60,
    env_name="SCALYR_K8S_LEADER_CHECK_INTERVAL",
)

define_config_option(
    __monitor__,
    "check_labels",
    "Optional (defaults to False). If true, then the monitor will check for any pods with the label "
    "`agent.config.scalyr.com/events_leader_candidate=true` and the pod with this label set and that has the oldest"
    "creation time will be the event monitor leader.",
    convert_to=bool,
    default=False,
    env_name="SCALYR_K8S_CHECK_LABELS",
)

define_config_option(
    __monitor__,
    "leader_candidate_label",
    "Optional (defaults to `agent.config.scalyr.com/events_leader_candidate=true`). "
    "If `check_labels` is true, then the monitor will check for any nodes with the label "
    "configured using this option and the node with this label set and that has the oldest"
    "creation time will be the event monitor leader.",
    convert_to=six.text_type,
    default="agent.config.scalyr.com/events_leader_candidate=true",
    env_name="SCALYR_K8S_LEADER_CANDIDATE_LABEL",
)


class EventLogFormatter(BaseFormatter):
    """Formatter used for the logs produced by the event monitor."""

    def __init__(self):
        # TODO: It seems on Python 2.4 the filename and line number do not work correctly.  I think we need to
        # define a custom findCaller method to actually fix the problem.
        BaseFormatter.__init__(
            self, "%(asctime)s [kubernetes_events_monitor] %(message)s", "k8s_events"
        )


class KubernetesEventsMonitor(
    ScalyrMonitor
):  # pylint: disable=monitor-not-included-for-win32
    # fmt: off
    """
# Kubernetes Events Monitor

The Kuberntes Events monitor streams Kubernetes events from the Kubernetes API

This monitor fetches Kubernetes Events from the Kubernetes API server and uploads them to Scalyr. [Kubernetes Events](https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.10/#event-v1-core) record actions taken by the Kubernetes master, such as starting or killing pods. This information can be extremely useful in debugging issues with your Pods and investigating the general health of your K8s cluster. By default, this monitor collects all events related to Pods (including objects that control Pods such as DaemonSets and Deployments) as well as Nodes.

Each Event is uploaded to Scalyr as a single log line. The format is described in detail below, but in general, it has two JSON objects, one holding the contents of the Event as described by the Kubernetes API and the second holding additional information the Scalyr Agent has added to provide more context for the Event, such as the Deployment to which the Pod belongs.

This monitor powers the [Kubernetes Events dashboard](https://www.scalyr.com/dash?page=k8s%20Events). Additionally, you can see all Events uploaded by [searching for monitor="kubernetes_events_monitor"](https://www.scalyr.com/events?filter=monitor%3D%22kubernetes_events_monitor%22)

## Event Collection Leader

The Scalyr Agent uses a simple leader election algorithm to decide which Scalyr Agent should retrieve the cluster's Events and upload them to Scalyr. This is necessary because the Events pertain to the entire cluster. Duplicate information would be uploaded if each Scalyr Agent Pod retrieved the cluster's Events and uploaded them.

By default, the leader election algorithm selects the Scalyr Agent running on the oldest Pod. To determine which is the oldest pod, each Scalyr Agent Pod will retrieve the Pod list of the associated ReplicaSet at start up, and then query the API Server once every `leader_check_interval` seconds (defaults to 60 seconds) to ensure the leader is still alive. For large deployment/replicaset or cluster/daemonset, performing these checks can place noticeable load on the K8s API server. Beyond using a limited ReplicaSet in the Deployment (or a separate DaemonSet for the monitor), there is another way to address this issue.

### Pod Labels

The approach is to add the label `agent.config.scalyr.com/events_leader_candidate=true` (or the value specified in `leader_candidate_label`) to a subset of pods that you wish to be eligible to become the events collector.  This can be done with the following command:

`kubectl label pod <podname> agent.config.scalyr.com/events_leader_candidate=true`

Where `<podname>` is the name of the pod in question.  You can set this label on multiple pods, and the agent will use the oldest of them as the event collector leader.  If the leader pod is shutdown, it will fallback to the next oldest pod and so on.

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

If `check_labels` is true then instead of querying the API server for all nodes on the cluster, the Scalyr agents will only query the API server for pods with this label set.  In order to reduce load on the API server, it is recommended to only set this label on a small number of pods.

This approach reduces the load placed on the API server and also provides a convenient fallback mechanism for when the existing event collector leader pod is shutdown.

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
    # fmt: on

    def _initialize(self):

        # our disk logger and handler
        self.__disk_logger = None
        self.__log_handler = None

        self.__log_watcher = None
        self.__module = None

        self._pod_name = None

        # configure the logger and path
        self.__message_log = self._config.get("message_log")

        self.log_config = {
            "parser": "k8sEvents",
            "path": self.__message_log,
        }

        self._leader_check_interval = self._config.get("leader_check_interval")
        self._check_labels = self._config.get("check_labels")
        self._leader_candidate_label = self._config.get("leader_candidate_label")

        self._current_leader = None
        self._owner_selector = None

        self.__flush_delay = self._config.get("log_flush_delay")
        try:
            attributes = JsonObject({"monitor": "json"})
            self.log_config["attributes"] = attributes
        except Exception:
            global_log.error(
                "Error setting monitor attribute in KubernetesEventMonitor"
            )

        # The namespace whose logs we should collect.
        # TODO: Correctly handle int values
        self.__k8s_namespaces_to_include = K8sNamespaceFilter.from_config(
            global_config=self._global_config
        )

        (
            default_rotation_count,
            default_max_bytes,
        ) = self._get_log_rotation_configuration()

        self.__event_object_filter = self._config.get(
            "event_object_filter",
            [
                "CronJob",
                "DaemonSet",
                "Deployment",
                "Job",
                "Node",
                "Pod",
                "ReplicaSet",
                "ReplicationController",
                "StatefulSet",
                "Endpoint",
            ],
        )

        self.__max_log_size = self._config.get("max_log_size")
        if self.__max_log_size is None:
            self.__max_log_size = default_max_bytes
        else:
            self.__max_log_size = int(self.__max_log_size)

        self.__max_log_rotations = self._config.get("max_log_rotations")
        if self.__max_log_rotations is None:
            self.__max_log_rotations = default_rotation_count
        else:
            self.__max_log_rotations = int(self.__max_log_rotations)

        # Support legacy disabling of k8s_events via the K8S_EVENTS_DISABLE environment variable
        k8s_events_disable_envar = compat.os_environ_unicode.get("K8S_EVENTS_DISABLE")
        if k8s_events_disable_envar is not None:
            global_log.warn(
                "The K8S_EVENTS_DISABLE environment variable is deprecated. Please use SCALYR_K8S_EVENTS_DISABLE instead."
            )
            legacy_disable = six.text_type(k8s_events_disable_envar).lower()
        else:
            legacy_disable = "false"

        # Note, accepting just a single `t` here due to K8s ConfigMap issues with having a value of `true`
        self.__disable_monitor = bool(
            legacy_disable == "true"
            or legacy_disable == "t"
            or self._global_config.k8s_events_disable
        )

        # NOTE: Right now Kubernetes Explorer functionality also needs data from Kubernetes events
        # monitor so in case explorer functionality is enabled, we also enable events monitor
        if self.__disable_monitor and self._global_config.k8s_explorer_enable:
            # NOTE: In case
            global_log.info(
                "k8s_explorer_enable config option is set to true, enabling kubernetes events monitor",
                limit_once_per_x_secs=(12 * 60 * 60),
                limit_key="k8s-ev-expr-enabled",
            )
            self.__disable_monitor = False

    def open_metric_log(self):
        """Override open_metric_log to prevent a metric log from being created for the Kubernetes Events Monitor
        and instead create our own logger which will log raw messages out to disk.
        """
        self.__disk_logger = logging.getLogger(self.__message_log)

        # assume successful for when the logger handler has already been created
        success = True

        # only configure once -- assumes all configuration happens on the same thread
        if len(self.__disk_logger.handlers) == 0:
            # logger handler hasn't been created yet, so assume unsuccssful
            success = False
            try:
                self.__log_handler = AutoFlushingRotatingFileHandler(
                    filename=self.log_config["path"],
                    maxBytes=self.__max_log_size,
                    backupCount=self.__max_log_rotations,
                    flushDelay=self.__flush_delay,
                )

                self.__log_handler.setFormatter(EventLogFormatter())
                self.__disk_logger.addHandler(self.__log_handler)
                self.__disk_logger.setLevel(logging.INFO)
                self.__disk_logger.propagate = False
                success = True
            except Exception as e:
                global_log.error(
                    "Unable to open KubernetesEventsMonitor log file: %s"
                    % six.text_type(e)
                )

        return success

    def close_metric_log(self):
        if self.__log_handler:
            self.__disk_logger.removeHandler(self.__log_handler)
            self.__log_handler.close()

    def set_log_watcher(self, log_watcher):
        self.__log_watcher = log_watcher

    def _check_if_alive(self, k8s, pod):
        """
        Checks to see if the pod specified by `pod` is alive
        """
        if pod is None:
            return False

        try:
            # this call will throw an exception on failure
            k8s.query_api_with_retries(
                "/api/v1/namespaces/%s/pods/%s" % (k8s.namespace, pod),
                retry_error_context="%s/pods/%s" % (k8s.namespace, pod),
                retry_error_limit_key="k8se_check_if_alive",
            )
        except Exception:
            global_log.log(
                scalyr_logging.DEBUG_LEVEL_1, "_check_if_alive False for pod %s" % pod
            )
            return False

        # if we are here, then the above pod exists so return True
        return True

    def _get_oldest_pod(self, pods):
        """
        Takes a list of pods returned from querying the k8s api, and returns the name
        of the pod with the oldest creationTimestamp or None if pods is empty or doesn't
        contain Pod objects.
        """

        oldest_time = datetime.datetime.utcnow()
        oldest = None

        # loop over all pods and find the one with the oldest create time
        for pod in pods:
            metadata = pod.get("metadata", {})
            create_time = metadata.get("creationTimestamp", None)
            if create_time is None:
                continue

            name = metadata.get("name", None)
            if name is None:
                continue

            # convert to datetime
            create_time = rfc3339_to_datetime(create_time)

            # if we are older than the previous oldest datetime, then update the oldest time
            if create_time is not None and create_time < oldest_time:
                oldest_time = create_time
                oldest = name

        return oldest

    def _check_pods_for_leader(self, k8s, selector=None):
        """
        Checks all pods in the owner (replicaset/daemonset) to see which one has the oldest creationTime
        @param k8s: a KubernetesApi object for querying the k8s api
        @selector - optional pod selector to allow for filtering
        """

        # Determine the current pod's owner for the selector to the other owned pods.
        # Done in two stages: retrieve the current pod for the owner type and name, then the selector proper.
        if not selector and not self._owner_selector:
            owner_name, owner_type = None, None
            response = k8s.query_api_with_retries(
                "/api/v1/namespaces/%s/pods/%s" % (k8s.namespace, self._pod_name),
                retry_error_context="%s/pods/%s" % (k8s.namespace, self._pod_name),
                retry_error_limit_key="k8se_get_own_pod",
            )
            for owner in response.get("metadata", {}).get("ownerReferences", []):
                if owner.get("kind") in ["DaemonSet", "ReplicaSet"] and "name" in owner:
                    owner_type, owner_name = owner["kind"], owner["name"]
                    break
            if not owner_name:
                raise K8sApiException("unable to determine pod's owner")

            if owner_type == "DaemonSet":
                response = k8s.query_api_with_retries(
                    "/apis/apps/v1/namespaces/%s/daemonsets/%s"
                    % (k8s.namespace, owner_name),
                    retry_error_context="%s/daemonsets/%s"
                    % (k8s.namespace, owner_name),
                    retry_error_limit_key="k8se_get_own_daemonset",
                )
                selector = ""
                for k, v in (
                    response.get("spec", {}).get("selector", {}).get("matchLabels", {})
                ).items():
                    if selector != "":
                        selector += ","
                    selector += k + "=" + v
                self._owner_selector = selector

            elif owner_type == "ReplicaSet":
                response = k8s.query_api_with_retries(
                    "/apis/apps/v1/namespaces/%s/replicasets/%s/scale"
                    % (k8s.namespace, owner_name),
                    retry_error_context="%s/replicasets/%s/scale"
                    % (k8s.namespace, owner_name),
                    retry_error_limit_key="k8se_get_own_replicaset",
                )
                self._owner_selector = response.get("status", {}).get("selector")

            if not self._owner_selector:
                raise K8sApiException("unable to determine replicaset selector")

        params = "?labelSelector=" + six.moves.urllib.parse.quote(
            selector or self._owner_selector
        )
        response = k8s.query_api_with_retries(
            "/api/v1/namespaces/%s/pods%s" % (k8s.namespace, params),
            retry_error_context="%s/pods%s" % (k8s.namespace, params),
            retry_error_limit_key="k8se_check_pods_for_leader",
        )
        pods = response.get("items", [])

        if len(pods) > 100:
            # TODO: Add in URL for how to use labels to rectify this once we have the documentation written up.
            global_log.warning(
                "Warning, Kubernetes Events monitor leader election is finding more than 100 possible "
                "candidates.  This could impact performance.  Contact support@scalyr.com for more "
                "information",
                limit_once_per_x_secs=300,
                limit_key="k8s-too-many-event-leaders",
            )
        # sort the list by pod name to ensure consistent processing order
        # if two pod have exactly the same creation time
        pods.sort(key=lambda n: n.get("metadata", {}).get("name", ""))

        # the leader is the longest running pod
        return self._get_oldest_pod(pods)

    def _get_current_leader(self, k8s):
        """
        Queries the kubernetes api to see which pod is the current leader pod.

        Check to see if the leader is specified using a pod label.
        If not, then if there is not a current leader pod, or if the current leader pod no longer exists
        then query all pods in the owner (replicaset/daemonset) for the leader
        @param k8s: a KubernetesApi object for querying the k8s api
        """

        try:
            new_leader = None
            # first check to see if the leader pod is specified via a label
            # this is in case the label has been moved to a different pod and the old pod is still alive
            if self._check_labels:
                new_leader = self._check_pods_for_leader(
                    k8s, self._leader_candidate_label
                )

            if new_leader is not None:
                global_log.log(scalyr_logging.DEBUG_LEVEL_1, "Leader set from label")
            else:
                # if no labelled leader was found, then check to see if the previous leader is still alive
                if self._current_leader is not None and self._check_if_alive(
                    k8s, self._current_leader
                ):
                    # still the same leader
                    global_log.log(
                        scalyr_logging.DEBUG_LEVEL_1,
                        "New leader same as the old leader",
                    )
                    new_leader = self._current_leader
                else:
                    # previous leader is not alive so check all pods in the owner for the leader
                    global_log.log(
                        scalyr_logging.DEBUG_LEVEL_1, "Checking for a new leader"
                    )
                    new_leader = self._check_pods_for_leader(k8s)

            # update the global leader (leader can be None)
            self._current_leader = new_leader

        except K8sApiAuthorizationException:
            global_log.warning(
                "Could not determine K8s event leader due to authorization error.  The "
                "Scalyr Service Account does not have permission to retrieve the list of "
                "available pods.  Please recreate the role with the latest definition which can be found "
                "at https://raw.githubusercontent.com/scalyr/scalyr-agent-2/release/k8s/scalyr-service-account.yaml "
                "K8s event collection will be disabled until this is resolved.  See the K8s install "
                "directions for instructions on how to create the role "
                "https://www.scalyr.com/help/install-agent-kubernetes",
                limit_once_per_x_secs=300,
                limit_key="k8s-events-no-permission",
            )
            self._current_leader = None
            return None
        except K8sApiException as e:
            global_log.error(
                "get current leader: %s, %s"
                % (six.text_type(e), traceback.format_exc())
            )

        return self._current_leader

    def _is_leader(self, k8s):
        """
        Detects if this agent is the `leader` for events in a cluster.  In order to prevent duplicates, only `leader` agents will log events.
        """
        if self._pod_name is None:
            return False

        leader = None
        try:
            leader = self._get_current_leader(k8s)
        except Exception as e:
            global_log.log(
                scalyr_logging.DEBUG_LEVEL_0,
                "Unexpected error checking for leader: %s" % (six.text_type(e)),
            )

        return leader is not None and self._pod_name == leader

    def _is_resource_expired(self, response):
        """
        Checks to see if the resource identified in `response` is expired or not.
        @param response: a response from querying the k8s api for a resource
        """
        obj = response.get("object", dict())

        # check to see if the resource version we are using has expired
        return (
            response.get("type", "") == "ERROR"
            and obj.get("kind", "") == "Status"
            and obj.get("reason", "") == "Expired"
        )

    def _get_involved_object(self, obj):
        """
        Processes an object returned from querying the k8s api, and determines whether the object
        has an `involvedObject` and if so returns a tuple containing the kind, namespace and name of the involved object.
        Otherwise returns (None, None, None)
        @param obj: an object returned from querying th k8s api
        """
        involved = obj.get("involvedObject", dict())
        kind = involved.get("kind", None)
        namespace = None
        name = None

        if kind:
            name = involved.get("name", None)
            namespace = involved.get("namespace", None)

        return (kind, namespace, name)

    def run(self):
        """Begins executing the monitor, writing metric output to logger."""
        if self.__disable_monitor:
            global_log.info(
                "kubernetes_events_monitor exiting because it has been disabled."
            )
            return

        try:
            self._global_config.k8s_api_url
            self._global_config.k8s_verify_api_queries

            # We only create the k8s_cache while we are the leader
            k8s_cache = None

            # First instance of k8s api uses the main rate limiter.  Leader election related API calls to the k8s
            # masters will go through this api/rate limiter.
            k8s_api_main = KubernetesApi.create_instance(
                self._global_config, rate_limiter_key="K8S_CACHE_MAIN_RATELIMITER"
            )

            # Second instance of k8s api uses an ancillary ratelimiter (for exclusive use by events monitor)
            k8s_api_events = KubernetesApi.create_instance(
                self._global_config, rate_limiter_key="K8S_EVENTS_RATELIMITER"
            )

            # k8s_cache is initialized with the main rate limiter. However, streaming-related API calls should go
            # through the ancillary ratelimiter. This is achieved by passing ApiQueryOptions with desired rate_limiter.
            k8s_events_query_options = ApiQueryOptions(
                max_retries=self._global_config.k8s_controlled_warmer_max_query_retries,
                rate_limiter=k8s_api_events.default_query_options.rate_limiter,
            )

            self._pod_name = k8s_api_main.get_pod_name()
            cluster_name = k8s_api_main.get_cluster_name()

            last_event = None
            last_resource = 0

            last_check = time.time() - self._leader_check_interval

            last_reported_leader = None
            while not self._is_thread_stopped():
                current_time = time.time()

                # if we are the leader, we could be going through this loop before the leader_check_interval
                # has expired, so make sure to only check for a new leader if the interval has expired
                if last_check + self._leader_check_interval <= current_time:
                    last_check = current_time
                    # check if we are the leader
                    if not self._is_leader(k8s_api_main):
                        # if not, then sleep and try again
                        global_log.log(
                            scalyr_logging.DEBUG_LEVEL_1,
                            "Leader is %s" % (six.text_type(self._current_leader)),
                        )
                        if (
                            self._current_leader is not None
                            and last_reported_leader != self._current_leader
                        ):
                            global_log.info(
                                "Kubernetes event leader is %s"
                                % six.text_type(self._current_leader)
                            )
                            last_reported_leader = self._current_leader
                        if k8s_cache is not None:
                            k8s_cache.stop()
                            k8s_cache = None
                        self._sleep_but_awaken_if_stopped(self._leader_check_interval)
                        continue

                    global_log.log(
                        scalyr_logging.DEBUG_LEVEL_1,
                        "Leader is %s" % (six.text_type(self._current_leader)),
                    )
                try:
                    if last_reported_leader != self._current_leader:
                        global_log.info("Acting as Kubernetes event leader")
                        last_reported_leader = self._current_leader

                    if k8s_cache is None:
                        # create the k8s cache
                        k8s_cache = k8s_utils.cache(self._global_config)

                    # start streaming events
                    lines = k8s_api_events.stream_events(last_event=last_event)

                    json = {}
                    for line in lines:
                        try:
                            json = scalyr_util.json_decode(line)
                        except Exception as e:
                            global_log.warning(
                                "Error parsing event json: %s, %s, %s"
                                % (line, six.text_type(e), traceback.format_exc())
                            )
                            continue

                        try:
                            # check to see if the resource version we are using has expired
                            if self._is_resource_expired(json):
                                last_event = None
                                global_log.log(
                                    scalyr_logging.DEBUG_LEVEL_1, "K8S resource expired"
                                )
                                continue

                            obj = json.get("object", dict())
                            event_type = json.get("type", "UNKNOWN")

                            # resource version hasn't expired, so update it to the most recently seen version
                            last_event = last_resource

                            metadata = obj.get("metadata", dict())

                            # skip any events with resourceVersions higher than ones we've already seen
                            resource_version = metadata.get("resourceVersion", None)
                            if resource_version is not None:
                                resource_version = int(resource_version)

                            # NOTE: In some scenarios last_resource can be None.
                            # In such scenario, we skip this check
                            if (
                                resource_version
                                and last_resource
                                and resource_version <= last_resource
                            ):
                                global_log.log(
                                    scalyr_logging.DEBUG_LEVEL_2,
                                    "Skipping older resource events",
                                )
                                continue

                            last_resource = resource_version
                            last_event = resource_version

                            # see if this event is about an object we are interested in
                            (kind, namespace, name) = self._get_involved_object(obj)

                            if kind is None:
                                global_log.log(
                                    scalyr_logging.DEBUG_LEVEL_1,
                                    "Ignoring event due to None kind",
                                )
                                continue

                            # exclude any events that don't involve objects we are interested in
                            if (
                                self.__event_object_filter
                                and kind not in self.__event_object_filter
                            ):
                                global_log.log(
                                    scalyr_logging.DEBUG_LEVEL_1,
                                    "Ignoring event due to unknown kind %s - %s"
                                    % (kind, six.text_type(metadata)),
                                )
                                continue

                            # ignore events that belong to namespaces we are not interested in
                            if namespace not in self.__k8s_namespaces_to_include:
                                global_log.log(
                                    scalyr_logging.DEBUG_LEVEL_1,
                                    "Ignoring event due to belonging to an excluded namespace '%s'"
                                    % (namespace),
                                )
                                continue

                            # get cluster and deployment information
                            extra_fields = {
                                "k8s-cluster": cluster_name,
                                "watchEventType": event_type,
                            }
                            if kind:
                                if kind == "Pod":
                                    extra_fields["pod_name"] = name
                                    extra_fields["pod_namespace"] = namespace
                                    try:
                                        pod = k8s_cache.pod(
                                            namespace,
                                            name,
                                            current_time,
                                            query_options=k8s_events_query_options,
                                        )
                                    except k8s_utils.K8sApiNotFoundException as e:
                                        global_log.log(
                                            scalyr_logging.DEBUG_LEVEL_1,
                                            "Failed to process single k8s event line due to following exception: %s, %s, %s"
                                            % (
                                                repr(e),
                                                six.text_type(e),
                                                traceback.format_exc(),
                                            ),
                                        )
                                        continue
                                    if pod and pod.controller:
                                        extra_fields[
                                            "k8s-controller"
                                        ] = pod.controller.name
                                        extra_fields["k8s-kind"] = pod.controller.kind
                                elif kind != "Node":
                                    controller = k8s_cache.controller(
                                        namespace,
                                        name,
                                        kind,
                                        current_time,
                                        query_options=k8s_events_query_options,
                                    )
                                    if controller:
                                        extra_fields["k8s-controller"] = controller.name
                                        extra_fields["k8s-kind"] = controller.kind

                            # if so, log to disk
                            self.__disk_logger.info(
                                "event=%s extra=%s"
                                % (
                                    six.text_type(scalyr_util.json_encode(obj)),
                                    six.text_type(
                                        scalyr_util.json_encode(extra_fields)
                                    ),
                                )
                            )

                            # see if we need to check for a new leader
                            if last_check + self._leader_check_interval <= current_time:
                                global_log.log(
                                    scalyr_logging.DEBUG_LEVEL_1,
                                    "Time to check for a new event leader",
                                )
                                break

                        except Exception as e:
                            global_log.exception(
                                "Failed to process single k8s event line due to following exception: %s, %s, %s"
                                % (repr(e), six.text_type(e), traceback.format_exc()),
                                limit_once_per_x_secs=300,
                                limit_key="k8s-stream-events-general-exception",
                            )
                except K8sApiAuthorizationException:
                    global_log.warning(
                        "Could not stream K8s events due to an authorization error.  The "
                        "Scalyr Service Account does not have permission to watch available events.  "
                        "Please recreate the role with the latest definition which can be found "
                        "at https://raw.githubusercontent.com/scalyr/scalyr-agent-2/release/k8s/scalyr-service-account.yaml "
                        "K8s event collection will be disabled until this is resolved.  See the K8s install "
                        "directions for instructions on how to create the role "
                        "https://www.scalyr.com/help/install-agent-kubernetes",
                        limit_once_per_x_secs=300,
                        limit_key="k8s-stream-events-no-permission",
                    )
                except ConnectionError:
                    # ignore these, and just carry on querying in the next loop
                    pass
                except Exception as e:
                    global_log.exception(
                        "Failed to stream k8s events due to the following exception: %s, %s, %s"
                        % (repr(e), six.text_type(e), traceback.format_exc())
                    )

            if k8s_cache is not None:
                k8s_cache.stop()
                k8s_cache = None

        except Exception:
            # TODO:  Maybe remove this catch here and let the higher layer catch it.  However, we do not
            # right now join on the monitor threads, so no one would catch it.  We should change that.
            global_log.exception(
                "Monitor died due to exception:", error_code="failedMonitor"
            )

    def stop(self, wait_on_join=True, join_timeout=5):
        # stop the main server
        ScalyrMonitor.stop(self, wait_on_join=wait_on_join, join_timeout=join_timeout)
