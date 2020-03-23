<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

# Kubernetes Monitor

This monitor is based of the docker_monitor plugin, and uses the raw logs mode of the docker
plugin to send Kubernetes logs to Scalyr.  It also reads labels from the Kubernetes API and
associates them with the appropriate logs.

## Log Config via Annotations

The logs collected by the Kubernetes monitor can be configured via k8s pod annotations.
The monitor examines all annotations on all pods, and for any annotation that begins with the
prefix log.config.scalyr.com/, it extracts the
entries (minus the prefix) and maps them to the log_config stanza for that pod's containers.
The mapping is described below.

The following fields can be configured a log via pod annotations:

* parser
* attributes
* sampling_rules
* rename_logfile
* redaction_rules

These behave in the same way as specified in the main [Scalyr help
docs](https://www.scalyr.com/help/scalyr-agent#logUpload). The following configuration
fields behave differently when configured via k8s annotations:

* exclude (see below)
* lineGroupers (not supported at all)
* path (the path is always fixed for k8s container logs)

### Excluding Logs

Containers and pods can be specifically included/excluded from having their logs collected and
sent to Scalyr.  Unlike the normal log_config `exclude` option which takes an array of log path
exclusion globs, annotations simply support a Boolean true/false for a given container/pod.
Both `include` and `exclude` are supported, with `include` always overriding `exclude` if both
are set. e.g.

    log.config.scalyr.com/exclude: true

has the same effect as

    log.config.scalyr.com/include: false

By default the agent monitors the logs of all pods/containers, and you have to manually exclude
pods/containers you don't want.  You can also set `k8s_include_all_containers: false` in the
kubernetes_monitor monitor config section of `agent.d/docker.json`, in which case all containers are
excluded by default and have to be manually included.

### Specifying Config Options

The Kubernetes monitor takes the string value of each annotation and maps it to a dict, or
array value according to the following format:

Values separated by a period are mapped to dict keys e.g. if one annotation on a given pod was
specified as:

        log.config.scalyr.com/attributes.parser: accessLog

Then this would be mapped to the following dict, which would then be applied to the log config
for all containers in that pod:

    { "attributes": { "parser": "accessLog" } }

Arrays can be specified by using one or more digits as the key, e.g. if the annotation was

        log.config.scalyr.com/sampling_rules.0.match_expression: INFO
        log.config.scalyr.com/sampling_rules.0.sampling_rate: 0.1
        log.config.scalyr.com/sampling_rules.1.match_expression: FINE
        log.config.scalyr.com/sampling_rules.1.sampling_rate: 0

This will be mapped to the following structure:

    { "sampling_rules":
        [
        { "match_expression": "INFO", "sampling_rate": 0.1 },
        { "match_expression": "FINE", "sampling_rate": 0 }
        ]
    }

Array keys are sorted by numeric order before processing and unique objects need to have
different digits as the array key. If a sub-key has an identical array key as a previously seen
sub-key, then the previous value of the sub-key is overwritten

There is no guarantee about the order of processing for items with the same numeric array key,
so if the config was specified as:

        log.config.scalyr.com/sampling_rules.0.match_expression: INFO
        log.config.scalyr.com/sampling_rules.0.match_expression: FINE

It is not defined or guaranteed what the actual value will be (INFO or FINE).

### Applying config options to specific containers in a pod

If a pod has multiple containers and you only want to apply log configuration options to a
specific container you can do so by prefixing the option with the container name, e.g. if you
had a pod with two containers `nginx` and `helper1` and you wanted to exclude `helper1` logs you
could specify the following annotation:

    log.config.scalyr.com/helper1.exclude: true

Config items specified without a container name are applied to all containers in the pod, but
container specific settings will override pod-level options, e.g. in this example:

    log.config.scalyr.com/exclude: true
    log.config.scalyr.com/nginx.include: true

All containers in the pod would be excluded *except* for the nginx container, which is included.

This technique is applicable for all log config options, not just include/exclude.  For
example you could set the line sampling rules for all containers in a pod, but use a different set
of line sampling rules for one specific container in the pod if needed.

### Dynamic Updates

Currently all annotation config options except `exclude: true`/`include: false` can be
dynamically updated using the `kubectl annotate` command.

For `exclude: true`/`include: false` once a pod/container has started being logged, then while the
container is still running, there is currently no way to dynamically start/stop logging of that
container using annotations without updating the config yaml, and applying the updated config to the
cluster.

## Configuration Reference

|||# Option                               ||| Usage
|||# ``module``                           ||| Always ``scalyr_agent.builtin_monitors.kubernetes_monitor``
|||# ``container_name``                   ||| Optional (defaults to None). Defines a regular expression that matches \
                                              the name given to the container running the scalyr-agent.
If this is \
                                              None, the scalyr agent will look for a container running \
                                              /usr/sbin/scalyr-agent-2 as the main process.

|||# ``container_check_interval``         ||| Optional (defaults to 5). How often (in seconds) to check if containers \
                                              have been started or stopped.
|||# ``api_socket``                       ||| Optional (defaults to /var/scalyr/docker.sock). Defines the unix socket \
                                              used to communicate with the docker API.   WARNING, if you have `mode` \
                                              set to `syslog`, you must also set the `docker_api_socket` configuration \
                                              option in the syslog monitor to this same value
Note:  You need to map \
                                              the host's /run/docker.sock to the same value as specified here, using \
                                              the -v parameter, e.g.
	docker run -v \
                                              /run/docker.sock:/var/scalyr/docker.sock ...
|||# ``docker_api_version``               ||| Optional (defaults to 'auto'). The version of the Docker API to use.  \
                                              WARNING, if you have `mode` set to `syslog`, you must also set the \
                                              `docker_api_version` configuration option in the syslog monitor to this \
                                              same value

|||# ``docker_log_prefix``                ||| Optional (defaults to docker). Prefix added to the start of all docker \
                                              logs.
|||# ``docker_max_parallel_stats``        ||| Optional (defaults to 20). Maximum stats requests to issue in parallel \
                                              when retrieving container metrics using the Docker API.
|||# ``docker_percpu_metrics``            ||| Optional (defaults to False). When `True`, emits cpu usage stats per \
                                              core.  Note: This is disabled by default because it can result in an \
                                              excessive amount of metric data on cpus with a large number of cores
|||# ``max_previous_lines``               ||| Optional (defaults to 5000). The maximum number of lines to read \
                                              backwards from the end of the stdout/stderr logs
when starting to log a \
                                              containers stdout/stderr to find the last line that was sent to Scalyr.
|||# ``readback_buffer_size``             ||| Optional (defaults to 5k). The maximum number of bytes to read backwards \
                                              from the end of any log files on disk
when starting to log a containers \
                                              stdout/stderr.  This is used to find the most recent timestamp logged to \
                                              file was sent to Scalyr.
|||# ``log_mode``                         ||| Optional (defaults to "docker_api"). Determine which method is used to \
                                              gather logs from the local containers. If "docker_api", then this agent \
                                              will use the docker API to contact the local containers and pull logs \
                                              from them.  If "syslog", then this agent expects the other containers to \
                                              push logs to this one using the syslog Docker log plugin.  Currently, \
                                              "syslog" is the preferred method due to bugs/issues found with the \
                                              docker API.  It is not the default to protect legacy behavior.

|||# ``container_globs``                  ||| Optional (defaults to None). If true, a list of glob patterns for \
                                              container names.  Only containers whose names match one of the glob \
                                              patterns will be monitored.
|||# ``report_container_metrics``         ||| Optional (defaults to True). If true, metrics will be collected from the \
                                              container and reported  to Scalyr.  Note, metrics are only collected \
                                              from those containers whose logs are being collected
|||# ``report_k8s_metrics``               ||| Optional (defaults to True). If true and report_container_metrics is \
                                              true, metrics will be collected from the k8s and reported to Scalyr.
|||# ``k8s_ignore_namespaces``            ||| Optional (defaults to "kube-system"). A comma-delimited list of the \
                                              namespaces whose pods's logs should not be collected and sent to Scalyr.
|||# ``k8s_ignore_pod_sandboxes``         ||| Optional (defaults to True). If True then all containers with the label \
                                              `io.kubernetes.docker.type` equal to `podsandbox` are excluded from \
                                              thelogs being collected
|||# ``k8s_include_all_containers``       ||| Optional (defaults to True). If True, all containers in all pods will be \
                                              monitored by the kubernetes monitor unless they have an include: false \
                                              or exclude: true annotation. If false, only pods/containers with an \
                                              include:true or exclude:false annotation will be monitored. See \
                                              documentation on annotations for further detail.
|||# ``k8s_use_v2_attributes``            ||| Optional (defaults to False). If True, will use v2 version of attribute \
                                              names instead of the names used with the original release of this \
                                              monitor.  This is a breaking change so could break searches / alerts if \
                                              you rely on the old names
|||# ``k8s_use_v1_and_v2_attributes``     ||| Optional (defaults to False). If True, send attributes using both v1 and \
                                              v2 versions of theirnames.  This may be used to fix breakages when you \
                                              relied on the v1 attribute names
|||# ``k8s_api_url``                      ||| DEPRECATED.
|||# ``k8s_cache_expiry_secs``            ||| Optional (defaults to 30). The amount of time to wait between fully \
                                              updating the k8s cache from the k8s api. Increase this value if you want \
                                              less network traffic from querying the k8s api.  Decrease this value if \
                                              you want dynamic updates to annotation configuration values to be \
                                              processed more quickly.
|||# ``k8s_cache_purge_secs``             ||| Optional (defaults to 300). The number of seconds to wait before purging \
                                              unused items from the k8s cache
|||# ``k8s_cache_init_abort_delay``       ||| Optional (defaults to 120). The number of seconds to wait for \
                                              initialization of the kubernetes cache before aborting the \
                                              kubernetes_monitor.
|||# ``k8s_parse_json``                   ||| Deprecated, please use `k8s_parse_format`. If set, and True, then this \
                                              flag will override the `k8s_parse_format` to `auto`. If set and False, \
                                              then this flag will override the `k8s_parse_format` to `raw`.
|||# ``k8s_parse_format``                 ||| Optional (defaults to `auto`). Valid values are: `auto`, `json`, `cri` \
                                              and `raw`. If `auto`, the monitor will try to detect the format of the \
                                              raw log files, e.g. `json` or `cri`.  Log files will be parsed in this \
                                              format before uploading to the server to extract log and timestamp \
                                              fields.  If `raw`, the raw contents of the log will be uploaded to \
                                              Scalyr. (Note: An incorrect setting can cause parsing to fail which will \
                                              result in raw logs being uploaded to Scalyr, so please leave this as \
                                              `auto` if in doubt.)
|||# ``k8s_always_use_cri``               ||| Optional (defaults to False). If True, the kubernetes monitor will \
                                              always try to read logs using the container runtime interface even when \
                                              the runtime is detected as docker
|||# ``k8s_always_use_docker``            ||| Optional (defaults to False). If True, the kubernetes monitor will \
                                              always try to get the list of running containers using docker even when \
                                              the runtime is detected to be something different.
|||# ``k8s_cri_query_filesystem``         ||| Optional (defaults to False). If True, then when in CRI mode, the \
                                              monitor will only query the filesystem for the list of active \
                                              containers, rather than first querying the Kubelet API. This is a useful \
                                              optimization when the Kubelet API is known to be disabled.
|||# ``k8s_verify_api_queries``           ||| Optional (defaults to True). If true, then the ssl connection for all \
                                              queries to the k8s API will be verified using the ca.crt certificate \
                                              found in the service account directory. If false, no verification will \
                                              be performed. This is useful for older k8s clusters where certificate \
                                              verification can fail.
|||# ``gather_k8s_pod_info``              ||| Optional (defaults to False). If true, then every gather_sample \
                                              interval, metrics will be collected from the docker and k8s APIs showing \
                                              all discovered containers and pods. This is mostly a debugging aid and \
                                              there are performance implications to always leaving this enabled
|||# ``include_daemonsets_as_deployments``||| Deprecated
|||# ``k8s_kubelet_host_ip``              ||| Optional (defaults to None). Defines the host IP address for the Kubelet \
                                              API. If None, the Kubernetes API will be queried for it
|||# ``k8s_kubelet_api_url_template``     ||| Optional (defaults to https://${host_ip}:10250). Defines the port and \
                                              protocol to use when talking to the kubelet API
|||# ``k8s_sidecar_mode``                 ||| Optional, (defaults to False). If true, then logs will only be collected \
                                              for containers running in the same Pod as the agent. This is used in \
                                              situations requiring very high throughput.

## Metrics

The table below describes the metrics recorded by the monitor.


### Network metrics

|||# Metric                         ||| Description
|||# ``docker.net.rx_bytes``        ||| Total received bytes on the network interface
|||# ``docker.net.rx_dropped``      ||| Total receive packets dropped on the network interface
|||# ``docker.net.rx_errors``       ||| Total receive errors on the network interface
|||# ``docker.net.rx_packets``      ||| Total received packets on the network interface
|||# ``docker.net.tx_bytes``        ||| Total transmitted bytes on the network interface
|||# ``docker.net.tx_dropped``      ||| Total transmitted packets dropped on the network interface
|||# ``docker.net.tx_errors``       ||| Total transmission errors on the network interface
|||# ``docker.net.tx_packets``      ||| Total packets transmitted on the network intervace
|||# ``k8s.pod.network.rx_bytes``   ||| The total received bytes on a pod
|||# ``k8s.pod.network.rx_errors``  ||| The total received errors on a pod
|||# ``k8s.pod.network.tx_bytes``   ||| The total transmitted bytes on a pod
|||# ``k8s.pod.network.tx_errors``  ||| The total transmission errors on a pod
|||# ``k8s.node.network.rx_bytes``  ||| The total received bytes on a pod
|||# ``k8s.node.network.rx_errors`` ||| The total received errors on a pod
|||# ``k8s.node.network.tx_bytes``  ||| The total transmitted bytes on a pod
|||# ``k8s.node.network.tx_errors`` ||| The total transmission errors on a pod

### Memory metrics

|||# Metric                                        ||| Description
|||# ``docker.mem.stat.active_anon``               ||| The number of bytes of active memory backed by anonymous pages, \
                                                       excluding sub-cgroups.
|||# ``docker.mem.stat.active_file``               ||| The number of bytes of active memory backed by files, excluding \
                                                       sub-cgroups.
|||# ``docker.mem.stat.cache``                     ||| The number of bytes used for the cache, excluding sub-cgroups.
|||# ``docker.mem.stat.hierarchical_memory_limit`` ||| The memory limit in bytes for the container.
|||# ``docker.mem.stat.inactive_anon``             ||| The number of bytes of inactive memory in anonymous pages, \
                                                       excluding sub-cgroups.
|||# ``docker.mem.stat.inactive_file``             ||| The number of bytes of inactive memory in file pages, excluding \
                                                       sub-cgroups.
|||# ``docker.mem.stat.mapped_file``               ||| The number of bytes of mapped files, excluding sub-groups
|||# ``docker.mem.stat.pgfault``                   ||| The total number of page faults, excluding sub-cgroups.
|||# ``docker.mem.stat.pgmajfault``                ||| The number of major page faults, excluding sub-cgroups
|||# ``docker.mem.stat.pgpgin``                    ||| The number of charging events, excluding sub-cgroups
|||# ``docker.mem.stat.pgpgout``                   ||| The number of uncharging events, excluding sub-groups
|||# ``docker.mem.stat.rss``                       ||| The number of bytes of anonymous and swap cache memory (includes \
                                                       transparent hugepages), excluding sub-cgroups
