Scalyr Agent 2 Changes By Release
=================================

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
