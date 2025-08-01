Scalyr Agent 2 Changes By Release
=================================

## 2.2.19 "Yvette" - Jul 28, 2025
<!---
Packaged by Joseph Makar <joseph.makar@sentinelone.com> on Jul 28, 2025 00:00 -0800
--->

* Introduced a new syslog monitor config option `unique_file_log_rotation` to support log rotation in Windows hosts

## 2.2.18 "Zack" - Nov 5, 2024
<!---
Packaged by Ales Novak <ales.novak@sentinelone.com> on Nov 5, 2024 00:00 -0800
--->

Changes:
* Introducing a a new config key `agent_status_timeout` and setting it to 30s by default. Until version 2.2.17 it was hardcoded to 5 seconds.

Fixes:
* Fixed a bug where pod logs were removed from ingestion because of a temporrary K8s API error and the agent was not able to add them again.

## 2.2.17 "Sinthia" - Sep 17, 2024
<!---
Packaged by Ales Novak <ales.novak@sentinelone.com> on Sep 17, 2024 00:00 -0800
--->

Changes:
* Several packages were upgraded to mitigate vulnerabilities - orjson==3.10.7, PyMySQL==1.1.1
* Unused root CA file scalyr_agent_ca_root was removed
* Alpine base image upgraded to 2.19.4

Fixes:
* Added safety check when handling pending addEvents task to handle the following error: `AttributeError: 'AddEventsTask' object has no attribute '_CopyingManagerWorkerSession__receive_response_status'`
* Added missing zstandard library to alpine image

## 2.2.16 "Lenny" - May 29, 2024
<!---
Packaged by Ales Novak <ales.novak@sentinelone.com> on May 29, 2024 00:00 -0800
--->

Changes:
* Fixed steady growth of memory usage of Syslog Monitor. syslog_processing_thread_count can be used to limit the number of threads and memory consumption.
* Added the max_allowed_checkpoint_age option to allow configuring the checkpoint age (default 15 minutes), useful for agents monitoring a large number of short-lived logs
* Added the Kubernetes monitor k8s_cri_query_filesystem_retain_not_found option to disable caching info about pods that are dead (default is true), useful for agents that monitor clusters whose pods are not cleaned up frequently

## 2.2.15 "Jain" - May 20, 2024
<!---
Packaged by Ales Novak <ales.novak@sentinelone.com> on May 20, 2024 00:00 -0800
--->

Features:
Ability to ignore k8s labels (https://github.com/scalyr/scalyr-agent-2/issues/1213).
A user can now define glob filters for including and excluding container and controller labels in logs.
For label to be included it needs to match one of the globs in k8s_label_include_globs and none of the globs in k8s_label_exclude_globs.

From documentation:
| k8s_label_include_globs | Optional, (defaults to ['*']). Specifies a list of K8s labels to be added to logs. |
| k8s_label_exclude_globs | Optional, (defaults to []]). Specifies a list of K8s labels to be ignored and not added to logs. |

Follows the same logic as label_include_globs and label_exclude_globs from the docker_monitor.

## 2.2.14 "Tycho" - May 6, 2024
<!---
Packaged by Ales Novak <ales.novak@sentinelone.com> on May 6, 2024 00:00 -0800
--->

Changes:
Support sending events to multiple Dataset accounts via K8s annotations. This feature was updated to use secrets from the same namespace as the pod and hierarchy of default secrets were added: default secret -> namespace secret -> pod secret -> container secret.
See [kubernetes_monitor.md](docs/monitors/kubernetes_monitor.md) for documentation.

## 2.2.13 "Killian" - Mar 30, 2024
<!---
Packaged by Ales Novak <ales.novak@sentinelone.com> on Mar 30, 2024 00:00 -0800
--->

Feature:
* Kubernetes Monitor - when K8s Pod API returnes 404, the logs are ingested based on SCALYR_K8S_INCLUDE_ALL_CONTAINERS regardless of pods annotations. Short-lived pods are usually affected.


## 2.2.12 "Gizmo" - Feb 29, 2024
<!---
Packaged by Ales Novak <ales.novak@sentinelone.com> on Feb 29, 2024 00:00 -0800
--->

Feature:
* Support sending events to multiple Dataset accounts via K8s annotations. See [kubernetes_monitor.md](docs/monitors/kubernetes_monitor.md) for documentation.

## 2.2.11 "Maxson" - Feb 7, 2024
<!---
Packaged by Ales Novak <ales.novak@sentinelone.com> on Feb 7, 2024 00:00 -0800
--->