|||# ``docker.mem.stat.rss_huge``                  ||| The number of bytes of anonymous transparent hugepages, excluding \
                                                       sub-cgroups
|||# ``docker.mem.stat.unevictable``               ||| The number of bytes of memory that cannot be reclaimed (mlocked \
                                                       etc), excluding sub-cgroups
|||# ``docker.mem.stat.writeback``                 ||| The number of bytes being written back to disk, excluding \
                                                       sub-cgroups
|||# ``docker.mem.stat.total_active_anon``         ||| The number of bytes of active memory backed by anonymous pages, \
                                                       including sub-cgroups.
|||# ``docker.mem.stat.total_active_file``         ||| The number of bytes of active memory backed by files, including \
                                                       sub-cgroups.
|||# ``docker.mem.stat.total_cache``               ||| The number of bytes used for the cache, including sub-cgroups.
|||# ``docker.mem.stat.total_inactive_anon``       ||| The number of bytes of inactive memory in anonymous pages, \
                                                       including sub-cgroups.
|||# ``docker.mem.stat.total_inactive_file``       ||| The number of bytes of inactive memory in file pages, including \
                                                       sub-cgroups.
|||# ``docker.mem.stat.total_mapped_file``         ||| The number of bytes of mapped files, including sub-groups
|||# ``docker.mem.stat.total_pgfault``             ||| The total number of page faults, including sub-cgroups.
|||# ``docker.mem.stat.total_pgmajfault``          ||| The number of major page faults, including sub-cgroups
|||# ``docker.mem.stat.total_pgpgin``              ||| The number of charging events, including sub-cgroups
|||# ``docker.mem.stat.total_pgpgout``             ||| The number of uncharging events, including sub-groups
|||# ``docker.mem.stat.total_rss``                 ||| The number of bytes of anonymous and swap cache memory (includes \
                                                       transparent hugepages), including sub-cgroups
