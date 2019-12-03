# Objective
This module is used to run the tests under scalyr_agent/tests on different OS platforms
with different Python versions. The objective is to make sure the Scalyr Agent runs the same way
in different distributions of supported OS (Windows/Linux/OSX etc.)

# Steps
The Platform Tests are run by:
* iterating over all the Dockerfiles under scalyr_agent/platform_tests
* for each Dockerfile:
    * create a Docker Image
    * run a container
    * run the tests.
* Once the tests have run, destroy the container and the images created.

# Goal and Further Actions
* Completeness: We should be able to run the tests on possibly all OS and their distributions if possible.
* Sensitivity: The tests should be sensitive to breakage and should alert if something breaks in any environment.
This means we need host machines like Jenkins etc. to have these tests run and gather reports and alert on breakage,
possibly on each PR requested? TBD




# Windows Tests

The Windows tests cannot be run like the Linux platform tests from OSX machines because
of the differences in the system architecture. We need a Virtual Machine for that.

We can set up a Windows VM by doing:

* Install vagrant on the host machine. https://www.vagrantup.com/docs/installation/
* Download and install Virtualbox as the OS image provider. https://www.virtualbox.org/wiki/Downloads
* Choose a Windows Vagrant image. eg: https://app.vagrantup.com/kensykora/boxes/windows_2012_r2_standard
and follow the instruction eg:

```
vagrant init kensykora/windows_2012_r2_standard

vagrant up --provider=virtualbox
```
* Remote Desktop into the Windows VM.
```
vagrant rdp
```

* Install Python for windows.

* Install git for Windows.

* Go to the ``cmd`` terminal.

* Download the Scalyr Agent Repo:

```
git init

git config --local user.name "Scalyr"

git config --local user.email support@scalyr.com &&

git clone -b release git://github.com/scalyr/scalyr-agent-2.git
```

* Run the tests:

```
cd scalyr-agent-2

python run_tests.py
```
