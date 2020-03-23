<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

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

## Configuration Reference

|||# Option                   ||| Usage
|||# ``module``               ||| Always ``scalyr_agent.builtin_monitors.kubernetes_events_monitor``
|||# ``max_log_size``         ||| Optional (defaults to None). How large the log file will grow before it is rotated. \
                                  If None, then the default value will be taken from the monitor level or the global \
                                  level log_rotation_max_bytes config option.  Set to zero for infinite size. Note \
                                  that rotation is not visible in Scalyr; it is only relevant for managing disk space \
                                  on the host running the agent. However, a very small limit could cause logs to be \
                                  dropped if there is a temporary network outage and the log overflows before it can \
                                  be sent to Scalyr
|||# ``max_log_rotations``    ||| Optional (defaults to None). The maximum number of log rotations before older log \
                                  files are deleted. If None, then the value is taken from the monitor level or the \
                                  global level log_rotation_backup_count option. Set to zero for infinite rotations.
|||# ``log_flush_delay``      ||| Optional (defaults to 1.0). The time to wait in seconds between flushing the log \
                                  file containing the kubernetes event messages.
|||# ``message_log``          ||| Optional (defaults to ``kubernetes_events.log``). Specifies the file name under \
                                  which event messages are stored. The file will be placed in the default Scalyr log \
                                  directory, unless it is an absolute path
|||# ``event_object_filter``  ||| Optional (defaults to ['CronJob', 'DaemonSet', 'Deployment', 'Job', 'Node', 'Pod', \
                                  'ReplicaSet', 'ReplicationController', 'StatefulSet']). A list of event object types \
                                  to filter on. If set, only events whose `involvedObject` `kind` is on this list will \
                                  be included.
|||# ``leader_check_interval``||| Optional (defaults to 60). The number of seconds to wait between checks to see if we \
                                  are still the leader.
|||# ``leader_node``          ||| Optional (defaults to None). Force the `leader` to be the scalyr-agent that runs on \
                                  this node.
|||# ``check_labels``         ||| Optional (defaults to False). If true, then the monitor will check for any nodes \
                                  with the label `agent.config.scalyr.com/events_leader_candidate=true` and the node \
                                  with this label set and that has the oldestcreation time will be the event monitor \
                                  leader.
|||# ``ignore_master``        ||| Optional (defaults to True). If true, then the monitor will ignore any nodes with \
                                  the label `node-role.kubernetes.io/master` when determining which node is the event \
                                  monitor leader.
