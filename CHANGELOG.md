Scalyr Agent 2 Changes By Release
=================================

## 2.0.54 "Galactica" - Oct 18, 2019

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Oct 18, 2019 15:00 -0700
--->

Note, this release is pending an actual release date is TBD

Features
* Added TSLite support to allow customers using Python 2.6 to connect via TLSv1.1

Miscellaneous changes
* Test cleanups

## 2.0.53 "Firefly" - Sep 18, 2019

<!---
Packaged by Imron Alston <imron@scalyr.com> on Sep 18, 2019 15:00 -0700
--->

Features
* Collection of per CPU metric data under docker/kubernetes has been placed behind a config option to prevent collecting excessive metrics on machines with a large number of cores.

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
