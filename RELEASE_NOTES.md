# Release Notes

This document describes any large or breaking / backward incompatible changes made in a specific
Scalyr Agent release.

In case there is no entry for a specific release in this file, it means no large or backward
incompatible changes have been made in that release.

For a list of all the changes in a particular release, please refer to the changelog file -
https://github.com/scalyr/scalyr-agent-2/blob/master/CHANGELOG.md.

## 2.2.1 "Frosty"

* This release adds new Agent's `deb` and `rpm` packages - scalyr-agent-2-aio. This package is shipped with its own, independent 
  version of the Python interpreter and does not rely on system Python. The upgrade process to the new packages is 
  seamless for the majority of cases, but if you use custom monitors that require additional libraries, you will need to
  specify those requirements in new agent's configuration.
  
  When upgraded to a new version of the package, add required libraries to the file `/opt/scalyr-agent-2/etc/additional-requirements.txt` 
  and run command `/opt/scalyr-agent-2/bin/agent-libs-config initialize` to re-initialize requirements.
  See [CREATING_MONITORS](docs/CREATING_MONITORS.md#installing-additional-requirements-for-plugin) for more details.

## 2.1.38 "Zaotune" - Dec 1, 2022

* This release changes the Kubernetes monitor leader election algorithm to use the pods in the owning ReplicaSet or
  DaemonSet, formerly it used every node in the cluster.

  As a result two of the associated options have changed:
  - `leader_node` has been removed
  - `check_labels` now checks pod labels (formerly node labels)

* This release also updates the Kubernetes monitor to more accurately calculate used memory.

  Formerly `docker.mem.usage` was equal to `memory_stats.usage` now it it equal to `memory_stats.usage` minus
  `memory_stats.stats.cache` which represents file system cache usage.

## 2.1.21 "Ultramarine" - Jun 1, 2021

* This is the last release that still supports Python 2.6. This version of the agent will emit a
  warning if running under Python 2.6.

  Python 2.6 has been officially EOL / unsupported for more than 7 years now so you are strongly
  encouraged to use newer and supported version of Python 3. If you can't do that you can still
  this or one of the older release.

  Similar story for Python 2.7 which has been EOL for more than 1 year now. For the time being,
  agent still supports Python 2.7, but that support will be removed in the near future so you are
  strongly encouraged to upgrade to a more recent and supported Python 3 release.

## 2.1.19 "StarTram" - March 9, 2021

* This release add support for adding the Kubernetes container name as an attribute to all log lines ingested via the 
  Kubernetes monitor. You can include the container name as a log line attribute using the ${k8s_container_name} config 
  template syntax.
  
  One option to configure container name logging for a pod is through annotations, here is an example:

  Through CLI:
  
      kubectl annotate pod <pod name> --overwrite log.config.scalyr.com/attributes.container_name=\$\{k8s_container_name\}
  
  Through YAML:
  
      metadata:
         annotations:
            "log.config.scalyr.com/attributes.container_name": "\$\{k8s_container_name\}"
  
  Whichever pod has this annotation applied will then have the container name to the "container_name" field attached to 
  each log line.
  If you want to apply this configuration to all pods the Agent tracks you will need to add the configuration to the
  Agent deployment, instructions for this can be found [here](https://gist.github.com/yanscalyr/6f986f0475337509894bce03d0a81c11).
  
  
  Note, there will be charges for the extra bytes sent due to attaching the container name attribute.

## 2.1.16 "Lasso" - December 23, 2020

* This release fixes default permissions for the ``agent.json`` file and ``agent.d/`` directory
  and ``*.json`` files inside that directory and makes sure those files are not readable by
  others by default (aka "other" permission bit in octal notation for that file is ``0`` in case
  of a file and ``1`` in case of a directory).

  In the previous releases, ``agent.json`` file was readable by others by default which means if a
  user didn't explicitly lock down and change the permission of that file after installation,
  other users who have access to the system where the agent is running on could potentially read
  that file and access information such as the API key which is used to send / upload logs to
  Scalyr.

  This issue only affects users which run agent on servers with multiple users. Container
  installations (Docker, Kubernetes) are single user by default so those are not affected.

  This issue also doesn't affect any installations which use a configuration management tool such
  as Ansible, Chef, Puppet, Terraform or similar to manage the config file content and permissions.

  In fact, using configuration management tool to manage configuration file access and locking down
  the permission is the best practice and recommended approach by us.

  As part of the fix, agent will now lock down those file permissions and also fix them on upgrade
  as part of the post install step for the existing files and installations.

  If you intentionally changed "other" permission bits for any of those files to something else than
  ``0``, you will need to change it again after installing / upgrading the agent.

  If you believe you may be affected, we recommend revoking the old write API key used to send logs
  and generating a new one.

  Keep in mind that the API key used by the agent is a write one which only has access to send logs
  and nothing else.

  It's also worth noting that this only affects agent.json file bundled with the default agent
  installation. If you manually removed that file and created a new one, that is out of the agent
  scope and domain of ``umask`` on Linux.

  On Windows, permissions are not rectified automatically because some users run the agent under a
  custom non-Administrator user account so automatically fixing the permissions would break this
  scenario.

  In this case, user can manually run ``scalyr-agent-2-config.exe`` as administrator to revoke
  permissions for "Users" group for the agent config.

  ```powershell
  & "C:\Program Files (x86)\Scalyr\config\scalyr-agent-2-config.exe" "--fix-config-permissions"
  ```

  Keep in mind that after running this script you need to use Administrator account to grant read
  permissions to user account which is used to run the agent in case this user is not Administrator
  or not a member of Administrators group.

## 2.1.15 "Endora" - December 15, 2020

### Increase Scalyr Agent upload throughput, using multiple Scalyr team accounts. (BETA)

**Note, the use of multiple sessions to upload logs to Scalyr is currently in beta. Please be sure to test use of this
 feature before deploying it widely in your production environment.**

#### Multi-worker configuration

##### Use multiple workers

In a default configuration, the Scalyr Agent creates a single session with the Scalyr servers to upload all collected logs.
This typically performs well enough for most users, but at some point, the log generation rate can exceed
a single session's capacity (typically 2 to 8 MB/s depending on line size and other factors).
You may increase overall throughput by increasing the number of sessions using the ``default_workers_per_pi_key`` option
in the agent configuration. By default, the option value is ``1``.
Each worker is assigned a subset of the log files to be uploaded, so increasing the number of workers,
increasing the overall upload throughput.

##### Use multiprocess workers

Even if the workers create separate sessions, by default, they will still run within the same Python process,
limiting their resources to a single CPU core.
This may become a problem when the number of log files is too big to be handled by a single CPU core, especially if
additional features (such as [sampling](https://app.scalyr.com/help/scalyr-agent?teamToken=7bn1PMhjS%2F8335sB6vgDcQ--#filter)
and [redaction](/https://app.scalyr.com/help/scalyr-agent?teamToken=7bn1PMhjS%2F8335sB6vgDcQ--#filter) rules)
are enabled.

This limitation can be addressed using the ``use_multiprocess_copying_workers`` option in the agent configuration.
By default, the option value is ``false``

##### Recommended configuration

To significantly increase overall throughput, we recommend you set the default workers per API key to ``3``, as well
as turn on multiprocess workers. The following configuration shows an example of setting both of those options.
```
{
    "use_multiprocess_copying_workers": true,
    "default_workers_per_api_key": 3,
    "api_key": "<you_key>",
    "logs": [
      {
        "path": "/var/log/app/*.log",
      },
    ]

}
```

If you are using Kubernetes, you will find it easier to configure these settings using their corresponding environment
variables in the configmap for the Scalyr Agent DaemonSet:

```
SCALYR_USE_MULTIPROCESS_COPYING_WORKERS=true
SCALYR_DEFAULT_WORKERS_PER_API_KEY=3
```

### Multiple API keys

The multiple API keys feature is useful when it is necessary to upload particular log files using a different API keys,
for instance, to upload to different Scalyr team accounts.

#### Adding new API keys

Each additional API key has to be defined in the list in the ``api_keys`` section.

```
"api_keys": [
     {
         "api_key": "<your_second_key>",
         "id": "frontend_team",
     },
     {
         "api_key": "<your_third_key>",
         "id": "backend_team",
     }
]
```

Possible options for each element of the ``api_keys`` list:

| Field   | required | Description                                                                                                                                            |
|---------|----------|--------------------------------------------------------------------------------------------------------------------------------------------------------|
| api_key | yes      | The API key token.                                                                                                                                     |
| id      | yes      | The identifier of the API key. Must be unique. String.                                                                                                 |
| workers | no       | The number of [workers](#multi-worker-configuration) for the API key. By default it has the same value as the `default_workers_per_api_key` [option](#multi-worker-configuration). |

You may also split the definition of the api_keys field across [multiple configuration files](https://app.scalyr.com/help/scalyr-agent?teamToken=7bn1PMhjS%2F8335sB6vgDcQ--#modularConfig)
in the agent.d directory. The agent will join together all entries in all api_keys fields defined.

NOTE: The "main" API key, which is defined in the ``api_key`` section, also has it's own implicit identifier - ``"default"``.

The identifier ``"default"`` is reserved by the "main" API key and can not be used by other API keys. For example, the next configuration is invalid.
```
{
    "api_key": "<main_key>",
    "api_keys": [
         {
             "api_key": "<second_key>",
             "id": "default",  // WRONG, the <main_key> API key already has the identifier "default".
         },
    ]
}
```

As an exception, the ``"default"`` identifier can be used with the same ``api_key`` value as in the "main" ``api_key`` section to change default options for this API key.

```
{
    "api_key": "<main_key>",
    "api_keys": [
         {
             "api_key": "<main_key>", // the same API key as in the "api_key" section.
             "id": "default",
             "workers": 3 // change the workers number from default - 1 to 3.
         },
         {
             "api_key": "<second_key>",
             "id": "second",
         },
    ]
}
```

#### Associating logs with API keys

Each element of the ``logs`` section can be associated with a particular API key by specifying the ``api_key_id`` field.

NOTE: If the ``api_key_id`` is omitted, then the ``default`` API key is used.
```
"logs": [
    {
       "path": "/var/log/frontend/*.log",
       "api_key_id": "frontend_team" // the API key with identifier - "frontend_team" is used.
    }
    {
       "path": "/var/log/backend/*.log"
       // the "api_key_id" is omitted, the API key with "default" identifier is used.
    }
]
```

### Linux system metrics monitor improved

 Linux system metrics monitor now ignores the following special mounts points by default:
``/sys/*``, ``/dev*``, ``/run*``.

  In most cases users just want to monitor block and inodes usage for actual data partitions
  and not other special partitions.

 If you want to preserve the old behavior and capture ``df.*`` metrics for those mounts points,
 you can configure ``ignore_mounts`` monitor option like this:

 ```javascript
    ...
    monitors: [
        {
            module: "scalyr_agent.builtin_monitors.linux_system_metrics",
            ignore_mounts: [],
        }
    ],
    implicit_metric_monitor: false,
    ...
 ```

   Keep in mind that ``linux_system_metrics`` monitor is special since it's enabled automatically
   by default so if you want to specify custom options for it, you need to add
   ``implicit_metric_monitor: false,`` option to the config as well.

## 2.1.8 "Titan" - August 3, 2020

* The `status -v` and the new `status -H` command contain health check information and will have a return code
 of `2` if the health check is failing.

 The health check considers the time since the Agent last attempted to upload logs. These attempts don't need to
 succeed to be considered healthy. The default time before the Agent is considered unhealthy after not making any
 attempts is `60.0` seconds. This can be changed with the `healthy_max_time_since_last_copy_attempt` configuration
 option.

 The Kubernetes yaml has been updated to make use of this as a liveliness check:

 ```
        livenessProbe:
          exec:
            command:
            - scalyr-agent-2
            - status
            - -H
          initialDelaySeconds: 60
          periodSeconds: 60
 ```

 Health will be checked one minute after pod startup and every minute after that, with a failed check resulting in a
 pod restart.

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

If you are using a custom Docker image to run the Scalyr agent in Docker or Kubernetes and this may result in additional
logs to `stdout` due to usually running with the `--no-fork` flag. If you wish to avoid this configure
`stdout_severity` as `ERROR`, this is the configuration for the official Agent Docker image, see [here](https://github.com/scalyr/scalyr-agent-2/blob/7e50025373e1a70e87a2e8cb95e863cf28c1786e/docker/Dockerfile.k8s#L19).

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
