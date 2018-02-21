Scalyr Agent Docker Integration
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
    
## Running the Scalyr Agent in Docker

To run a Scalyr Agent container, you must first create a file containing a write logs key from
your Scalyr account.  The file should look like:

    {
      api_key: "YOUR KEY HERE"
    }

In this example, we will store the file in /tmp/api_key.json

You must also verify the location of the docker daemon unix socket.  In the example below, we assume
it is stored in `/run/docker.sock`.  Another common location is `/var/run/docker.sock`.  Be sure that
you reference the actual socket and not a symlink to it.  Use `ls -l` to determine that.

To run the Scalyr Agent container, execute the following commands:

    docker run -d --name scalyr-docker-agent -v /tmp/api_key.json:/etc/scalyr-agent-2/agent.d/api_key.json -v /run/docker.sock:/var/scalyr/docker.sock -p 601:601

## Configuring local containers to send their logs to Scalyr

Once you have the Scalyr Agent container running, you may configure other containers on the same
physical host to send their logs to Scalyr through it.

To do this, you must add the following options when you start a container: `--log-driver=syslog --log-opt syslog-address=tcp://127.0.0.1:601`

The following is an example of a small container that will write `Hello Word` repeatedly to Scalyr:

    docker run  --log-driver=syslog --log-opt syslog-address=tcp://127.0.0.1:601 -d ubuntu /bin/sh -c "while true; do echo hello world; sleep 1; done"
