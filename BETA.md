Scalyr Agent Python 3 support: Beta release
===========================================

## Python 3 support

Scalyr is in the final stages of preparing the 2.1 release of the Scalyr Agent.
This will be a significant update of the Scalyr Agent code base that
adds in support for running under Python 3.

As part of the preparation, we are inviting Scalyr users to install
a beta version of the 2.1 release.  By testing out the beta release,
you will be able to ensure the upcoming changes work for your
particular environment before they are pushed to the stable repositories.

## Requirements

* Install beta release directly on host using either `apt install` or `yum`
* System Python must be `2.6`, `2.7` or `>=3.5`
* `/usr/bin/env python` must point to the desired Python version to run the agent

The 2.1 release can also be run under Kubernetes and Docker.  However,
Scalyr wishes to focus the initial beta testing on those users running the
Scalyr Agent directly on the host.

We are also not yet releasing a beta of the Scalyr Agent on Windows.

## Warning!

This is a beta release.  We *STRONGLY* recommend that you only run the
beta release on your non-production environments.  Ideally, you would run
it on your normal qualification environments to test the Scalyr Agent
runs both your current and planned future systems.

## Instructions

The following instructions will configure your system to use the
beta package repositories and install the current beta release:

For accounts hosted on `www.scalyr.com`, use:

    curl -sO https://scalyr-repo.s3.amazonaws.com/beta/latest/install-scalyr-agent-2-beta.sh
    sudo bash ./install-scalyr-agent-2-beta.sh --set-api-key "<WRITE LOGS API KEY>"

For accounts hosted on `eu.scalyr.com`, use:

    curl -sO https://scalyr-repo.s3.amazonaws.com/beta/latest/install-scalyr-agent-2-beta.sh
    sudo bash ./install-scalyr-agent-2-beta.sh --set-scalyr-server "https://upload.eu.scalyr.com" --set-api-key "<WRITE LOGS API KEY>"

After you execute this script, your system will be configured to use the beta release.
You may use `apt-get install scalyr-agent-2` or `yum update scalyr-agent-2` to upgrade
to new versions of the beta release as we publish them.

This script will attempt to remove any previously installed versions of the Scalyr Agent
and its repositories.  However, if you do have issues, please first try to manually remove
the old packages using the following commands:

For yum based systems:

    yum remove -y scalyr-agent-2
    yum remove -y scalyr-repo
    yum remove -y scalyr-repo-bootstramp

For apt based systems:

    dpkg -r scalyr-agent-2
    dpkg -r scalyr-repo
    dpkg -r scalyr-repo-bootstrap

## Breaking changes from Scalyr Agent 2.0.X

Good news, there are no breaking changes from the previous versions of the
Scalyr Agent.  You can use the same configuration and get the same
functionality as you have in the past.

## Known issues

Scalyr has done extensive correctness testing of the 2.1 release under
both Python 2 and 3.  We are currently conducting performance and resource
utilization testing with initial results not indicating any large problems.
We have also tested the Scalyr Agent on the distributions most frequently
used by our users, but still need to test less popular ones.

There is one currently known issue we are still investigating:

* Slow memory usage growth over time (~300KB per day)

## Reporting problems

As always, if you have any difficulties, please contact `support@scalyr.com` and
clearly mention that you are using the beta release of the Scalyr Agent.
