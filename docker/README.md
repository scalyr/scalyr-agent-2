Scalyr Agent Docker Intergraion
===============================

This directory holds the configuration files and Docker build file used to
create the scalyr/scalyr-docker-agent Docker image.  This will run the Scalyr
Agent in a container with Docker-specific features turned on.

In particular, the key integration features are:

  * Send all logs received from other local containers via syslog to Scalyr
  * Automatically collect and report metrics to Scalyr from all local containers

## Building

To build the Docker image, you must execute the following commands:

    cd scalyr-agent-2/docker
    python ../build_package.py --no-versioned-file-name docker_tarball
    docker build -t scalyr/scalyr-docker-agent .
    
## 