|||# ``docker.mem.stat.total_rss_huge``            ||| The number of bytes of anonymous transparent hugepages, including \
                                                       sub-cgroups
|||# ``docker.mem.stat.total_unevictable``         ||| The number of bytes of memory that cannot be reclaimed (mlocked \
                                                       etc), including sub-cgroups
|||# ``docker.mem.stat.total_writeback``           ||| The number of bytes being written back to disk, including \
                                                       sub-cgroups
|||# ``docker.mem.max_usage``                      ||| The max amount of memory used by container in bytes.
|||# ``docker.mem.usage``                          ||| The current number of bytes used for memory including cache.
|||# ``docker.mem.fail_cnt``                       ||| The number of times the container hit its memory limit
|||# ``docker.mem.limit``                          ||| The memory limit for the container in bytes.

### CPU metrics

|||# Metric                                      ||| Description
|||# ``docker.cpu.usage``                        ||| Total CPU consumed by container in nanoseconds
|||# ``docker.cpu.system_cpu_usage``             ||| Total CPU consumed by container in kernel mode in nanoseconds
|||# ``docker.cpu.usage_in_usermode``            ||| Total CPU consumed by tasks of the cgroup in user mode in nanoseconds
|||# ``docker.cpu.total_usage``                  ||| Total CPU consumed by tasks of the cgroup in nanoseconds
|||# ``docker.cpu.usage_in_kernelmode``          ||| Total CPU consumed by tasks of the cgroup in kernel mode in \
                                                     nanoseconds
|||# ``docker.cpu.throttling.periods``           ||| The number of of periods with throttling active.
|||# ``docker.cpu.throttling.throttled_periods`` ||| The number of periods where the container hit its throttling limit
|||# ``docker.cpu.throttling.throttled_time``    ||| The aggregate amount of time the container was throttled in \
                                                     nanoseconds
