# Scalyr Agent (scalyr-agent-2)

[![CircleCI](https://circleci.com/gh/scalyr/scalyr-agent-2.svg?style=svg)](https://circleci.com/gh/scalyr/scalyr-agent-2)
[![codecov](https://codecov.io/gh/scalyr/scalyr-agent-2/branch/master/graph/badge.svg)](https://codecov.io/gh/scalyr/scalyr-agent-2)

This repository holds the source code for the Scalyr Agent, a daemon that collects logs and metrics from
customer machines and transmits them to Scalyr.

For more information on the Scalyr Agent, please visit https://www.scalyr.com/help/scalyr-agent.

To learn more about Scalyr, visit https://www.scalyr.com.

## Features

The Scalyr Agent is designed to be lightweight, easy to install, and safe to run on production systems.
Key features:

  * Pure Python implementation, supporting Python versions 2.6, 2.7 and >= 3.5
  * Lightweight (typically 15 MB RAM, 2% CPU or less)
  * Easy-to-use troubleshooting features
  * Modular configuration files
  * Extensibility using monitor plugins

## Release Notes and Changelog

For release notes please see [RELEASE_NOTES.md](RELEASE_NOTES.md) document and for changelog,
see [CHANGELOG.md](CHANGELOG.md) document.

## Developing

From this repository, you can create your own RPM and Debian packages containing customized versions of
the Scalyr Agent. For instance, you can bundle additional monitoring plugins to collect specialized data
from your servers.

We also welcome submissions from the community.

For information on the agent architecture and code abstractions, please refer to the
[architecture.md](docs/architecture.md) document.

### Local Development Environment, Tests and Lint Checks

This repository utilizes ``tox`` Python project for running various lint checks and tests.

For it to work, you need to have ``tox`` Python package installed on the system or inside the virtual
environment which you use for the development.

```bash
pip install tox
```

In addition to that, you also need to have Python version available which is used for a particular
tox target. By default Python 2.7 is used for the unit tests and Python 3.6 for all the lint checks.

To run all the checks you can simply run tox command:

```bash
tox
```

In addition to that, you can also run a specific target or a set of targets using ``-e`` flag. For example:

```bash
# run all the lint targets
tox -elint
# run flake8 and mypy tox target
tox -eflake8,mypy
# run py2.7-unit-tests tox target
tox -epy2.7-unit-tests
# run coverage tox target
tox -ecoverage
```

### Monitor Plugins

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

### Building Packages

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

### Pre-Commit Hooks

This project uses the [Black](http://black.readthedocs.io) code autoformatting tool with default
settings.

[Pre-commit](https://pre-commit.com) is used to automatically run checks including Black formatting
prior to a git commit.

To use pre-commit:

- Use one of the [Installation Methods](https://pre-commit.com/#install) from the documentation.
- Install the hooks with `pre-commit install`.
- To manually execute the pre-commit hooks (including black), run `pre-commit run --all-files` (
  run it on all the files) or ``pre-commit run`` (run it only on staged files).

All the pre-commit targets rely on binaries from tox virtual environment so you need to make sure
tox virtual environment for ``lint`` target exists:

```bash
tox -elint --notest --recreate
```

#### Pre-commit Configuration

- `.pre-commit-config.yaml` configures the scripts run by pre-commit

To update the Pre-commit hooks , run `pre-commit autoupdate`. This will update
`.pre-commit-config.yaml` and will need to be committed to the repository.

## Contributing

In the future, we will be pushing guidelines on how to contribute to this repository.  For now, please just
feel free to submit pull requests to the `master` branch and we will work with you.

## Copyright, License, and Contributors Agreement

Copyright 2014-2020 Scalyr, Inc.

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this work except in
compliance with the License. You may obtain a copy of the License in the [LICENSE](LICENSE.txt) file, or at:

[http://www.apache.org/licenses/LICENSE-2.0](http://www.apache.org/licenses/LICENSE-2.0)

By contributing you agree that these contributions are your own (or approved by your employer) and you
grant a full, complete, irrevocable copyright license to all users and developers of the project,
present and future, pursuant to the license of the project.
