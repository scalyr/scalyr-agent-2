Scalyr Agent 2 Smoke tests
=================================

###standalone_smoke_test.py
This file contains test cases for agent which is installed on the same machine.

### package_smoke_tests
This directory contains tests cases for agent which is installed from package, for example `rpm` or `deb`.

Package smoke tests run inside docker containers because they are too specific to run locally, for example:
- agent installation from package will interfere with system files, this is not safe.
- different packages types can require different operating systems and not all of them can even be installed
on the local machine.

The package smoke test execution flow is the same as in the standalone agent test.
Moreover, it just runs 'standalone_smoke_test.py' test but just inside docker container.
The main job for package smoke test is to prepare image with needed environment, build needed package and install it.

