Scalyr Agent 2 Changes By Release
=================================

## 2.0.16 "Operating Otter" - January 31, 2016

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Jan 31, 2016 11:30 -0800
--->

Note, this release is under development.  Actual release date is TBD.

Features:

* Windows Event Log monitor now supports the EvtLog API implemented by Windows Vista and newer system.  This allows for more expressive queries, as well as selecting events by severity level such as "Critical".

Bug fixes:

* Fix UTF-8 truncation bug in redis plugin.
* New option in redis plugin that controls logging of UTF-8 converstion errors.  See the ``utf8_warning_interval`` for more details.


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
