Scalyr Agent Docker Integration
===============================

This directory holds the configuration files and Docker build file used to
create the scalyr/scalyr-docker-agent Docker image.  This will run the Scalyr
Agent in a container with Docker-specific features turned on.

In particular, the key integration features are:

  * Send all logs received from other local containers via syslog to Scalyr
  * Automatically collect and report metrics to Scalyr from all local containers

## Building

We support two Docker images:
- **scalyr-docker-agent-json**: uploads Docker logs captured by the Docker JSON File logging driver.
- **scalyr-docker-agent-syslog**: uploads Docker logs captured by the Docker Syslog File logging driver.  

We recommend customers use the **scalyr-docker-agent-json** image.

Use the following commands to build the respective images:

#### scalyr-docker-agent-json

    cd scalyr-agent-2/docker
    python ../build_package.py --no-versioned-file-name docker_json_builder
    ./scalyr-docker-agent-json --extract-packages
    docker build -t scalyr/scalyr-docker-agent-json .

#### scalyr-docker-agent-syslog

    cd scalyr-agent-2/docker
    python ../build_package.py --no-versioned-file-name docker_syslog_builder
    ./scalyr-docker-agent-syslog --extract-packages
    docker build -t scalyr/scalyr-docker-agent-syslog .

## Running the Scalyr Agent in Docker

To run a Scalyr Agent container, you must do the following 3 things:

#### scalyr-docker-agent-json

1) Pass the API key in one of two ways:

    a) Through the `SCALYR_API_KEY` environment variable
    
    b) Through config file as follows: 
       
       First create a file containing a write logs key from your Scalyr account.  The file should look like:
    
        {
          api_key: "YOUR KEY HERE"
        }
    
        In this example, we will store the file in /tmp/api_key.json
    
2) Verify and map the location of the docker daemon unix socket.  In the example below, we assume
it is located at `/run/docker.sock`.  Another common location is `/var/run/docker.sock`.  Be sure 
you reference the actual socket and not a symlink to it.  Use `ls -l` to determine that.

3) Map `/var/lib/docker/containers` to the Docker containers directory.
    
    `-v /var/lib/docker/containers:/var/lib/docker/containers`

Here is an example of the complete command:

    docker run -d --name scalyr-docker-agent-json \
    -v /tmp/api_key.json:/etc/scalyr-agent-2/agent.d/api_key.json \
    -v /run/docker.sock:/var/scalyr/docker.sock \
    -v /var/lib/docker/containers:/var/lib/docker/containers \
    scalyr/scalyr-docker-agent-json
    
Or if setting API key via environment:    
    
    docker run -d --name scalyr-docker-agent-json \
    -e SCALYR_API_KEY=<Your api key> \ 
    -v /run/docker.sock:/var/scalyr/docker.sock \
    -v /var/lib/docker/containers:/var/lib/docker/containers \
    scalyr/scalyr-docker-agent-json

#### scalyr-docker-agent-syslog

To run the Syslog version, steps (1) and (2) are the same, but for step (3), you don't map in the
containers directory.

    docker run -d --name scalyr-docker-agent-syslog \
    -e SCALYR_API_KEY=<Your api key> \
    -v /run/docker.sock:/var/scalyr/docker.sock \
    scalyr/scalyr-docker-agent-syslog

Note: by default, the scalyr-agent-syslog container exposes tcp port 601 and udp port 501

## Configuring local containers to send their logs to Scalyr

Once you have the Scalyr Agent container running, other containers on the same physical host can then send their 
logs to Scalyr through the Scalyr Agent container.  The following is an example of a small container that will write `Hello World` repeatedly to Scalyr:

    docker run -d ubuntu /bin/sh -c "while true; do echo hello world; sleep 1; done"

Note that no extra configuration was needed if you're running the `scalyr-docker-agent-json` image. 

In contrast, if you're running the `scalyr-docker-agent-syslog` version, you will need to configure all containers 
to send logs via the Syslog protocol. To do this, add the following options when starting a container: 

    `--log-driver=syslog --log-opt syslog-address=tcp://127.0.0.1:601`

    Thus, the docker run command becomes:

    docker run --log-driver=syslog --log-opt syslog-address=tcp://127.0.0.1:601 \
    -d ubuntu /bin/sh -c "while true; do echo hello world; sleep 1; done"
