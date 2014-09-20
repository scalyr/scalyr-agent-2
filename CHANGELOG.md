Scalyr Agent 2 Changes By Release
=================================

## 2.0.1 "Aggravated Aardvark" - Sept 11, 2014

<!---
Packaged by Steven Czerwinski <czerwin@scalyr.com> on Sept 11, 2014 15:12 -0600
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
