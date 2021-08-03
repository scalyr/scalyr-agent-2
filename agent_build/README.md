
## How to build a package?


Here is a small example of how to build a package:
```bash
python3 agent_build/build_package.py <PACKAGE_TYPE> build --output-dir <OUTPUT_PATH>
```

Here is a list of available package types:

* `deb` - For the Debian based package managers such `apt`
* `rpm` - For Red Hat Enterprise Linux based packages managers.
* `tar` - Standalone tarball.
* `msi` - Msi installer for Windows.

The `deb`, `rpm` and `tar` packages are built in a docker by default, so there is no need
to prepare the system by installing all tools that are required for the build. All that is needed is docker.

For the `msi` package dockerized approach is not working yet, so it is needed to install all required tools 
in order to be able to perform the build.

Here is a command how do that.

_WARNING: This command makes changes to the system where it runs, and it expects freshly created 
environment without any additional installations (for example CI/CD environment). Be careful when running it 
on your machine to prevent bad things._

```bash
python3 agent_build/build_package.py msi prepare-build-environment --output-dir <OUTPUT_PATH>
```
