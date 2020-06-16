# AWS AMI Based Package Tests

This directory contains scalyr-agent-2 package install and upgrade sanity
tests.

Those tests utilize Apache Libcloud to spin up a new temporary EC2 instance
and run basic installer fresh install and upgrade sanity checks.

For example usage and which variables need to be set, please refer to the
script file module level docstring.


## Using Windows images.

Apache Libcloud operates EC2 instances by ssh, so we need to install OpenSSH server on windows images
before we can use them.

Also, you can use script `windows/install_openssh.ps1`. It downloads, installs and configures openssh server.

```
$Env:PUBLIC_KEY="<your public key>"
install_openssh.ps1
```