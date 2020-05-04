# Release Notes

## in development

* We now default to ``zstandard`` compression algorithm for compressing data which is sent to
  Scalyr on servers where ``zstandard`` Python library is available.

  Previously we used ``deflate`` with a compression level of ``9``. For most workloads / datasets,
  ``zstandard`` is about 5-10x faster / more CPU efficient than deflate and it also results in a
  slightly better compression ratio (it depends on data which is compressed, but for access log like
  log files, it results in around 5%-10% better compression ratio).

  If for some reason you want to switch back to deflate, you can do that by adding the following line
  to your scalyr agent config (``/etc/scalyr-agent-2/agent.json``):

  ```javascript
  compression_type: "deflate"
  ```

  If you want to use zstandard compression algorithm on servers where ``zstandard`` Python library
  is not available, you can do that by installing the library using pip:

  ```bash
  # At the time of this writting the latest version which we performed extensive testings with was
  # 0.13.0
  pip install zstandard
  ```

  And restarting the agent:

  ```bash
  /etc/init.d/scalyr-agent-2 restart
  ```

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
