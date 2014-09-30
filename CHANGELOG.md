Scalyr Agent 2 Changes By Release
=================================

## 2.0.2 "Bashful Bovine" - Oct 15, 2014

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Oct 15, 2014 16:15 -0700
--->

This release is under active development.  The release date is TBD and will be updated.

New features:

* Support for the MySQL monitor plugin

Bug fixes:

* Fix bug prevented having release notes for multiple releases in CHANGELOG.md

Documentation fixes:

* Update MySQL monitor documentation to note deprecated metrics.

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
