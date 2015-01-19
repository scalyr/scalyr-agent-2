Scalyr Agent 2 Changes By Release
=================================

## 2.0.4 "Dubious Dog" - Jan 22, 2015

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Jan 22, 2015 14:45 -0800
--->

This release is still be developed and the actual contents and release date are TBD.

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
