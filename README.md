scalyr-agent-2
==============
[![CircleCI](https://circleci.com/gh/scalyr/scalyr-agent-2.svg?style=svg)](https://circleci.com/gh/scalyr/scalyr-agent-2)

This repository holds the source code for the Scalyr Agent, a daemon that collects logs and metrics from
customer machines and transmits them to Scalyr.

For more information on the Scalyr Agent, please visit https://www.scalyr.com/help/scalyr-agent.

To learn more about Scalyr, visit https://www.scalyr.com.


Features
========

The Scalyr Agent is designed to be lightweight, easy to install, and safe to run on production systems.
Key features:

  * Pure Python implementation, supporting Python versions 2.4 and up
  * Lightweight (typically 15 MB RAM, 2% CPU or less)
  * Easy-to-use troubleshooting features
  * Modular configuration files
  * Extensibility using monitor plugins


Developing
==========

From this repository, you can create your own RPM and Debian packages containing customized versions of
the Scalyr Agent. For instance, you can bundle additional monitoring plugins to collect specialized data
from your servers.

We also welcome submissions from the community.

## Monitor plugins

Monitor plugins are one of the key features for Scalyr Agent 2.  These plugins can be used to augment the
functionality of Scalyr Agent 2 beyond just copying logs and metrics.  For example, there are monitor plugins
that will fetch page content at a given URL and then log portions of the returned content.  Another plugin allows
you to execute a shell command periodically and then log the output.  Essentially, plugs can be used to implement
any periodic monitoring task you have.

We encourage users to create their own plugins to cover features they desire.  In the near future, we will be
publishing documentation that describes how to implement your own monitor.  And, if you feel your monitor would
be useful to other Scalyr customers, we encourage you to submit it to monitor collection in the `monitors/contrib`
directory.

To learn how to develop plugins, please see the
[instructions for creating a monitor plugin](docs/CREATING_MONITORS.md).

## Building packages

You can use the `build_packages.py` script to build your own RPM or Debian packages.  This is often desirable
if your company has its own yum or apt repositories, or you have modified the Scalyr Agent 2 code to suit
some particular need.  (Of course, if you are finding you need to modify the Scalyr Agent 2 code, we encourage you
to submit your changes back to the main repository).

You must have the following installed on your machine to create packages:

  * fpm, see https://github.com/jordansissel/fpm/
  * rpmbuild (for building RPMs)
  * gnutar / gtar (for building Debian packages)

We strongly suggest you use the same platform that you intend to install the agent on to build the packages.
This is because tools like `rpmbuild` and `gtar` are more available on the platforms that use those respective
packaging systems.


To build the RPM package, execute the following command in the root directory of this repository

    python build_package.py rpm
    
To build the Debian package, execute the following command in the root directory of this repository

    python build_package.py deb
  
Contributing
============

In the future, we will be pushing guidelines on how to contribute to this repository.  For now, please just
feel free to submit pull requests to the `master` branch and we will work with you.




