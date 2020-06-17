# AWS AMI Based Package Tests

This directory contains scalyr-agent-2 package install and upgrade sanity
tests.

Those tests utilize Apache Libcloud to spin up a new temporary EC2 instance
and run basic installer fresh install and upgrade sanity checks.

For example usage and which variables need to be set, please refer to the
script file module level docstring.

## Supported Distros

Right now tests run on the following distros and operating systems on each merge to master and
also daily as part of our Circle CI job:

* Ubunut 14.04
* Ubunut 16.04
* Ubunut 18.04
* Debian 10
* CentOS 7
* CentOS 8
* Amazon Linux 2
* Windows Sever 2012
* Windows Sever 2016
* Windows Sever 2019

## Using Windows images

Apache Libcloud operates EC2 instances by ssh, so we need to install OpenSSH server on windows images
before we can use them.

Also, you can use script `windows/install_openssh.ps1`. It downloads, installs and configures openssh server.

```
$Env:PUBLIC_KEY="<your public key>"
install_openssh.ps1
```
