# AWS AMI Based Package Tests

This directory contains scalyr-agent-2 package install and upgrade sanity
tests.

Those tests utilize Apache Libcloud to spin up a new temporary EC2 instance
and run basic installer fresh install and upgrade sanity checks.

For example usage and which variables need to be set, please refer to the
script file module level docstring.
