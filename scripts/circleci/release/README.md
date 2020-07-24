# Install script building using CircleCI pipeline.

In this folder you can find files which are used to build convenience install script for the Scalyr agent.
You can also find this script in the https://app.scalyr.com/help/install-agent-linux page.

The install script is nothing but a bash script with bootstrap packages which are attached to the end it.
The script parses itself and finds the place where packages begin and extracts them.
After that script determines the current OS and
finds available package managers and tries to use appropriate bootstrap package. For now there are deb and rpm packages.

Here, is the release folder you can find the following files.

* `installScalyrAgentV2.sh` - the actual install script.
* `create-agent-installer.sh` - this script builds bootstrap repo packages, packs them into single tarball
and attaches it to `installScalyrAgentV2.sh` file.

* `public_keys` folder - contains GPG public key files which are used in the bootstrap packages for the signature checking.


The `create-agent-installer.sh`and other files are used in the `build-linux-packages-and-installer-script` job
 in the CircleCi pipeline  to produce build artifacts.
After that those artifacts are ready to be used in the further release process.