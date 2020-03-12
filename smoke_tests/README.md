Scalyr Agent 2 Smoke tests
=================================

##Settings for local testing.

Every smoke test requires some essential environment variables to be set.
In general, CI provides it own variables, but for local testing you must provide yours.

There is an option in root `conftest.py` file called `--test-config`.
This should be a path to the yaml file with the following structure:

```yaml
agent_settings:
  SCALYR_API_KEY: # this goes as environment variable.
  READ_API_KEY: # this goes as environment variable.
  SCALYR_SERVER: # this goes as environment variable.
  AGENT_HOST_NAME: # this goes to agent.json config as 'server_attributes.serverHost'
```

**NOTE:** By default, py.test expects file named `config.yml` in the root directory of the smoke tests - `smoke_tests/config.yml`.
 You can create this file and it will be used by py.test automatically.\
For your convenience, this file is added to `.gitignore`.
 Also, there is a blank version of this file `smoke_tests/blank_config.yml` and you can make a copy and fill it.

The main purpose of this file(and the option in general) is to be a centralized and unified way to configure smoke tests
when they are running locally.


###standalone_smoke_test.py
This file contains basic test cases for agent which is running on the same machine
directly from source or as installed package.


To run test use following command:
```
py.test smoke_tests/standalone_smoke_tests
```

For more options see `custom options:` section by running

```
py.test smoke_tests/standalone_smoke_tests --help
```

### package_smoke_tests
This directory contains tests cases for agent which is installed from package, for example `rpm` or `deb`.

Package smoke tests run inside docker containers because they are too specific to run locally, for example:
- agent installation from package will interfere with system files, this is not safe.
- different packages types can require different operating systems and not all of them can even be installed
on the local machine.

The package smoke test execution flow is the same as in the standalone agent test.
Moreover, it just runs 'standalone_smoke_test.py' test but just inside docker container.
The main job for package smoke test is to prepare image with needed environment, build needed package and install it.

To run test use following command:
```
py.test smoke_tests/package_smoke_tests
```

For more options see `custom options:` section by running

```
py.test smoke_tests/package_smoke_tests --help
```