Security fix:
* Alpine image upgraded to 3.19.1 to mitigate [CVE-2023-7104](https://www.cve.org/CVERecord?id=CVE-2023-7104) and [CVE-2023-5363](https://www.cve.org/CVERecord?id=CVE-2023-5363)

## 2.2.10 "Aradesh" - Feb 5, 2024
<!---
Packaged by Ales Novak <ales.novak@sentinelone.com> on Feb 5, 2024 00:00 -0800
--->

Improvement:
* Windows Event Log Monitor - EventID field has been expanded into three fields. Until now EventID from the Windows Event Log was represented only by EventID field computed the following way win32api.MAKELONG(EventID, EventIDQualifiers). EventID and EventIDQualifiers now hold the values from the Windows Event Log without any modification and InstanceID is computed from EventID and EventIDQualifiers as described above.

Fix:
* Missing monitor field added to the event data sent by Syslog Monitor. The following field was added - ‘monitor’:'agentSyslog'.

## 2.2.9 "Tandi" - Jan 11, 2024
<!---
Packaged by Ales Novak <ales.novak@sentinelone.com> on Jan 11, 2024 00:00 -0800
--->

Feature:
* Support for CRI multi lines - implementing support for the following format: https://github.com/kubernetes/design-proposals-archive/blob/main/node/kubelet-cri-logging.md

Fix:
* Python2 suport for Syslog monitor fixed

Security Fix:
* Alpine image upgraded from 3.18.13 to 3.18.14 to fix recently found vulnerabilities

## 2.2.8 "Marcus" - Nov 20, 2023
<!---
Packaged by Ales Novak <ales.novak@sentinelone.com> on Nov 20, 2023 00:00 -0800
--->

Features:
* Added allow_http_monitors root configuration option. If true it forces monitors to use https instead of http where relevant. By default true for fips docker images, false otherwise.

Bug fixes:
* Tls certificate handling defect in 2.2.4 - https://github.com/scalyr/scalyr-agent-2/issues/1199
* Python2 support fixed (broken with version 2.2.7)


## 2.2.7 "Zeratul" - Nov 6, 2023
<!---
Packaged by Ales Novak <ales.novak@sentinelone.com> on Nov 6, 2023 00:00 -0800
--->

* SCALYR_K8S_INCLUDE_ALL_CONTAINERS evironment flag fix -  When the K8s Pod API returned 404, the logs were being imported without a label marking the pod as included.
* Base Ubuntu Fips image was upgraded to 2.0.32
* Syslog Monitor uses a thread pool to process requests

## 2.2.6 "Trégor" - Oct 11, 2023
<!---
Packaged by Ales Novak <ales.novak@sentinelone.com> on Oct 11, 2023 00:00 -0800
--->

Windows:
* Support execution as any administrator account

Other:
* Add missing CA root certificates for FedRAMP environments (DigiCert Global CA root, DigiCert Global G2 CA root, GoDaddy CA root).
* Alpine base image upgraded to 3.8.13

## 2.2.4 "Trillian" - Aug 14, 2023
<!---
Packaged by Ales Novak <ales.novak@sentinelone.com> on Aug 14, 2023 00:00 -0800
--->

Docker Images / Kubernetes:
* Kubernetes and Docker images switched from Debian to Ubuntu. Python version used in those images now matches Python in this distribution.
* Upgraded bundled Python dependencies to the latest stable versions to include all the latest security fixes (requests==2.28,1, pysnmp==4.4.12, docker==6.1.3)

## 2.2.3 "Elloria" - Jun 22, 2023
<!---
Packaged by Arthur Kamalov <arthurk@sentinelone.com> on Jun 22, 2023 00:00 -0800
--->

Kubernetes:
* Fix a bug with Kubernetes Events monitor not emitting events for `CronJob` objects when using Kubernetes >= 1.25.0. The bug was related to the API endpoint being promoted from `v1beta` to `stable`. The code has been updated to support both locations - old one (beta) and the new one (stable).
* Update Kubernetes monitor to also log the value of `SCALYR_COMPRESSION_LEVEL` environment variable on start up. Contributed by @MichalKoziorowski-TomTom #1104.

## 2.2.2 "Pollux" - Apr 26, 2023
<!---
Packaged by Arthur Kamalov <arthurk@sentinelone.com> on Apr 26, 2023 00:00 -0800
--->

Improvements:
* Support SSL connections to PostgreSQL

Kubernetes:
* Kubernetes ClusterRole resource definition now includes Argo Rollouts. The agent won't receive permission errors anymore when it interrogates Argo Rollout resources.

## 2.2.1 "Frosty" - Mar 29, 2023
<!---
Packaged by Arthur Kamalov <arthurk@sentinelone.com> on Jan 19, 2023 00:00 -0800
--->

Other:
* Linux `deb` and `rpm` packages are now shipped with its own Python interpreter, so agent does not have to rely on system Python interpreter anymore. Please refer to the RELEASE_NOTES document, for more information.
* The PostgreSQL monitor now supports connecting to servers over SSL. Configure the monitor with the setting `use_ssl` set to `True` to enable this.

Bug fixes:
* Fix bug in the Docker monitor which would, under some edge cases, cause a specific log messages to be logged very often and as such, exhausting the CPU cycles available to the Docker monitor.

## 2.1.40 "Onone" - Jan 19, 2023
<!---
Packaged by Arthur Kamalov <arthurk@sentinelone.com> on Jan 19, 2023 00:00 -0800
--->

Docker Images / Kubernetes:
* Docker images now are built against Python:3.8.16 image. Debian and Alpine based Docker images have also been updated to include all the latest security updates for the system packages.

## 2.1.39 "Hroderich" - December 15, 2022
<!---
Packaged by Dominic LoBue <dominicl@sentinelone.com> on Dec 15, 2022 00:00 -0800
--->

Kubernetes:
* Support ``Rollout`` controllers from argo-rollouts as a source of server metadata with which to annotate events.

## 2.1.38 "Zaotune" - December 1, 2022
<!---
Packaged by Joseph Makar <joseph.makar@sentinelone.com> on Dec 1, 2022 00:00 -0800
--->

Kubernetes:
* Add ``securityContext.allowPrivilegeEscalation: false`` annotation to the Scalyr Agent DaemonSet container specification.
* Fix bug that caused logging of the Kubernetes cache stats to agent status.
* More accurate docker.mem.usage metric (no longer includes filesystem cache).
* Monitor leader election algorithm now uses pods in the owning ReplicaSet or DaemonSet.

Windows:
* Add support for placeholder parameter (ie %%1234) replacement in event data.

Other
* Added support for ``--debug`` flag to the scalyr-agent-2 status command. When this flag is used, agent prints additional debug related information with the status output. NOTE: Right now it's only supported with the healthcheck option (``--health_check``, ``-H``).

## 2.1.37 "Penvolea" - October 17, 2022
<!---
Packaged by Joseph Makar <joseph.makar@sentinelone.com> on Oct 17, 2022 12:31 -0800
--->

Kubernetes:
* Fix a bug / edge case in the Kubernetes caching PodProcessor code which could cause an agent to get stuck in an infinite loop when processing controllers which have a custom Kind which is not supported by the agent defined. Contributed by @xdvpser #998 #999.
* Allows user to configure Docker client library connection timeout and maximum connection pool size when using Docker container enumerator via new `k8s_docker_client_timeout` and `k8s_docker_client_max_pool_size` config option.

Docker Images:
* Upgrade Linux Docker images to use Python 3.8.14.
* Upgrade docker-py dependency to v6.0.0.
* Upgrade orjson and yappi dependency to the latest stable version (3.8.0 and 1.3.6).

Windows:
* Upgrade agent Windows binary to use Python 3.10.7.
* Fix a bug where under some scenarios log record would not contain "message" attribute.

Other:
* Log how long it took (in milliseconds) to read data from socket when we encounter HTTP errors (e.g. connection aborted, connection reset, etc.).
* Log which version of docker-py and requests Python library is being used so it's easier to spot if bundled / vendored or system version is used.

## 2.1.36 "Corrntos" - September 15, 2022
<!---
Packaged by Joseph Makar <joseph.makar@sentinelone.com> on Sep 17, 2022 12:31 -0800
--->

Windows:
* The monitor field is set to ``windows_event_log_monitor`` in the ``windows_event_log`` monitor if the ``json`` config option is true.
* Proper handling of forwarded windows events (ie handling of EvtOpenPublisherMetadata exceptions) in the ``windows_event_log`` monitor.

## 2.1.35 "Xabboaturn" - September 8, 2022
<!---
Packaged by Joseph Makar <joseph.makar@sentinelone.com> on Sep 17, 2022 12:30 -0800
--->

Windows:
* More sophisticated handling of array-based (event field) names in ``windows_event_log`` monitor.

## 2.1.34 "Tadongolia" - August 30, 2022
<!---
Packaged by Dominic LoBue <dominicl@sentinelone.com> on Sep 17, 2022 12:29 -0800
--->

Improvements:
* Add support for tracemalloc based memory profiler (``"memory_profiler": "tracemalloc"`` config option). Keep in mind that tracemalloc is only available when running the agent under >= Python 3.5.
* Add new ``memory_profiler_max_items`` config option which sets maximum number of items by memory usage reported by the memory profiler.
* Add new ``enable_cpu_profiling`` and ``enable_memory_profiling`` config option with which user can enable either CPU or memory profiler, or both. Existing ``enable_profiling`` config behavior didn't change and setting it to ``true`` will enable both profilers (CPU and memory).
* Allow user to specify additional trace filters (path globs) for tracemalloc memory profiler using ``memory_profiler_ignore_path_globs`` config option. (e.g. ``memory_profiler_ignore_path_globs: ["**/scalyr_agent/util.py", "**/scalyr_agent/json_lib/**"]``).
* Update syslog_monitor to ignore errors when decoding data from bytes into unicode if data falls outside of the utf-8 range.

Bug fixes:
* Update windows_event_log_monitor to handle embedded double quotes in fields.

## 2.1.33 "Chaavis" - August 17, 2022
<!---
Packaged by Dominic LoBue <dominicl@sentinelone.com> on Aug 17, 2022 12:29 -0800
--->

Improvements:
* Add option ``stop_agent_on_failure`` for each monitor's configuration. If ``true``, the agent will stop if the monitor fails. For Kubernetes deployments this is `true` by default for the Kubernetes monitor (``scalyr_agent.builtin_monitors.kubernetes_monitor``). The agent's pod will restart if the monitor fails.

Kubernetes Explorer:
* Update code to calculate per second rate for various metrics used by Kubernetes Explorer on the client (agent) side. This may result in slight CPU and memory usage increase when using Kubernetes Explorer functionality.

Windows:
* Add new ``json`` config option to the ``windows_event_log`` monitor. When this option is set to true, events are formatted as JSON.

Other:
* Changed log severity level from ``ERROR`` to ``WARNING`` for non-fatal and temporary network client error.
* Update agent packages to also bundle new LetsEncrypt CA root certificate (ISRG Root X2). Some of the environments use LetsEncrypt issued certificates.
* Update agent code base to log a warning with the server side SSL certificate in PEM format on SSL certificate validation failure for easier troubleshooting.
* Upgrade various bundled dependencies (orjson, docker).

Bug fixes:
* Set new ``stop_agent_on_failure`` monitor config option to ``true`` in the agent Docker image for Kubernetes deployments. Solves an issue, present in some rare edge cases, where the Kubernetes Monitor (``scalyr_agent.builtin_monitors.kubernetes_monitor``) exits, but the agent continues to run. The agent's pod will restart if the monitor fails.

## 2.1.32 "Occao" - July 27, 2022

<!---
Packaged by Dominic LoBue <dominicl@sentinelone.com> on Jul 27, 2022 12:29 -0800
--->

Windows:
* Fix bug in Windows System Metrics and Windows Process Metrics monitor where user wasn't able to override / change default sampling rating of 30 seconds (``sample_interval`` monitor config option).
* Update Windows Process Metrics monitor to log a message in case process with the specified pid / command line string is not found when retrieving process metrics.
* Update Windows Process Metrics monitor to throw an error in case invalid monitor configuration is specified (neither "pid" nor "commandline" config option is specified or both config options which are mutually exclusive are specified).

Bug fixes:
* Fix a bug with ``import_vars`` functionality which didn't work correctly when the same variable name prefix was used (e.g. ``SCALYR_FOO_TEST``, ``SCALYR_FOO``).
* Fix a bug with handling the log file of the Kubernetes Event Monitor twice, which led to duplication in the agent's status.
* Fix a bug in scalyr-agent-2-config ``--export-config``, ``import-config`` options caused by Python 2 and 3 code incompatibility.
* Fix a bug with the wrong executable ``scalyr-agent-2-config`` in Docker and Kubernetes, due to which it could not be used.

Docker images:
* Upgrade various dependencies: orjson, requests, zstandard, lz4, docker.

Other:
* Support for Python 2.6 has been dropped.
* Support for ``ujson`` JSON library (``json_library`` configuration option) has been removed in favor of ``orjson``.
* Update agent log messages to include full name of the module which produced the message.

## 2.1.31 "Irati" - Jun 28, 2022

<!---
Packaged by Dominic LoBue <dominicl@sentinelone.com> on Jun 28, 2022 12:29 -0800
--->

Windows:
* Update base Python interpreter for Windows MSI package from 3.8 to 3.10.
* Upgrade various bundled dependencies (pywin32, orjson, urllib3, six).

Bug fixes:
* Fix a regression introduced in v2.1.29 which would cause the agent to inadvertently skip connectivity check on startup.
* Default value for ``check_remote_if_no_tty`` config option is ``False``. Previously the changelog entry incorrectly stated it defaults to ``True``. This means that a connectivity check is not performed on startup if tty is not available.
* Fix a bug in syslog monitor on Windows under Python 3 which would prevent TCP handler from working.
* Fixed agent checkpoint selection bug that could cause old log files to be re-uploaded.
* Small bug with command line argument parsing for the Agent. Agent raised unhandled exception instead of normal argparse error message when agent main command wasn't specified.
* Fix a bug in the Agent's custom JSON parser, which did not raise error on unexpected ending of the JSON document which might be caused by a JSON syntax error.

Docker images:
* Upgrade orjson dependency

Other:
* Monitor ``emit_value()`` method now correctly sanitizes / escapes metric field names which are "reserved" (logfile, metric, value, serverHost, instance, severity). This is done to prevent possible collisions with special / reserved metric event attribute names which could cause issues with some queries. Metric field names which are escaped get added ``_`` suffix (e.g. ``metric`` becomes ``metric_``).
* Upgrade dependency ``requests`` library to 2.25.1.
* Failed docker container metric status requests from the docker client now logged as warnings instead of errors.

## 2.1.30 "Heturn" - May 17, 2022

<!---
Packaged by Arthur Kamalov <arthurk@sentinelone.com> on May 17, 2022 23:04 -0800
--->

Kubernetes:
* Agent has been updated to periodically try to re-read Kubernetes authentication token value from ``/var/run/secrets/kubernetes.io/serviceaccount/token`` file on disk (every 5 minutes by default). This way agent also supports Kubernetes deployments where token files are periodically automatically refreshed / rotated (e.g. https://kubernetes.io/docs/tasks/configure-pod-container/configure-service-account/#service-account-token-volume-projection).
* Fix an edge case with handling empty ``resourceVersion`` value in the Kubernetes Events Monitor.

Docker images:
* Upgrade Python used by Docker images from 3.8.12 to 3.8.13.

Bug fixes:
* Fix minimum Python version detection in the deb/rpm package pre/post install script and make sure agent packages also support Python >= 3.10 (e.g. Ubuntu 22.04). Contributed by Arkadiusz Skalski (@askalski85).

Other:
* Update the code to log connection related errors which are retried and are not fatal under WARNING instead of ERROR log level.
* Update agent start up log message to use format which is supported by the agent message parser.

## 2.1.29 "Auter" - Mar 15, 2022

<!---
Packaged by Arthur Kamalov <arthurk@sentinelone.com> on Mar 15, 2022 23:04 -0800
--->

Docker images:
* Kubernetes Docker image (``scalyr-k8s-agent``) has been updated to ignore checkpoint data for ephemeral log files (anything matching ``/var/log/scalyr-agent-2/*.log``) on agent start up. Those log files are ephemeral (aka only available during container runtime) which means we don't want to re-use checkpoints for those log files across pod restarts (recreations). Previously, those checkpoints were preserved across restarts which meant that on subsequent pod restarts some of the early internal agent log messages produced by the agent during start up phase were not ingested.

Bug fixes:
* Kubernetes monitor now correctly dynamically detects pod metadata changes (e.g. annotations) when using containerd runtime. Previously metadata updates were not detected dynamically which meant agent needed to be restarted to pick up any metadata changes (such as Scalyr related annotations).

## 2.1.28 "Dryria" - Feb 23, 2022

<!---
Packaged by Arthur Kamalov <arthurk@sentinelone.com> on Feb 23, 2022 23:04 -0800
--->

Improvements:
* Docker and Kubernetes monitors now support parsing date and time information from the container log lines with custom timezones (aka non UTC).

Docker images:
* Docker images now include udatetime time dependency which should speed up parsing date and time information from Docker container log lines.
* Upgrade zstandard and orjson dependency used by the Docker image.

## 2.1.27 "Thonia" - Jan 27, 2022

<!---
Packaged by Arthur Kamalov <arthurk@sentinelone.com> on Jan 27, 2022 23:04 -0800
--->

Improvements:
* Add new ``debug_level_logger_names`` config option. With this config option user can specify a list of logger names for which to set debug log level for. Previously user could only set debug level for all the loggers. This comes handy when we want to set debug level for a single of subset of loggers (e.g. for a single monitor).
* If profiling is enabled (``enable_profiling`` configuration option), memory profiling data will be ingested by default (CPU profiling data was already being ingested when profiling was enabled, but not memory one).

Docker images:
* Upgrade Python used by Docker images from 3.8.10 to 3.8.12.
* Base distribution version for non slim Alpine Linux based images has been upgraded from Debian Buster (10) to Debian Bullseye (11).

Bug fixes:
* Fix a bug with the URL monitor not working correctly with POST methods when ``request_data`` was specified under Python 3.

## 2.1.26 "Yavin" - Jan 12, 2022

<!---
Packaged by Arthur Kamalov <arthurk@sentinelone.com> on Jan 12, 2022 23:04 -0800
--->

Improvements:
* Add ``collect_replica_metrics`` config option to the MySQL monitor. When this option is set to False (for backward compatibility reasons it defaults to True) we don't try to collect replica metrics and as such, user which is used to connect to the database only needs PROCESS permissions and nothing else.
* Add support for specifying new ``server_url`` config option for each session worker. This allows user to configure different session workers to use different server urls (e.g. some workers send data to agent.scalyr.com and other send data to eu.scalyr.com).

Other:
* Update agent to also log response ``message`` field value when we receive ``error/client/badParam`` status code from the API to make troubleshooting easier.

Docker Images:
* Docker images now utilize Python 3.8 (in the past they used Python 2.7).
* Docker images are now also produced and pushed to the registry for the ``linux/arm64`` and ``linux/arm/v7`` architecture.
* Docker image now includes ``pympler`` dependency by default. This means memory profiling can be enabled via the agent configuration option without the need to modify and re-build the Docker image.
* ``ujson`` dependency has been removed from the Docker image in favor of ``orjson`` which is more performant and now used by default.
* Alpine based Docker images which are 50% small than regular Debian bullseye-slim based ones are now available. Alpine based images contains ``-alpine`` tag name suffix.

## 2.1.25 "Hamarus" - Nov 17, 2021

<!---
Packaged by Yan Shnayder <yans@sentinelone.com> on Nov 17, 2021 14:10 -0800
--->

Other:
* Added a LetsEncrypt root certificate to the Agent's included certificate bundle.
* Update Kubernetes monitor to log a message under INFO log level that some container level metrics won't be available when detected runtime is ``containerd`` and not ``docker`` and container level metrics reporting is enabled.

Bug fixes:
* Fix plaintext mode in the Graphite monitor.
* Update Linux system metric monitor so it doesn't print an error and ignores ``/proc/net/netstat`` lines we don't support metrics for.

## 2.1.24 "Xuntian" - Oct 26, 2021

<!---
Packaged by Yan Shnayder <yans@sentinelone.com> on Oct 26, 2021 14:10 -0800
--->

Improvements:
* Implemented optional line merging when running in Docker based Kubernetes to work around Docker's own 16KB line length limit. Use the ``merge_json_parsed_lines`` config option or ``SCALYR_MERGE_JSON_PARSED_LINES`` environment variable to enable this functionality.

Bug fixes:
* Update agent to throw more user-friendly error when we fail to parse fragment file due to invalid content.

## 2.1.23 "Whipple" - Sept 16, 2021

<!---
Packaged by Steven Czerwinski <stevenc@sentinelone.com> on Sep 16, 2021 10:10 -0800
--->

Bug fixes:
* Fix docker container builder scripts to only use `buildx` if it is available.
* Fix memory leak in the Syslog monitor which is caused by a bug in standard TCP/UDP servers in Python 3 (https://bugs.python.org/issue37193). The version of Python for Windows was updated to 3.8.10. For Linux users, who run agent on Python 3 and use Syslog monitor, it is also recommended to check if their Python 3 installation is up to date and has appropriate bug fixes.
* Fix bug in the copying manager which works with monitor (such as Docker or Syslog monitor). This bug might cause re-uploading of the old log messages in some edge cases.

## 2.1.22 "Volans" - Aug 11, 2021

<!---
Packaged by Oliver Hsu <oliverhs@sentinelone.com> on Aug 11, 2021 21:00 -0800
--->

Bug fixes:
* Don't log "skipping copying log lines" messages in case number of last produced bytes is 0.
* Fix Kubernetes Agent DaemonSet liveness probe timeout too short and unhealthy agent pod not restarting when a liveness probe timeout occurs.

Other:
* Update Windows Event Log monitor to emit a warning if ``maximum_records_per_source`` config option is set to a non-default value when using a new event API where that config option has no affect.

## 2.1.21 "Ultramarine" - Jun 1, 2021

<!---
Packaged by Arthur Kamalov <arthur@scalyr.com> on Jun 1, 2021 21:00 -0800
--->

Improvements:
* Allow journald monitor to be configured via globs on multiple fields via ``journald_logs.journald_globs`` config option. Contributed by @imron. #741

Bug fixes:
* Fix an issue where log lines may be duplicated or lost in the Kubernetes monitor when running under CRI with an unstable connection to the K8s API.
* Fix an issue where LogFileIterator during the copy-truncate process picks wrong pending file with a similar name causing loss of the log and showing negative bytes in agent status.

Other:
* The discovery logic of the log files, which have been rotated with copy truncate method, now can handle only default rogrotate configurations.
* Agent now emits a warning if running under Python 2.6 which we will stop supporting in the next release.

## 2.1.20 "Tabeisshi" - April 19, 2021

<!---
Packaged by Arthur Kamalov <arthur@scalyr.com> on Apr 19, 2021 21:00 -0800
--->

Improvements:
* Add support for collecting some metrics Kubernetes when running in a CRI runtime.
* Add support for SSL in the `mysql_monitor`. This can be enabled by setting `use_ssl` to True in the monitor configuration.

Bug fixes:
* Ensure pod digest which we calculate and use to determine if pod info in the Kubernetes monitor has  changed is deterministic and doesn't depend on dictionary item ordering.
* Fix a race condition in the worker session checkpoint read/write logic, which was introduced with the ``multi-worker`` feature.


Other:
* Changed the logging level of "not found" errors while querying pods from the Kubernetes API from ERROR to DEBUG, as these errors are always transient and result in no data loss.

## 2.1.19 "StarTram" - March 9, 2021

<!---
Packaged by Yan Shnayder <yan@scalyr.com> on Mar 9, 2021 14:00 -0800
--->

Improvements:
* Add ``Endpoint`` to the default ``event_object_filter`` values for the Kubernetes Event Monitor.
* Update ``scalyr-agent-2 status -v`` output to also include process id (pid) of the main agent process and children worker processes in scenarios where the agent is configured with multiple worker processes.
* Add a new experimental ``--systemd-managed`` flag to the ``scalyr-agent-2-config`` tool which converts existing scalyr agent installation to be managed by systemd instead of init.d.
* Add support for capturing k8s container names to the kubernetes monitor via log line attributes. Container name can be captured using ``${k8s_container_name}`` config template syntax.
* Kubernetes monitor has been updated to log 403 errors when connecting to the Kubernetes API before falling back to the old fallback URL under warning log level. Previously those errors were logged under debug log level which would make it hard to troubleshoot some issues related to missing permissions, etc. since those log messages would only end up in debug log file which is disabled by default.

Bug fixes:
* Fix ``scalyr-agent-status -v`` to not emit / print warnings under some edge cases.
* Fix regression with syslog monitor which caused the ingestion of the file with a wrong parser. The root cause was in the too broad path glob that was used in the agent log's `LogMatcher`, so it also processed the `agent_syslog.log` as an agent log file.

## 2.1.18 "Ravis" - January 29, 2021

<!---
Packaged by Arthur Kamalov <arthur@scalyr.com> on Jan 29, 2021 14:00 -0800
--->

Improvements:
* Add new ``tcp_request_parser`` and ``tcp_message_delimiter`` config option to the ``syslog_monitor``. Valid values for ``tcp_request_parser`` include ``default`` and ``batch``. New TCP recv batch oriented request parser is much more efficient than the default one and should be a preferred choice in most situations.  For backward compatibility reasons, the default parser hasn't been changed yet.
* Update agent to emit a warning if ``k8s_logs`` config option is defined, but Kubernetes monitor is not enabled / configured.
* Update Kubernetes and Docker monitor to not propagate and show some non-fatal errors.
* Field values in log lines for monitor metrics which contain extra fields are now sorted in alphabetic order. This should have no impact on the end user since server side parsers already support arbitrary ordering, but it's done to ensure consistent ordering and output for for monitor log lines.
* Update agent to throw more user-friendly exceptions on Windows when the agent doesn't have access to the agent config file and Windows registry.
* Update code which periodically prints out useful configuration settings to also include actual value of the json library used in case the config option is set to "auto".

Bug fixes:
* Fix a race condition in ``docker_monitor`` which could cause the monitor to throw exception on start up.
* Fix a config deprecated options bug when they are set to ``false``.
* Fix agent so it doesn't throw an exception on Windows when trying to escalate permissions on agent start.
* Make sure we only print the value of ``win32_max_open_fds`` config option on Windows if it has changed.
* Fix a bug which could result in docker, journald and windows event log checkpoint files to be deleted when restarting the agent. This would only affect docker monitor configurations which are setup to ingest logs via Docker API and not json log files on disk (aka ``docker_raw_logs: false`` docker monitor option is set).
* Fix a small bug which might skip first lines of the worker session log file.

Other:
* Pre-built frozen Windows binaries now bundle and utilize Python 3 (3.8.7). In the past releases, they utilized Python 2.7, but due to the Python 2.7 being EOL for a year now, new release will utilize Python 3. This change should be opaque to the end user and everything should continue to work as it did in the previous releases.

## 2.1.17 "Xothichi" - January 15, 2021

<!---
Packaged by Arthur Kamalov <arthur@scalyr.com> on Jan 15, 2021 14:00 -0800
--->

Bug fixes:
* Fix syslog monitor default TCP message parser bug which was inadvertently introduced in 2.1.16 which may sometimes cause for a delayed ingest of some syslog data. This would only affect installations utilizing syslog monitor in TCP mode using the default message parser.  As part of this fix, we have removed the new message parsers added in 2.1.16.  If you were using them, you will revert to the default parser

## 2.1.16 "Lasso" - January 13, 2021

<!---
Packaged by Arthur Kamalov <arthur@scalyr.com> on Jan 13, 2021 14:00 -0800
--->

Features:
* Add copy truncate log rotation support. This is enabled by default.  It does not support copy truncate with compression unless the `delaycompress` option is used.  This feature can be disabled by setting `enable_copy_truncate_log_rotation_support` to false.

Improvements:
* Add new ``tcp_request_parser`` and ``tcp_message_delimiter`` config option. Valid values for ``tcp_request_parser`` include ``default`` and ``batch``. New TCP recv batch oriented request parser is much more efficient than the default one and should be a preferred choice in most situations.  For backward compatibility reasons, the default parser hasn't been changed yet.
* ``shell_monitor`` now outputs two additional metrics during each sample gather interval - ``duration`` and ``exit_code``. First one represents how many seconds it took to execute the shell command / script and the second one represents that script exit (status).

Misc:
* On startup and when parsing a config file, agent now emits a warning if the config file is readable by others.
* Add the config option ``enable_worker_process_metrics_gather`` to enable 'linux_process_metrics' monitor for each multiprocess worker.
* Each session, which runs in a separate process, periodically writes its stats in the log file. The interval between writes can be changed by using the ``default_worker_session_status_message_interval``
* Rename some of the configuration parameters: ``use_miltiprocess_copying_workers``  to ``use_multiprocess_workers``, ``default_workers_per_api_key`` to ``default_sessions_per_api_key``. Previous option names are preserved for the backward compatibility but they are marked as deprecated. NOTE: The appropriate [environment variable names](https://app.scalyr.com/help/scalyr-agent-env-aware) are changed too.
* Update docker monitor so we don't log some non-fatal errors under warning log level when consuming logs using Docker API.
* Add support for ``compression_type: none`` config option which completely disables compression for outgoing requests. Right now one of the main bottle necks in the high volume scenarios in the agent is compression operation. Disabling it can, in some scenarios, lead to large increase to the overall throughput (up to 2x). Disabling the compression will in most cases result in larger data egress traffic which may incur additional charges on your infrastructure provider so this option should never be set to ``none`` unless explicitly advised by the technical support.
* Linux system metrics monitor has been updated to also ignore ``/var/lib/docker/*`` and ``/snap/*`` mount points by default. Capturing metrics for those mount points usually offers no additional insight to the end user. For information on how to change the ignore list via configuration option, please see [RELEASE_NOTES](https://github.com/scalyr/scalyr-agent-2/blob/master/RELEASE_NOTES.md).
* The agent install bash script now adds the Scalyr repositories directly without installing the ``scalyr-repo`` packages. This also eliminates errors caused by re-acquiring the package manager's lock file during the *pre/post* *install/uninstall* scripts. The issue occurred in both ``apt`` and ``rpm`` package managers.

Security fixes and improvements:
* Agent installation artifacts have been updated so the default ``agent.json`` file which is bundled with the agent is not readable by "other" system users by default anymore. For more context, details and impact, please see [RELEASE_NOTES](https://github.com/scalyr/scalyr-agent-2/blob/master/RELEASE_NOTES.md).

## 2.1.15 "Endora" - December 16, 2020

<!---
Packaged by Arthur Kamalov <arthur@scalyr.com> on Dec 16, 2020 14:00 -0800
--->
Feature:
* Ability to upload logs to different Scalyr team accounts by specifying different API keys for different log files. See [RELEASE_NOTES](https://github.com/scalyr/scalyr-agent-2/blob/master/RELEASE_NOTES.md) for more details.
* New configuration option `default_workers_per_api_key` which creates more than one session with the Scalyr servers to increase upload throughput. This may be set using the `SCALYR_DEFAULT_WORKERS_PER_API_KEY` environment variable.
* New configuration option `use_multiprocess_copying_workers` which uses separate processes for each upload session, thereby providing more CPU resources to the agent. This may be set using the `SCALYR_USE_MULTIPROCESS_COPYING_WORKERS` environment variable.
Improvements:
* Linux system metrics monitor now ignores the following special mounts points by default: ``/sys/*``, ``/dev*``, ``/run*``. If you want still capture ``df.*`` metrics for those mount points, please refer to [RELEASE_NOTES](https://github.com/scalyr/scalyr-agent-2/blob/master/RELEASE_NOTES.md).
* Update ``url_monitor`` so it sends correct ``User-Agent`` header which identifies requests are originating from the agent.

Misc:
* The default value for the `k8s_cri_query_filesystem` Kubernetes monitor config option (set via the `SCALYR_K8S_CRI_QUERY_FILESYSTEM` environment var) has changed to `True`. This means that by default when in CRI mode, the monitor will only query the filesystem for the list of active containers, rather than first querying the Kubelet API. If you wish to revert to the original default to prefer using the Kubelet API, set `SCALYR_K8S_CRI_QUERY_FILESYSTEM` the environment variable to "false" for the Scalyr Agent daemonset.
* New ``global_monitor_sample_interval_enable_jitter`` config option has been added which is enabled by default. When this option is enabled, random sleep between 2/10 and 8/10 of the configured monitor sample gather interval is used before gathering the sample for the first time. This ensures that sample gathering for all the monitors doesn't run at the same time. This comes in handy when running agent configured with many monitors on lower powered devices to spread the monitor sample gathering related load spike across a longer time frame.

Bug fixes:
* Fix to make sure we don't expect a valid Docker socket when running Kubernetes monitor in CRI mode. This fixes an issue preventing the K8s monitor from running in CRI mode if Docker is not available.
* Fix line grouping code and make sure we don't throw if line data contains bad or partial unicode escape sequence.
* Fix ``scalyr_agent/run_monitor.py`` script so it also works correctly out of the box when using source code installation.
* Update Windows System Metrics monitor to better handle a situation when disk io counters are not available.
* Docker monitor has been fixed that when running in "API mode" (``docker_raw_logs: false``) it also correctly ingests logs from container ``stderr``. Previously only logs from ``stdout`` have been ingested.

## 2.1.14 "Hydrus" - November 4, 2020

<!---
Packaged by Tomaz Muraus <tomaz@scalyr.com> on Nov 4, 2020 14:00 -0800
--->

Features:
* Add new ``initial_stopped_container_collection_window`` configuration option to the Kubernetes monitor, which can be configured by setting the ``SCALY_INITIAL_STOPPED_CONTAINER_COLLECTION_WINDOW`` environment variable. By default, the Scalyr Agent does not collect the logs from any pods stopped before the agent was started. To override this, set this parameter to the number of seconds the agent will look in the past (before it was started). It will collect logs for any pods that was started and stopped during this window. This can be useful in autoscaling environments to ensure all pod logs are captured since node creation, even if the Scalyr Agent daemonset starts just after other pods.

Improvements:
* Improve logging in the Kubernetes monitor.
* On agent start up we now also log the locale (language code and encoding) used by the agent process. This will make it easier to troubleshoot issues which are related to the agent process not using UTF-8 coding.
* Default value for ``tcp_buffer_size`` Syslog monitor config option has been increased from 2048 to 8192 bytes.
* New ``message_size_can_exceed_tcp_buffer`` config option has been added to Syslog monitor. When set to True, monitor will support messages which are larger than ``tcp_buffer_size`` bytes in size and  ``tcp_buffer_size`` config option will tell how much bytes we try to read from the socket at once / in a single recv() call. For backward compatibility reasons, it defaults to False.

Bug fixes:
* Fix a bug / race-condition in Docker monitor which could cause, under some scenarios, when monitoring containers running on the same host, logs to stop being ingested after the container restart. There was a relatively short time window when this could happen and it was more likely to affect containers which take longer to stop / start.
* Update code for all the monitors to correctly use UTC timezone everywhere. Previously some of the code incorrectly used local server time instead of UTC. This means some of those monitors could exhibit incorrect / undefined behavior when running the agent on a server which has local time set to something else than UTC.
* Fix ``docker_raw_logs: false`` functionality in the Docker monitor which has been broken for a while now.
* Update Windows System Metrics monitor to better handle a situation when disk io counters are not available.

## 2.1.13 "Celaeno" - October 15, 2020

<!---
Packaged by Oliver Hsu <oliver@scalyr.com> on Oct 17, 2020 19:00 -0800
--->

Bug fixes:
* Fix ``scalyr-agent-2 status`` command non-fatal error when running status command multiple times concurrently or in a short time frame.
* Fix ``scalyr-agent-status`` command to not log config override warning to stdout since it may interfere with consumers of the status command output.
* Fix merging of active-checkpoints.json and checkpoints.json checkpoint file data. Previously data from active checkpoints file was not correctly merged into full checkpoint data file which means that under some scenarios (e.g. agent crashed after active checkpoint file was written, but before full checkpoint file was written), data which was already sent to the server could be sent twice. Actual time window when this could happen was relatively small since full checkpoint data is written out every 60 seconds by default. Reported by @anton-ryzhov. #638
* Fix Postgres monitor error when specifying the Postgres ``database_port`` in the agent config.

## 2.1.12 "Betelgeuze" - September 17, 2020

<!---
Packaged by Arthur Kamalov <arthur@scalyr.com> on Sep 17, 2020 19:00 -0800
--->

Mics:
* Upgrade `psutil` dependency which incorporates many critical fixes. As part of the change, Windows Server 2003/XP is no longer supported.
* Small fix for the `pywin32` library which is used in the Windows package.

## 2.1.11 "Aqua" - August 21, 2020

<!---
Packaged by Tomaz Muraus <tomaz@scalyr.com> on Aug 21, 2020 19:00 -0800
--->

Features:
* Add new ``win32_max_open_fds`` configuration option which allows user to overwrite maximum open file limit on Windows for the scalyr agent process.

Bug fixes:
* Fix bug in packaging which would cause agent to sometimes crash on Windows when using windows event log monitor.

## 2.1.10 "Alcor" - August 10, 2020

<!---
Packaged by Tomaz Muraus <tomaz@scalyr.com> on Aug 10, 2020 9:00 -0800
--->

Bug fixes:
* Fix formatting of the "Health Check:" line in ``scalyr-agent-2 status -v`` command output and make sure the value is left padded and consistent with other lines.
* Fix reporting of "Last successful communication with Scalyr" line value in the ``scalyr-agent-2 status -v` command output if we never successfuly establish connection with the Scalyr API.
* Fix a regression in ``scalyr-agent-2-config --upgrade-windows`` functionality which would sometimes throw an exception, depending on the configuration values.

Security fixes and improvments:
* Fix a bug with the agent not correctly validating that the hostname which is stored inside the certificate returned by the server matches the one the agent is trying to connect to (``scalyr_config`` option). This would open up a possibility for MITM attack in case the attacker was able to spoof or control the DNS.
* Fix a bug with the agent not correctly validating the server certificate and hostname when using ``scalyr-agent-2-config --upgrade-windows`` functionality under Python < 2.7.9. This would open up a possibility for MITM attack in case the attacker was able to spoof or control the DNS.
* When connecting to the Scalyr API, agent now explicitly requests TLS v1.2 and aborts connection if the server doesn't support it or tries to use an older version. Recently Scalyr API deprecated support for TLS v1.1 which allows us to implement this change which makes the agent more robust against potential downgrade attacks. Due to lack of required functionality in older Python versions, this is only true when running the agent under Python >= 2.7.9.
* When connecting to the Scalyr API, server now sends a SNI header which matches the host specified in the agent config. Due to lack of required functionality in older Python versions, this is only true when running the agent under Python >= 2.7.9.

## 2.1.9 "Ursa" - August 4, 2020

<!---
Packaged by Oliver hsu <oliver@scalyr.com> on Aug 4, 2020 9:00 -0800
--->

Bug fixes:
* Fixed a regression in Scalyr Windows Agent cmdlet script (`ScalyrShell.cmd`) which prevents the agent from starting.

## 2.1.8 "Titan" - August 3, 2020

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Aug 3, 2020 12:30 -0800
--->

Features:
* The `status -v` command now contains health check information, and will have a return code of `2` if the health check has failed. New optional flag for the `status` CLI command `-H` returns a short status with only health check info. A new configuration feature `healthy_max_time_since_last_copy_attempt` defines how many seconds is acceptable for the Agent to not attempt to send up logs before the health check should fail, defaulting to `60.0`. For more information, please refer to the release notes document.
* Kubernetes yaml has been updated to include a liveliness check based on the new health check info, which will cause a pod restart if the agent is considered unhealthy.

Bug fixes:
* Fixed race condition in pipelined requests which could lead to duplicate log upload, especially for systems with a large number of inactive log files.  Log files would be reuploaded from their start over short period of time (seconds to minutes).  This bug is triggered when pipelining is enabled, either by explicitly setting the `pipeline_threshold` config option or by using a Scalyr Agent release >= 2.1.6 (pipelining was turned on by default in 2.1.6).
* Fixed the misconfiguration in Windows packager which causes some number of the monitors to not be included in Windows version.  This generates import errors when attempting to use monitors like the syslog or shell monitor.
Misc:
* ``compression_level`` configuration option now defaults to ``6`` when using ``deflate`` ``compression_type`` (``deflate`` is the default value for the ``compression_type`` configuration option). 6 offers the best trade off between compression ratio and CPU usage. For more information, please refer to the release notes document.

## 2.1.7 "Serenity" - June 24, 2020

<!---
Packaged by Yan Shnayder <yan@scalyr.com> on Jun 24, 2020 16:30 -0800
--->

Features:
* New configuration feature `k8s_logs` allows configuring of Kubernetes logs similarly to the `logs` configuration but matches based on Kubernetes pod, namespace, and container name. Please see the [RELEASE_NOTES](https://github.com/scalyr/scalyr-agent-2/blob/master/RELEASE_NOTES.md#217-serenity---june-24-2020) for more details.

Bug fixes:
* Fixed race condition that sometimes resulted in duplicated K8s logs being uploaded on agent restart or configuration update.

Misc:
* The Windows package is now built using `pyInstaller` instead of `py2exe`.  As part of the change, we are no longer supporting 32-bit Windows systems.  Nothing else should change due move to `py2Installer`.

## 2.1.6 "Rama" - June 4, 2020

<!---
Packaged by Arthur Kamalov <arthur@scalyr.com> on Jun 4, 2020 13:30 -0800
--->

Features:
* New configuration option `max_send_rate_enforcement` allows setting a limit on the rate at which the Agent will upload log bytes to Scalyr. You may wish to set this if you are worried about bursts of log data from problematic files and want to avoid getting charged for these bursts.
* New default overrides for a number of configuration parameters that will result in a higher throughput for the Agent. If you were relying on the lower throughput as a makeshift rate limiter we recommend setting the new `max_send_rate_enforcement` configuration option to an acceptable rate or "legacy" to maintain the current behavior. See the [RELEASE_NOTES](https://github.com/scalyr/scalyr-agent-2/blob/master/RELEASE_NOTES.md#216-rama---june-4-2020) for more details.

Minor updates:
* Default value for `max_line_size` has been raised to 49900. If you have this value in your configuration you may wish to not set it anymore to use the new default.

Bug fixes:
* Fixed Syslog monitor issue causing monitor to write binary strings to the log file.

## 2.1.5 "Quantum Leap" - May 30, 2020

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on May 30, 2020 13:30 -0800
--->

Bug fix
* Fixed issue causing the Windows version of the Scalyr Agent to not start when starting in forked mode.

## 2.1.4 "Prime" - May 30, 2020

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on May 30, 2020 09:30 -0800
--->

Critical bug fix
* Updated bundled certificates used to verify Scalyr TLS certificate.  Existing bundled certificates had expired causing some customers to not be able to verify the TLS connection.

* Added ability to specify an extra configuration snippet directory (in addition to `agent.d`).  You may specify the extra directory by setting the SCALYR_EXTRA_CONFIG_DIR environment variable to the path of your desired directory.  This has been added mainly to help mounting additional configuration in Kubernetes.

Bug fix
* Fix timing issue in `kubernetes_monitor` that could result in not collecting logs from very short lived containers.

## 2.1.3 "Orion" - May 1, 2020

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on May 1, 2020 09:30 -0800
--->

Features
* The Kubernetes and Kubernetes event monitors now allow you to restrict the namespaces for which the Scalyr Agent will collect logs and events.  This may be controlled via the `SCALYR_K8S_INCLUDE_NAMESPACES` environment variable or `k8s_include_namespaces` configuration option.  See [release notes](https://github.com/scalyr/scalyr-agent-2/blob/master/RELEASE_NOTES.md#213-orion---may-1-2020) for more information.

Bugs
* Fixed Kubernetes monitor to verify by default TLS connections made to the local Kubelet.  This was causing an excessive amount of warnings to be emitted to the stdout.  See [release notes](https://github.com/scalyr/scalyr-agent-2/blob/master/RELEASE_NOTES.md#213-orion---may-1-2020) for details on how to disable verification if this causes issues.
* Fixed issue preventing the Apache monitor from running under Python 2.
* Fixed some issues causing some logging to fail due to incorrect arguments.

## 2.1.2 "Nostromo" - April 23, 2020

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Apr 23, 2020 08:30 -0800
--->

Features

* The Agent no longer enforces all events must have monotonically increasing timestamps when pushed into Scalyr.  The is now possible due to changes in the server.  This allow better use of the default timestamps, such as in Docker and Kubernetes.
* Log lines collected via the Kubernetes or Docker monitors will now have their default timestamps set to the timestamp generated by K8s/Docker.  As long as a parser does not override the timestamp, the K8s and Docker timestamps will be used in Scalyr.
* Agent logs with severity higher than INFO will now be output to stdout as well as the `agent.log` file when running with the `--no-fork` flag.
* The Journald monitor now supports a `detect_escaped_strings` option which automatically detects if the `details` field is already an escaped string, and if so, just emits it directly to the log instead of re-escaping it.  This option is specified using the `journald_logs` array.  See the [journald monitor documentation](https://www.scalyr.com/help/monitors/journald) for more details.

Bugs
* Fixed monitor configuration bug that prevented config options that did not have a default nor were required from being properly set via environment variables.

Optimizations

* Optimize RFC3339 date strings parsing. This should result in better throughput under highly loaded scenarios (many lines per second) when using Docker / Kubernetes monitor.
* Speed up event serialization under highly loaded scenarios by optimizing json encoding and encoding of event attributes.
* We now default to ``orjson`` JSON library under Python 3 (if the library is available). ``orjson`` is substantially faster than ``ujson`` for encoding.

## 2.1.1 "Millenium Falcon" - Mar 30, 2020

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Mar 30, 2020 16:30 -0800
--->

Features
* Major update of code base to support running under Python 2 and 3.  See [release notes](https://github.com/scalyr/scalyr-agent-2/blob/master/RELEASE_NOTES.md) for more information.
* Agent now supports Python 2.6, 2.7 and >= 3.5
* When installing using RPM or Debian, Python 2 will be used by default unless unavailable.
* The Python version used to run the Agent may be controlled using the `scalyr-switch-python` command.
* The K8s manifest files have been changed to run the Agent in the `scalyr` namespace instead of the `default` namespace.  When updating an existing Scalyr Agent K8s instance, you must follow the upgrade instructions described in the [upgrade notes](https://github.com/scalyr/scalyr-agent-2/blob/master/upgrade_notes.md).
* RPM and Debian packages no longer declare dependency on Python to promote cross-distribution compatibility.  The dependency is now verified at package install time.
* Added option to `scalyr-agent-2 status -v` to emit JSON (``--format=[text|json]``).
* Add new ``metric_name_blacklist`` supported attribute to each monitor configuration section. With this attribute, user can define a list of metric names which should be excluded and not shipped to Scalyr.
* Add support for ``orjson`` JSON library when running under Python 3. This library offers significantly better performance and can be enabled by setting ``json_library`` config option to ``orjson`` and installing ``orjson`` Python package using pip.

Bugs
* Fix authentication issue in `kubernetes_monitor` when accessing kublet API.
* Better error messages issued when missing required certificate files.
* Updated Kubernetes manifest file to use `apps/v1` for DaemonSet API version instead of beta version.
* Update scalyr client code to log raw uncompressed body under debug log level to aid with troubleshooting.
* Metric type for ``app.disk.requests.{read,write}`` metrics has been fixed.
* Fix ``iostat`` monitor so it also works with newer versions of Linux kernel.
* Fix invalid extra field for two ``tomcat.runtime.threads`` metrics in the Tomcat monitor (all of the metrics had type set to ``max`` whereas one should have type set to ``active`` and the other to ``busy``).

Minor updates
* The ``/etc/init.d/scalyr-agent-2`` symlink is no longer marked as a conf file in Debian packages.
* Update of embedded ecsda library to 0.13.3
* Docker support now requires the docker 4.1 client library
* Changed which signal is used to execute `scalyr-agent-2 status -v` under Linux to improve handling of SIGINT. Previously ``SIGINT`` was used, now ``SIGUSR1`` is used.
* When running in foreground mode (``--no-fork`` flag), SIGINT signal (aka CTRL+C) now starts the graceful shutdown procedure.
* Two new metrics (``app.io.wait``, ``app.mem.majflt``) are now emitted by the Linux process monitor. If you want those metrics to be excluded for your monitors, you can utilize new ``metric_name_blacklist`` monitor config option.

Testing updates
* Numerous changes to improve testing and coverage reporting

## 2.0.59 "Lady MacBeth" - Feb 13, 2020

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Feb 13, 2020 10:30 -0800
--->

Feature
* Improved support for handling long log lines captured by `kubernetes_monitor` and `docker_monitor`.  When parsing docker logs, the serialized JSON objects can now be up to `internal_parse_max_line_size` bytes (defaults to 64KB).  This replaces the requirement they be less than `max_line_size`.  The `log` field extracted from the JSON object is still subjected to the `max_line_size` limit.
* Improved handling when `kubernetes_monitor` fails due to an uninitialized K8s cache.  If a `kubernetes_monitor` becomes stuck for 2 minutes and cannot initialize, the agent will terminate its container to allow for K8s to restart it.

Bugs
* Add additional diagnostic information to help customers troubleshoot issues in the `kubernetes_monitor` due to failures in K8s cache initialization.
* Fix bug due to protected access in the `journald_monitor`.

## 2.0.58 "Karrajor" - Jan 23, 2020

Packaged by Steven Czerwinski <czerwin@scalyr.com> on Jan 23, 2020 10:30 -0800

Bugs
* Fixed error in Windows release caused by missing `glob2` module
* Fixed removal of `stream` attribute from logs uploaded using Docker and K8s monitors

## 2.0.57 "Jupiter 2" - Jan 16, 2020

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Jan 16, 2020 11:00 -0800
--->

Bugs
* Fixed error in `syslog-monitor` causing monitor to stop working without `docker-py` installed on host system

## 2.0.56 "Icarus" - Jan 15, 2020

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Jan 8, 2020 14:30 -0800
--->

Features
* Added support to `journald` plugin to create separate log files (with distinct configuration such as parsers) based on `unit` field.
* Add supported for `**` in file path glob patterns recursively drill down into sub-directories.
* Changed to new API format that allows for more efficient encoding of log file attributes

## 2.0.55 "Hermes" - Nov 21, 2019

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Nov 21, 2019 14:30 -0800
--->

Bugs
* Fixed bug causing SSL connection failures on certain Windows configurations.

## 2.0.54 "Galactica" - Nov 7, 2019

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Nov 5, 2019 10:00 -0800
--->

Features
* Added TSLite support to allow customers using Python 2.6 to connect via TLSv1.1

Bugs
* Fix issue causing log copying slow down when there is a high churn in the log files it is copying (typically K8s or Docker with lots of containers coming up down)

Miscellaneous changes
* No longer fail startup if cannot connect successfully to server
* Change default of `check_remote_if_no_tty` config option to `True`
* Test cleanups

## 2.0.53 "Firefly" - Sep 18, 2019

<!---
Packaged by Imron Alston <imron@scalyr.com> on Sep 18, 2019 15:00 -0700
--->

Features
* Collection of per CPU metric data under docker/kubernetes has been placed behind the config option `docker_percpu_metrics` (defaulted to `False`) to prevent collecting excessive metrics on machines with a large number of cores.

Miscellaneous changes
* Added scripts for bringing up/tearing down large clusters for testing
* Fixed problem with smoketest scripts


## 2.0.52 "Einstein-Rosen Bridge" - Sep 16, 2019

<!---
Packaged by Edward Chee <echee@scalyr.com> on Sep 16, 2019 11:00 -0700
--->

Features
* K8s serverHosts are no longer displayed in Scalyr UI Log Sources (thus avoiding situations where hundreds of serverHost entries pollute the Log Sources overview).

Bugs
* MySQL monitor plugin fails to connect to Amazon RDS instances. Note: the fix requires python 2.7 so customers running older python versions will no longer be able to run the MySQL monitor from this release onward.


## 2.0.51 "Daniel Jackson" - Sep 5, 2019

<!---
Packaged by Edward Chee <echee@scalyr.com> on Sep 5, 2019 15:00 -0700
--->

Features
* Major refactor of kubernetes_monitor (rate-limit k8s api master calls and avoid large api master queries). Tested on a 1000-node cluster.

Bugs
* You can now set config params to empty string, thus allowing overriding of non-null default values (e.g. set `k8s_ignore_namespaces` to empty list instead of default `kube-system`).
* `k8s_ignore_namespaces` is now a comma-separated array-of-strings (legacy space-separated behavior is still supported).
* JSON logs were causing `total_bytes_skipped` to incorrectly report as always increasing in agent.log `agent_status` line.
* Python 2.5 sometimes fails to launch because `httplib.HTTPConnection._tunnel_host` is not present.

Miscellaneous changes
* Emit log message indicating whether kubernetes_monitor is using docker socket or cri filesystem to query running containers.
* If an error is encountered while parsing JSON logs, do not log the offending JSON line in agent.log.
* Better reporting of stack trace when exception occurs in kubernetes & docker monitor _get_container() loops.


## 2.0.50 "Chevron" - July 30, 2019

<!---
Packaged by Edward Chee <echee@scalyr.com> on Jul 30, 2019 11:00 -0700
--->

Features
* Default `docker_raw_logs` to True.
* Default `compression_type` to `bz2` (previously compression was off).
* Add `SCALYR_SERVER` to sample config map and docker readme.

Bugs
* Fix custom json lib handling of negative integers.
* Fix bug to allow agent to inherits environment umask.
* Restore default value of `report_k8s_metrics` to True.


## 2.0.49 "Bratac" - Jun 7, 2019

<!---
Packaged by Edward Chee <echee@scalyr.com> on Jun 7, 2019 11:00 -0700
--->

Features
* Add `container_globs_exclude` option to docker monitor for blacklisting containers by name.
* Many `docker_monitor` plugin config variables are now environment-aware.
* The global `compression_level` config variable is now environment-aware.
* Add SCALYR_K8S_EVENTS_DISABLE in addition to K8S_EVENTS_DISABLE, but either will work.
* Allow tilde (~) character in `linux_system_metrics` tags (e.g. mounted file names may contain it).
* Incorporate profiler into agent for runtime performance analysis.
* Add random skew to k8s api queries to lessen peak load on k8s api masters.

Bugs
* Fix Dockerfile.custom_k8s_config to use correct image
* Fix bug in Windows upgrade utility
* Fix attribute error in k8s controller object

Miscellaneous changes
* `scalyr-agent-2.yaml` now exports SCALYR_K8S_EVENTS_DISABLE instead of K8S_EVENTS_DISABLE


## 2.0.48 "Asgard" - May 22, 2019

<!---
Packaged by Edward Chee <echee@scalyr.com> on May 22, 2019 14:00 -0700
--->

Bugs
* Fix memory leak in linux process metrics introduced in v2.0.47 which manifests as high CPU or memory use.


## 2.0.47 "Zatnikatel" - May 8, 2019

<!---
Packaged by Edward Chee <echee@scalyr.com> on May 8, 2019 16:00 -0700
--->

Features
* ContainerD support
* Reduced Agent docker image sizes (using Alpine)

Bugs
* Fix bug where if hashing is used with redaction, non-matching lines are not uploaded
* Fixed code bugs causing Agent not to start in versions of Python < 2.7
* Fixed github issue #180
* Updated docker/README.md


## 2.0.46 "Yadera" - Apr 24, 2019

<!---
Packaged by Edward Chee <echee@scalyr.com> on Apr 24, 2019 11:00 -0700
--->

Features
* Expanded mapping of config vars to top-level and k8s environment variables in code (not `import_vars`).
* Expanded env vars enable agent configuration via single k8s configMap (imported with `envFrom`).
* Config vars such as `container_globs` and logs `exclude` globs are now assigned a type (comma-separated strings).
* Display Scalyr-related environment variables in `agent status -v`.
* Include Docker versioning information when reporting to Scalyr.

Bugs
* Fix issue preventing k8s agent from recognizing new pods.


## 2.0.45 "Xindi" - Apr 5, 2019

<!---
Packaged by Edward Chee <echee@scalyr.com> on Apr 5, 2019 15:00 -0700
--->

Features
* Publish image supporting Docker logs via `json` driver instead of `syslog`
* Include K8s versioning information when reporting to Scalyr

Bugs
* Remove Python 2.7 specific uses for `format`
* Fix parser not being respected when set in log file attributes

## 2.0.44 "Wurwhal" - Mar 25, 2019

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Mar 25, 2019 14:10 -0700
--->

Features
* Add configuration-via-labels support for the `docker_monitor`.
* Record `eventId` in `windows_events_monitor`.

Bugs
* Fix issue preventing collection of remote events in `windows_events_monitor`.
* Fix incorrect metrics collection in `postgres_monitor` due to not properly reseting cursor.
* Eliminate redudant K8s cache in the agent running on the K8s event leader.



## 2.0.43 "Vorta" - Mar 8, 2019

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Mar 8, 2019 15:15 -0800
--->

Features
* Release of the `kubernetes_events_monitor` plugin with collects Kubernetes Events and pushes them into Scalyr.  See the [monitor documentation](https://www.scalyr.com/help/monitors/kubernetes-events) for more information.

Bugs
* Fix issue preventing log configs with glob patterns to override exact match patterns.  This is required to help override redaction and parsers rules for Docker.
* Fix issue in mysql_monitor preventing error message from being logged

## 2.0.42 "Unas" - Jan 27, 2019

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Jan 27, 2019 11:15 -0800
--->

Features
* Add in v2 K8s support.  You must configure a k8s cluster name to start using the new v2 support.  See Kubernetes Agent Install directions.

Bugs
* Only allow non-secure connections to Scalyr if explicit override option is set.
* Redesign of k8s cache to better handle large number of pods
* Allow the k8s api server address to be set via a configuration option.
* Parallelized container metric fetches to avoid not being able to collect metrics in time.

## 2.0.41 "Q" - Dec 12, 2018

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Dec 12, 2018 11:15 -0800
--->

Bugs
* Fix bad class name for wrapped responses in Docker and Kubernetes monitor.
* Fix high CPU consumption in Kubernetes monitor due to encoding detection.
* Add defensive code to Kubernetes cache to prevent cache death spiral.


## 2.0.40 "Primes" - Dec 7, 2018

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Dec 7, 2018 16:00 -0800
--->

Bugs
* Fix urgent incompatibility issue with python version < 2.7 in call to string decoding.


## 2.0.39 "Orion" - Dec 5, 2018

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Dec 5, 2018 16:50 -0800
--->

Bugs
* Adjusted unicode decoding to be more tolerant of bad input.
* Added support for optimized json parsing library.  Changed k8s agent to use optimized version.

## 2.0.38 "Nox" - Nov 9, 2018

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Nov 9, 2018 16:00 -0800
--->

Features

* Added ability to specify default values for environment variables imported in configuration files.

Bugs
* Added temporary hack to new Kubernetes support to upload Daemonsets as Deployments.

## 2.0.37 "Ly-Cilph" - Oct 19, 2018

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Oct 19, 2018 15:00 -0700
--->

Features

* Finalized new support for Kubernetes.  Not turned on by default yet.  Will be generally available in November.

Bugs
* Fix journald monitor to system default path.

## 2.0.36 "Kliint" - Sept 21, 2018

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Sep 21, 2018 13:00 -0700
--->

Bug fixes

* Remove / rework debug log statements that were consuming too much CPU.
* Add ability to disable the Kubernetes monitor from parsing the json log lines on the client
* Do not write out the full checkpoint.json file every iteration.  Instead, write out only the active log files on every iteration with a consolidation every one minute.

## 2.0.35 "Jem'hadar" - Sept 19, 2018

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Sep 19, 2018 11:00 -0700
--->

Features:

* Added support in the `kubernetes_monitor` for annotations-based configuration.  You can now specify parsers and whether or not a pod's logs can be sent to Scalyr via k8s annotations.  See documentation on `kubernetes_monitor` for more details.

Bug fixes:

* Added fixes that should eliminate memory leak.

## 2.0.34 "" - Jun 15, 2018

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Jun 15, 2018 11:00 -0700
--->

Features:

* Added `journald_monitor` for collecting logs from a local `journald` service.  Requires installation of the Python `systemd` library.
* Added `garbage_monitor` for debugging memory consumption issues in the agent.
* Added `verify_k8s_api_queries` option to the `kubernetes_monitor` to allow disabling SSL verification on local API calls.

Bug fixes:

* Fixed issues causing the `linux_process_metrics_monitor` to throw exceptions when the monitored process dies.
* Additional debug flags to aide in investigating memory issues with the agent.

## 2.0.33 "Horta" - May 25, 2018

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on May 25, 2018 16:00 -0700
--->

Features:

* Relaxed configuration rules to allow for any config option to be specified in a configuration fragment in the `agent.d` directory.

Bug fixes:

* Fixed bug in `linux_process_metrics` that would generate errors when a monitored process died
* Fixed issue in the docker and kubernetes monitors that would prevent the agent from sending logs from short lived containers
* Fixed issue in the docker and kubernetes monitors that could cause the tail end of a containers logs to not be uploaded after it exits
* Fixed issue in docker monitor where the `metrics_only` config option was not being obeyed.
* Added various options to help investigate memory leak

## 2.0.32 "Goauld" - Apr 27, 2018

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Apr 27, 2018 13:00 -0700
--->

Bug fixes:

* Added various options to help investigate memory leak

## 2.0.31 "Fallers" - Apr 19, 2018

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Apr 19, 2018 11:00 -0700
--->

Features:

* Added kubernetes support with introduction of new kubernetes monitor along with kubernete image published on dockerhub.com under scalyr/scalyr-k8s-agent.  See online documentation for more information.
* Added `network_interface_suffix` option to `linux_system_metrics` monitor to control regular expression used to validate interfaces names.  Additionally, widened existing rule to accept letters at the end of the interface name.
* Added `aggregate_multiple_processes` to `linux_process_metrics` which allows multiple processes to be matched by process matching rule.  The reported metrics will include the statistics from all matching processed.
* Added `include_child_processes` to `linux_process_metrics` to include all child processes from the matched process in the reported metrics.

## 2.0.30 "Ewok" - Oct 25, 2017

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Oct 25, 2017 13:45 -0700
--->

Features:

* Changed default for `max_line_size` to 9900 to match new larger `message` field support on the server.

Bug fixes:

* Fixed bug causing the Docker plugin to `leak` file descriptors as new containers were added while using the `docker_api` mode.

## 2.0.29 "Dyson Aliens" - Sep 29, 2017

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Sep 29, 2017 13:45 -0700
--->

Features:

* Support to parse log lines written as a JSON object to extract line content before sending to Scalyr.  You may turn this on by setting `parse_lines_as_json` to `true` in your log configuration stanza for a particular file.  This is useful when uploading raw Docker logs.
* Read the Scalyr api key from an environment variable
* Add support for `PUT` requests to the `http_monitor`.
* Add support for replacing redacted values with a hash of the actual value.  See [the redaction documentation](https://www.scalyr.com/help/scalyr-agent#redaction) for more details.

Bug fixes:

* Fix win32 build such that it correctly pulls packages from the third party repository.  This fixes a bug resulting in SOCK5 proxy support not working under Windows.

## 2.0.28 "Changeling" - Aug 29, 2017

<!---
Packaged by Saurabh Jain <saurabh@scalyr.com> on Aug 29, 2017 13:45 -0700
--->

New features:

* Upgraded `requests` library to support new proxy protocols such as `SOCKS5`.  To use `SOCKS5`, use either the `socks5` or `socks5h` protocol when specifying the proxy address (`socks5` resolves DNS addresses locally, whereas `socks5h` resolves addresses at the `SOCKS5` server).

Bug fixes:

* Fix bug preventing multiple instances of the `syslog_monitor` from logging to separate log files.

## 2.0.27 "Borg" - Jun 2, 2017

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Jun 2, 2017 16:45 -0700
--->

New features:

* Added new option `report_container_metrics` to `docker_monitor` to allow disabling of gathering and reporting metrics for each Docker container.

Bug fixes:

* Fix recent breakage causing the `run_monitor` code to fail.
* Fix error / warning logging in `syslog_monitor` to better capture issues with Docker support.

## 2.0.26 "Anomine" - May 11, 2017

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on May 11, 2017 16:45 -0700
--->

New features:

* Added feature to allow completely disabling the use of the Docker socket in certain Docker configurations.
* New `max_log_size` and `max_log_rotations` configuration options that can be used to set the maximum length an agent-generated log file can grow before it is rotated and the maximum number of rotations to keep.

Bug fixes:

* Fix bug preventing rotated Docker files from being deleted
* Fix bug that resulted in `https_proxy` and ``http_proxy` configuration options being ignored.


## 2.0.25 "Zany Zebra" - Apr 13, 2017

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Apr 13, 2017 14:45 -0700
--->

New features:

* Docker integration:  Old docker log files will be deleted after unused for 1 day (by default).
* Change to pidfile format in preparation for better `systemd` support

Bug fixes:

* Syslog/Docker fix that was causing logs being uploaded with default parser instead of user-specified parser
* Minor fixes for BMP unicode


## 2.0.24 "Yucky Yak" - Mar 22, 2017

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Mar 22, 2017 15:15 -0700
--->

New features:

* New `rename_logfile` option to change the file name and path for a log file when uploading it to Scalyr.
* New `copy_from_start` option to instruct the agent to copy a log file from its start when it first matches.
* New metric in `linux_system_metrics` to record number of CPUs used by a machine.  Metric name is `sys.cpu.count`.
* New `strip_domain_from_default_server_host` configuration option to remove any domain name from `serverHost` when using the default value.

Bug fixes:

* Syslog/Docker fix that generated a `port already in use` error when reading new configuration file
* Syslog/Docker fix that caused dropped log lines when write rate exceeded certain threshold
* Syslog CPU performance improvements


## 2.0.23 "Xeric Xeme" - Jan 27, 2017

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Jan 27, 2017 14:00 -0700
--->

Major overhaul of Docker support:

* New approach to improve stability across multiple versions of Docker
* Relies on Docker's `syslog` logging plugin
* Automatic collection of Docker metrics for all containers running on host
* Improved Dockerfiles to ease creating images with custom Scalyr Agent configuration
* Improved methods for configuring Scalyr Agent running within the container
* Customize where container log files are written
* See the [Docker installation documentation](https://www.scalyr.com/help/install-agent-docker) for more details.

Additional features:

* New `exclude` option for writing log matching rules.  When specifying which logs to collect using a glob pattern, you can exclude any of the matching logs using another glob.  The field value should be an array of glob patterns.
* The `import_vars` feature has been extended to work in all files in the `agent.d` directory.  The variables imported by a file are only applied to that file.
* Both the `api_key` and `scalyr_server` fields may now be set in any file in the `agent.d` directory.
* Initial support for compressing upload payloads

Bug fixes:

* Removed spurious exceptions in the `linux_process_metrics` module due to reading blank lines from `/prod/pid/io`
* Prevent log upload being wedged when encountering invalid utf-8 characters
* Prevent errors in Windows when file descriptors were attempted to be close
* More diagnostic output and defensive code for the `linux_process_metrics` module to help investigate issue

## 2.0.22 "Wonderful Whale" - Oct 10, 2016

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Oct 10, 2016 16:00 -0700
--->

Bug fixes:

* Fixed bug in `linux_process_metrics` causing errors when monitored process disappears


## 2.0.21 "Querulous Quail" - Oct 7, 2016

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Oct 7, 2016 17:00 -0700
--->


Features:

* Added ability to set HTTP and HTTPS proxies via configuration file.  Use new configuration variables `http_proxy` and `https_proxy`.  You must also set `use_requests_lib` to true.
* Report the number of open file descriptors held by a process for `linux_process_metrics`.  The metric name is `app.io.fds`.
* The assigned the `scalyrAgentLog` parser to the agent log
* Added ability to skip the Scalyr connectivity check at agent start up using `--no-check-remote-server`.

Bug fixes:

* Added third-party library to fix issue with `postgres_monitor`.
* Added extra logging to track issue reported with Windows agent of silent shutdown.
* Fixed issue with `haltBefore` line grouper that prevented logs from being uploaded for several minutes.
* Changed default for `line_completion_wait_time` from 300 secs to 5 secs.
* Always delete the `*.pyc` files when doing an upgrade or uninstall


## 2.0.20 "Vexing Viper" - August 10, 2016

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Aug 10, 2016 16:00 -0700
--->

Features:

* Added feature to prevent tracking stale log files on a per-directory basis.  Reduces checkpoint size due to large directories.


## 2.0.19 "Underwater Urubu" - July 29, 2016

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Jul 29, 2016 11:30 -0700
--->

Bug fixes:

* Fix bug causing agent to fail startup due to ``'module' object has no attribute 'UUID'``.
* Improved log line format for ``snmp_monitor``.  You may disable using new format by setting the monitor config option ``use_legacy_format`` to true.

## 2.0.18 "Quaint Quail" - July 19, 2016

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Jul 19, 2016 13:30 -0700
--->

Features:

* Release of new ``snmp_monitor`` plugin, used to monitor SNMP devices

Bug fixes:

* Fix bug in ``windows_process_metrics`` when matching by commandline.
* Fix invalid character bug when parsing unicode characters with decimal value > 2^16
* Fix bug in ``shell_monitor`` plugin resulting in defunct processes lingering
* Fix bug in ``url_monitor`` plugin resulting in not emitting metric in some failure cases

## 2.0.17 "Pugnacious Pig" - April 20, 2016

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Apr 20, 2016 13:30 -0700
--->

Features:

* Integration of new request library, allowing routing through target specified by ``proxy`` environment variable.  New library turned off by default for now.  To turn on, set ``use_requests_lib``.

Bug fixes:

* Fix ``windows_system_metrics`` monitor to no longer report disk usage on empty drives
* Fix ``mysql_monitor`` to recreate connection to db on failures
* Fix metrics names rather than throw errors when invalid metrics names are emitted by modules such as graphite.


## 2.0.16 "Operating Otter" - January 31, 2016

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Jan 31, 2016 11:30 -0800
--->

Features:

* Windows Event Log monitor now supports the EvtLog API implemented by Windows Vista and newer system.  This allows for more expressive queries, as well as selecting events by severity level such as "Critical".

Bug fixes:

* Fix UTF-8 truncation bug in redis plugin.
* New option in redis plugin that controls logging of UTF-8 converstion errors.  See the ``utf8_warning_interval`` for more details.
* Fix bug where ``network_interface_prefixes`` option was broken when listing multiple interfaces.
* Fix ``no attribute _tunnel_host`` bug with python 2.4 ssl library


## 2.0.15 "Marauding Mouse" - January 4, 2016

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Jan 4, 2016 11:30 -0800
--->

Features:

* Added plugin for reading SLOWLOG from redis
* Heavily optimized common path for copying logs to increase throughput

## 2.0.14 "Neurotic Nightingale" - November 4, 2015

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Nov 4, 2015 11:30 -0800
--->

Features:

* New sequence id and number implementation to help prevent events being added to the database multiple times
* Create new configuration option ``max_existing_log_offset_size`` to set a limit on how far back in a log file we are willing to go for a log file we have been previously copying.
* Enabled ``syslog_monitor`` for Windows platforms
* Preview release of ``windows_event_log_monitor``, a monitor for copying the Windows event log to Scalyr.
* Preview release of docker support.  E-mail contact@scalyr.com for more details
* Added new option ``network_interface_prefixes`` to linux_system_metrics monitor to override the prefix for monitored network interfaces.

Bug fixes:

* Fixed some race conditions in writing the pidfile on POSIX systems.
* Fixed bug causing agent to stop copying logs when previously copied logs are removed
* Disabled checking the command of the running agent process to guard against pid re-use since this was leading to some false negatives in the ``is the agent running`` checks.
* Remove exception logging when bad response received from server
* Print more informative message when server responds with ``server too busy``
* Fix Utf-8 encoding bug with redaction rules

## 2.0.13 "Moonstruck Monkey" - August 14, 2015

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Aug 14, 2015 2:45 -0700
--->

Bug fixes:

* Added some extra diagnostic information to help investigate some customer issues

## 2.0.12 "Loopy Lama" - August 5, 2015

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Aug 5, 2015 15:30 -0700
--->

New features:

* Enable line groupers on the agent.  Each log file may specify line grouping rules in its configuration.  The agent can use this to group consecutive log lines together into a single logic log line.  All future sampling and redaction rules will work on this single line instead of the individual log lines.

Bug fixes:

* Close file handles for files being scanned that have not had any activity in the last hour.  Should fix too many open files bug.
* Reduce the default ``max_line_size`` value to 3400 to avoid truncation issues introduced by the server.

## 2.0.11 "Keen Kangaroo" - June  24, 2015

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Jun 24, 2015 11:45 -0700
--->

New features:

* Allow any monitor's metric log's rate limiter to be modified via configuration, along with flush aggregation.
* Provide ``--upgrade-without-ui`` on ``scalyr-agent-2-config`` to allow upgrading the agent without UI (Windows).
* Write user-friendly error message to event log when a major configuration problem is seen during start up (Windows)

Bug fixes:

* Do not fail Scalyr Agent service start if configuration file registry is not set (Windows).
* Remove rate limiter on metric log for graphite monitor and add in flush aggregation.
* Fix that prevented graphite monitor thread from starting when accepting both text and pickle protocols

## 2.0.10 "Jumpy Jaguar" - June  9, 2015

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Jun 9, 2015 03:00 -0700
--->

Bug fixes:

* Prevent syslog monitor from writing syslog message to agent log.
* Performance improvement for syslog monitor to prevent it from flushing the traffic log file too often
* Fix bug in error reporting from client that caused exceptions to be thrown while logging an exception

## 2.0.9 "Intelligent Iguana" - May  28, 2015

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on May 28, 2015 17:00 -0700
--->

New features:

* Added syslog monitor for receiving logs via syslog protocol.

Bug fixes:

* Fix bug causing agent to temporarily stop copying logs if the underlying log file disappeared or read access was removed for Windows.

## 2.0.8 "Hilarious Horse" - Apr 15, 2015

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Apr 15, 2015 11:30 -0700
--->

New features:

* Make log processing parameters such as ``max_log_offset_size`` adjustable via the configuration file.

Bug fixes:

* Fix bug preventing turning off default system and agent process monitors.
* Fix bugs preventing release of open file handles


## 2.0.7 "Glorious Gerbil" - Apr 8, 2015

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Apr 8, 2015 11:00 -0700
--->

Bug fixes:

* Relax metric name checking to allow including dashes.
* Fix bug where linux_system_metrics was ignoring the configured sample interval time.

## 2.0.6 "Furious Falcon" - Apr 2, 2015

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Apr 2, 2015 16:30 -0700
--->

New features:

* Add a new option ``--set-server-host`` in scalyr-agent-2-config to set the server host from the commandline.
* Add new instance variables ``_log_write_rate`` and ``_log_max_write_burst`` to ScalyrMonitor to allow monitor developers to override the rate limits imposed on their monitor's log.  See the comments in test_monitor.py for more details.
* Add new parameter ``emit_to_metric_log=True`` to force a log line to go to the metric log instead of the agent log for monitors.  See the comments in test_monitor.py for more details.
* Added new configuration parameters to easily change any or all monitor's sample rate.  Use ``global_monitor_sample_interval`` in the general configuration to set it for all monitors, or ``sample_interval`` in an individual monitor's config.  The value should be the number of seconds between samples and can be fractional.

Bug fixes:

* Fix failing to accept unicode characters in metric values

## 2.0.5 "Eccentric Elk" - Feb 26, 2015

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Feb 26, 2015 13:30 -0800
--->

New features:

* Support for Windows.  Many changes to support this platform.

## 2.0.4 "Dubious Dog" - Jan 20, 2015

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Jan 20, 2015 13:00 -0800
--->

Bug fixes:

* Fix excessive CPU usage bug when monitoring thousands of logs that are not growing.

## 2.0.3 "Capricious Cat" - Dec 18, 2014

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Dec 18, 2014 14:45 -0800
--->

New features:

* The ``run_monitor.py`` takes a new option ``-d`` to set the debug level.

Bug fixes:

* Fix false warning message about file contents disappearing.
* Assign a unique thread id for each log file being copied to mimic old agent's behavior.

## 2.0.2 "Bashful Bovine" - Oct 31, 2014

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Oct 31, 2014 12:30 -0700
--->

New features:

* Added the MySQL, Apache, and Nginx monitor plugins.
* New functions for defining and adding documentation for Scalyr Plugin Monitor configuration options, log entries, and metrics.
* Added support for variable substitution in configuration files.
* New ``print_monitor_doc.py`` tool for printing documentation for a monitor.  This tool is experimental.

Bug fixes:

* Fixed bug that prevented having release notes for multiple releases in CHANGELOG.md
* Fixed bug with CR/LF on Windows preventing log uploads

Documentation fixes:

* Updated MySQL monitor documentation to note deprecated metrics.

Internal:

* Refactored code to extract platform-specific logic in preparation for Windows work.

## 2.0.1 "Aggravated Aardvark" - Sept 15, 2014

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Sept 15, 2014 16:15 -0700
--->

New core features:

* Complete rewrite of the Scalyr Agent in Python!
* No more Java dependency.
* Easier to configure.
* Easier to diagnosis issues.
* Monitor plugin support.
* Detailed status page.

Bugs fixed since beta and alpha testing:

* Slow memory "leak".
* graphite_module not accepting connections from localhost when only_accept_local is false.
* Ignore old pidfile if the process is no longer running.  Added pid collison detection as well.
