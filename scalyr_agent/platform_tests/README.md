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

# Goal and Further Actions:
* Completeness: We should be able to run the tests on possibly all OS and their distributions if possible.
* Sensitivity: The tests should be sensitive to breakage and should alert if something breaks in any environment. 
This means we need host machines like Jenkins etc. to have these tests run and gather reports and alert on breakage, 
possibly on each PR requested? TBD
