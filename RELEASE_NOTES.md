# Release Notes

## 2.1.8 - TBD

* Default value for the  ``compression_level`` configuration option when using
  ``compression_type: deflate`` has been changed from ``9`` to ``6`` (``deflate`` is a default
  value is ``compress_type`` configuration option is not specified by the end user).

  ``6`` offers a best compromise between CPU usage and compression ratio.

  For the average case, using ``9`` usually only offers a very small increase in a compression
  ratio (in the range of couple % at most), but it uses much more CPU time (that is especially
  true for highly loaded scenarios and large request sizes).

  Keep in mind that this default value will only be used if you don't explicitly specify
  ``compression_level`` configuration option in your agent config.

  If you want to use level 9, you can still do that by adding ``compression_level: 9`` to your
  agent config.

## 2.1.7 "Serenity" - June 24, 2020

* Windows 32-bit systems are no longer supported.

  If you still need support, you should not upgrade beyond version 2.1.6.

* Agent configuration files now support a top level json array called `k8s_logs` which lets you specify log
  configuration for Kubernetes logs.

  For example, you could create a new config snippet containing the following values:

  ```
  {
    "k8s_logs": [
      {
        "k8s_pod_glob": "*nginx*",
        "attributes": {
          "parser": "nginxParser"
        }
      }
    ]
  }
  ```

  and any pod whose name matches the glob `*nginx*` will be configured to use the parser `nginxParser`.

  The log configuration snippet can contain the same configuration options as those from  [`logs`
  section](https://app.scalyr.com/help/scalyr-agent?#logUpload), with the exception that you don't need to specify a log
  path because the configuration will be applied based on whether pod metadata matches various glob patterns.

  You can currently specify glob patterns for the pod name, the pod namespace, and the name of the container specified
  in the k8s pod yaml using the fields `k8s_pod_glob`, `k8s_namespace_glob` and `k8s_container_glob` respectively.

  Each of these globs default to `*` (match everything), and a log config will only be applied if all three of these
  globs match for a specific container's logs.

  Only a single log config will be applied for any given container, and logs are matched on a "first come, first served"
  basis determined by the order in which they appear in the config file.  This means that you should define more
  specific config rules before more general ones.

  Here is a more complex log configuration that modifies the name of the logfile shown in the Scalyr UI, to include pod
  namespace and pod name, and that then also samples only 10% of any log messages that contain DEBUG:

  ```
  {
    "k8s_logs": [
      {
        // configure rename rule and sampling for myApp
        "k8s_pod_glob": "myApp*",
        "k8s_namespace_glob": "backend",
        "sampling_rules": [
          { match_expression: "DEBUG", sampling_rate: 0.1 }
        ],
        // also specify a rename rule
        "rename_logfile": "/k8s/${pod_namespace}/${pod_name}/${k8s_container_name}.log"
      },
      {
        // this configuration will match every other container because
        // k8s_pod_glob, k8s_namespace_glob and k8s_container_glob all default to `*`
        "rename_logfile": "/k8s/${pod_namespace}/${pod_name}/${k8s_container_name}.log"
      }
    ]
  }
  ```

  Note that for [`rename_logfile`](https://app.scalyr.com/help/scalyr-agent?#logFileRenaming) the field can contain one
  or more predefined variables which will be replaced at runtime with the appropriate values.  The variables currently
  allowed include:

  * `${pod_name}` - the name of the pod
  * `${pod_namespace}` - the namespace of the pod
  * `${k8s_container_name}` - the name of the container in the k8s pod spec
  * `${node_name}` - the name of the node
  * `${controller_name}` - the name of the controller running the pod (e.g. the deployment name, or the cronjob name and so on).
  * `${short_id}` the first 8 characters of the container's ID
  * `${container_id}` the full container ID
  * `${container_name}` the container name used by the container runtime
  * `${container_runtime}` the runtime used for this container (e.g. `docker`, `containerd` etc)

  If [pod annotations](https://app.scalyr.com/help/scalyr-agent-k8s?#annotations-config) are used to configure a pod,
  then any config option defined in the annotations will override the values specified in the `k8s_log` snippets.

## 2.1.6 "Rama" - June 4, 2020

* There are a number of new default overrides to increase Agent throughput:

  ```
  "max_allowed_request_size": 5900000
  "pipeline_threshold": 0
  "min_request_spacing_interval": 0.0
  "max_request_spacing_interval": 5.0
  "max_log_offset_size": 200000000
  "max_existing_log_offset_size": 200000000
  ```

  Increased throughput may result in a larger amount of logs uploaded to Scalyr if the Agent has been skipping logs
  before this upgrade, and as a result a larger bill.

  Increase to `max_allowed_request_size` may result in increased memory usage by the Agent, if this is an issue you may
  wish to revert to the legacy behavior as described below.

  If you are interested in relying on the legacy behavior, you may set the `max_send_rate_enforcement` option to
  `legacy` either by setting it in your `agent.json` configuration file, or by setting the
  `SCALYR_MAX_SEND_RATE_ENFORCEMENT` environment variable to `legacy`.

* The `max_send_rate_enforcement` option defaults to `"unlimited"`, which will not rate limit at all and have the above
  overrides in effect. You may also set it to a specific maximum upload rate, such as `2MB/s`.  The Agent will attempt
  to not exceed this rate by artificially delaying its upload requests.

  The format for specifying a maximum upload rate is: `"<rate><unit_numerator>/<unit_denominator>""`, where

  `<rate>` Accepts an integer or float value.

  `<unit_numerator>` Accepts one of bytes (`B`), kilobytes(`KB`), megabytes (`MB`), gigabytes (`GB`), and terabytes
  (`TB`). It also takes into account kibibytes(`KiB`), mebibytes (`MiB`), gibibytes (`GiB`), and tebibytes
  (`TiB`). To avoid confusion it only accepts units in bytes with a capital `B`, and not bits with a lowercase `b`.

  `<unit_denominator>` Accepts a unit of time, one of seconds (`s`), minutes (`m`), hours (`h`), days (`d`), and weeks
  (`w`).

  Other examples include: `1.5MB/s`, `5GB/d`, `200KiB/s`.

  Note, this will rate limit in terms of raw log bytes uploaded to Scalyr which may not be same as charged log volume
  if you have additional fields and other enrichments turned on.

## 2.1.3 "Orion" - May 1, 2020

* You may now restrict which namespaces for which logs and events are collected
  when using the Kubernetes and Kubernetes event monitor using the new `k8s_include_namespaces`
  top-level configuration option or its equivalent `SCALYR_K8S_INCLUDE_NAMESPACES` environment variable.

  To restrict the namespaces, set `SCALYR_K8S_INCLUDE_NAMESPACES` via your `scalyr-config` configmap.
  The value should be a comma-separated list of the namespaces for which you wish to collect logs and events.  For example,
  the following configures the Scalyr Agent to only collect from the `frontends` and `database` namespaces:

  ```
  SCALYR_K8S_INCLUDE_NAMESPACES: frontends,database
  ```

  Note, this option to defaults to `*` which indicates to include all namespaces.

  The `SCALYR_K8S_EXCLUDE_NAMESPACES` environment variable (or `k8s_exclude_namespaces` option) is applied after the
  `SCALYR_K8S_INCLUDE_NAMESPACES` option.  So, if you have a namespace listed in both `SCALYR_K8S_INCLUDE_NAMESPACES`
  and `SCALYR_K8S_EXCLUDE_NAMESPACES`, then it will not be included.

* By default, the Kubernetes monitor will now verify `https` connections made to the local Kubelet.  The connection
  is verified using the certificate authority configured via the service account's cert.  If this causes issues for
  your particular set up, you can either change which certificate is used to verify the connnection or disable verfication.

  To set the certificate used to verify, set `SCALYR_K8S_KUBELET_CA_CERT` in your `scalyr-config` configmap to
  the path of the certificate.  Be sure that path is properly mapped into the Scalyr Agent container's filesytem.

  To set disable verification, set `SCALYR_K8S_VERIFY_KUBELET_QUERIES` in your `scalyr-config` configmap to `false`

## 2.1.2 "Nostromo" - April 23, 2020

When running the agent with the `--no-fork` flag it will now output its logs to stdout as well as
the usual `agent.log` file. The output can be limited with the new top level configuration parameter
`stdout_severity` which requires a string value of a valid logging level, one of `NOTSET`, `DEBUG`,
`INFO`, `WARN`, `ERROR`, or `CRITICAL`. Only messages with a severity equal to or higher than this value
will be output to stdout. The equivalent environment variable for this configuration is `SCALYR_STDOUT_SEVERITY`.

## 2.1.1 "Millenium Falcon" - Mar 27, 2020

This release includes significant changes to the Scalyr Agent code base.  The release highlights
include:

* Support for Python 3 (Python 3.5 and higher) in addition to existing support for Python 2.6
  and 2.7.  See below for instructions on how to control which version of Python is used by
  the Scalyr Agent.
* This release is backward compatiable with previous Scalyr Agent releases with
  one exception related to Kubernetes.  The new install instructions for K8s creates
  the Scalyr Agent DaemonSet (and related resources) in the ``scalyr`` namespace
  instead of ``default``.  See below for instructions on how to upgrade an existing Scalyr
  Agent K8s instance.
* Updated K8s manifest files allowing rolling updates, persistence of checkpoint files, and
  customization via `kustomize`.
* Collection of two new metrics (``app.io.wait`` and ``app.mem.majflt``) in the
  ``linux_process_metrics`` monitor.  See below for instructions on disabling their collection.
* The ``/etc/init.d/scalyr-agent-2`` symlink is no longer marked as a conf
  file in the Debian package.  If you have created a customized version of this
  file, you will need to copy it before upgrading to this new version.

For additional changes, please read the detailed release notes below.

### Python 3 support

This release introduces support for Python 3 (Python 3.5 and higher). It means the agent now
supports Python 2.6, 2.7 and >= 3.5.

On package installation, the installer will try to find a suitable Python version which will
be used for running the agent. It defaults to Python 2 (``/usr/bin/env python2``), but if a
suitable Python 2 version is not found, it will try to use Python 3 if available (
``/usr/bin/env python3``) or Python (``/usr/bin/env python``) by default.

If you want to select a specific Python version you want to use to run the agent (e.g. you have
both Python 2 and Python 3 installed), you can do that using ``scalyr-switch-python`` tool
which ships with the agent.  It takes a single argument from the following values: ``default``,
``python2``, or ``python3``.  This will configure the Scalyr Agent to use ``/usr/bin/env python``,
``/usr/bin/env python2``, or ``/usr/bin/env python3`` respectively.

Selecting Python 2:

```bash
sudo scalyr-switch-python python2
sudo /etc/init.d/scalyr-agent-2 restart
```

Selecting Python 3:

```bash
sudo scalyr-switch-python python3
sudo /etc/init.d/scalyr-agent-2 restart
```

Keep in mind that you need to restart the agent after running the ``scalyr-switch-python``
command for the changes to take an effect.

### Upgrading an existing Scalyr Agent K8s instance to 2.1.1

Prior to release 2.1.1, the default Kubernetes manifest files created all Scalyr-related resources
(the API key secret, configmap, service account, and DaemonSet) in the ``default`` namespace.
As of the 2.1.1 relase, they are now created in the ``scalyr`` namespace.  You must take the
following actions to upgrade your existing Scalyr Agent K8s instance:

  1.  Create the ``scalyr`` namespace:

    kubectl create namespace scalyr

  2.  Copy your existing API key to the ``scalyr`` namespace:

    kubectl get secret scalyr-api-key --namespace=default --export -o yaml | kubectl apply -f - --namespace=scalyr

  3.  Copy your existing configmap to the ``scalyr`` namespace:

    kubectl get configmap scalyr-config --namespace=default --export -o yaml | kubectl apply -f - --namespace=scalyr

  4.  Delete the existing Scalyr Agent DaemonSet.

    kubectl delete -f https://raw.githubusercontent.com/scalyr/scalyr-agent-2/release/k8s/default-namespace/scalyr-agent-2.yaml

  5.  Create the Scalyr Agent service account and DaemonSet in the ``scalyr`` namespace.

    kubectl apply -f https://raw.githubusercontent.com/scalyr/scalyr-agent-2/release/k8s/no-kustomize/scalyr-service-account.yaml
    kubectl apply -f https://raw.githubusercontent.com/scalyr/scalyr-agent-2/release/k8s/no-kustomize/scalyr-agent-2.yaml

### Preventing collection of metrics using ``metric_name_blacklist``

This release adds new ``metric_name_blacklist`` monitor configuration option. With this
configuration option you can specify which metrics generated by the monitors should not
be logged and shipped to Scalyr.

For example, if you want to exclude ``app.io.wait`` and ``app.uptime`` metrics for the
built-in agent Linux process monitor, the agent configuration file would look like this:

```javascript
// This is only needed if you are changing settings for built-int agent process metrics
// monitor
implicit_agent_process_metrics_monitor: false,

monitors: [
  {
      "module": "scalyr_agent.builtin_monitors.linux_process_metrics",
      "id": "agent",
      "pid": "$$",
      "metric_name_blacklist": ["app.io.wait", "app.uptime"],
  },
]
```

### Controlling which JSON library is used

New ``json_library`` global configuration option has been added. With this option user can
explicitly select which JSON library to use when serializing and deserializing data.

By default, if ``ujson`` Python package is available, agent will try to use that and if it's not,
it will fall back to ``json`` library from Python standard library.

In addition to ``ujson`` and ``json`` libraries, ``orjson`` library is now also supported. This
library only supports Python 3, but offers significant performance improvements under some
scenarios.

To select ``orjson`` library, add the following line to your agent configuration file.

```javascript
"json_library": "orjson",
```

Keep in mind that ``ujson`` and ``orjson`` Python packages are not available by default and can
be installed using pip.

```bash
sudo pip install ujson
sudo pip install orjson
```

### Verbose status exported as JSON

The ``scalyr-agent-2 status -v`` command now also supports printing the output in a machine readable
(JSON) format.

Example usage:

```bash
# Print the output in JSON format
scalyr-agent-2 status -v --format=json

# Print the output in human readable format (default)
scalyr-agent-2 status -v --format=text
```

### New metrics for `linux_process_metrics` monitor

New ``app.io.wait`` and ``app.mem.majflt`` metric has been added to the Linux process metrics
monitor.

If you don't want this metric to be logged and shipped to Scalyr you can utilize new
``metric_name_blacklist`` config option as shown below:

```javascript
// This is only needed if you are changing settings for built-int agent process metrics
//monitor
implicit_agent_process_metrics_monitor: false,

monitors: [
  {
      "module": "scalyr_agent.builtin_monitors.linux_process_metrics",
      "id": "agent",
      "pid": "$$",
      "metric_name_blacklist": ["app.io.wait", "app.mem.majflt"],
  },
]
