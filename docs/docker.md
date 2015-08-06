#Building the docker image


From the root of the scalyr-agent repository run:

	python build_package.py docker

This will build a .deb package of the current source tree, create a new docker image based on Dockerfile.base and install the previously created .deb file.

Dockerfile.base creates an image off docker’s default ubuntu image, installs python and other dependencies, installs the previously created scalyr-agent.deb and sets a non-forking, non-changing-user scalyr-agent-2 as the default command for the image (scalyr-agent-2 needs to be non-forking so the container keeps running once it starts up otherwise docker will exit as soon as the entry point program exits.  If you are sharing an agent.json config file between the host and the containers, you also need to pass in --no-change-user to prevent missing user errors).

If needed, custom docker images can be created by making custom Dockerfiles and running the command

	docker build -f MyNewDockerfile -t <tag> .

Where &lt;tag&gt; typically follows the format `company/product:version` e.g. scalyr/scalyr-agent:test

#Running the scalyr-agent


Once you have created the scalyr-agent image, it can be run with the following command:

	docker run -d --name scalyr-agent -v /path/to/config/agent.json:/etc/scalyr-agent-2/agent.json scalyr/scalyr-agent:2.0.6

Where:

* `-d` is to run in detached mode (needed when running a daemon process such as the scalyr-agent)

* `--name scalyr-agent` names this container 'scalyr-agent'.  It is useful to give a fixed name to the scalyr-agent container, and if used, the docker_monitor plugin expects this to be 'scalyr-agent' by default (this can be configured with the container_name option in the agent.json if necessary).

* `-v /path/to/config/agent.json:/etc/scalyr-agent-2/agent.json` maps /path/to/config/agent.json on the host, to /etc/scalyr-agent-2/agent.json on the container.  This allows you to specify a custom config file when running the container.  Note, you can’t use ~ in this path. [See here](#permanent-config) for making a permanent config file.  

* `scalyr/scalyr-agent:2.0.6` specifies the tag of the image to run.  In this case for version 2.0.6 of the scalyr-agent.

If you want to see the available docker images on your machine, run the command

	docker images

If you would like to log the stdout/stderr of other docker containers via the docker_monitor plugin, you will also need to map the docker socket to the scalyr-agent container.  [See here](#docker-socket) for details.

You can also specify additional volumes on the command line, for example in case you want to make logs files from other containers available to the scalyr-agent container.  [See here](#log-volumes) for how to configure such volumes.

##Data files

If you wish to persist checkpoint information about already logged files and/or Docker logs, it is recommended that your scalyr data directory is also mapped from the host to the container e.g.
`-v /path/to/persistent/data-dir:/var/lib/scalyr-agent-2`


#Stopping the scalyr-agent container


Assuming you have a container named ‘scalyr-agent’ running, it can be stopped with the following command:

	docker stop scalyr-agent


#Restarting the scalyr-agent container

Assuming you have previously stopped a container named 'scalyr-agent', you can restart it with the command

	docker start scalyr-agent

#Checking the status of a running scalyr-agent container

To check the status of a currently running scalyr-agent container, use the following command:

	docker exec scalyr-agent scalyr-agent-2 --no-change-user status

or

	docker exec scalyr-agent scalyr-agent-2 --no-change-user status -v

to get more verbose output


# <a name="permanent-config"></a>Creating a permanent config file

If you wish to create a permanent config file for your scalyr-agent image so you don’t have to specify it on the command line each time, you can do it as follows:

	docker run -it -v /:/mnt/host --name custom-scalyr scalyr/scalyr-agent:2.0.6 /bin/bash

and from the container’s command prompt run

	$ cp /mnt/host/path/to/config/agent.json /etc/scalyr-agent-2/agent.json
	$ exit

Then commit this changes to a new image:

	docker commit -m "added custom scalyr config" custom-scalyr custom/scalyr-agent

You can now run the scalyr agent as follows:

	docker run -d --name scalyr-agent custom/scalyr-agent scalyr-agent-2 --no-fork --no-change-user start

Note, this method is less than ideal, because the image's default command gets overridden and so you need to specify the full command and arguments each time.

An alternative method is to create a custom Dockerfile to copy your custom config file during the docker build process.

# <a name="log-volumes"></a>Logging files from other containers


In order to log files from other containers, you must share volumes containing those log files with the scalyr-agent container.  You can then configure the scalyr-agent's agent.json file as per normal to copy those files to the Scalyr servers.

There are numerous ways to share volumes from other containers.  See the docker documentation on [managing data in containers](https://docs.docker.com/userguide/dockervolumes/)

As a simple example, imagine you have an apache container, that was configured to log its access files to `/var/log/httpd/access.log` on the host.  When running the scalyr-agent container you would simply map that file to a file in container with the -v command line parameter: `-v /var/log/httpd/access.log:/var/log/httpd/access.log`

So the full command to run the container would be:

	docker run -d --name scalyr-agent -v /path/to/config/agent.json:/etc/scalyr-agent-2/agent.json -v /var/log/httpd/access.log:/var/log/httpd/access.log -v /run/docker.sock:/var/scalyr/docker.sock  scalyr/scalyr-agent:2.0.6

You would then configure your agent.json to have:

	logs: [
		{
			path: "/var/log/httpd/access.log",
			attributes: {parser: "accessLog"}
		},
	]

And scalyr will automatically start tracking this file.

If you have multiple containers that each have files you wish to upload, you should probably consider creating a [Data Volume Container](https://docs.docker.com/userguide/dockervolumes/#creating-and-mounting-a-data-volume-container)

This volume would be shared among all containers, with each container configured to output log data to a specific path.

e.g. assuming you had followed the instructions in the link above and created a data volume container called 'logdata'.  You could then run the scalyr-agent container with the following command:

	docker run -d --name scalyr-agent --volumes-from logdata -v /path/to/config/agent.json:/etc/scalyr-agent-2/agent.json scalyr/scalyr-agent:2.0.6

And configure the scalyr agent’s agent.json to track any files of interest that existed in logdata’s volumes.

# <a name="docker-socket"></a>Logging Stdout

If you would like to use the scalyr-agent container to log another container’s stdout/stderr, this can be done with the built-in docker_monitor plugin.  In the monitors section of your agent.json file, add something similar to:

	monitors: [
		{   
			module: "scalyr_agent.builtin_monitors.docker_monitor",
		}   
	]

The docker_monitor module has a number of configuration options:

* `container_name` - the container name of the scalyr-agent container.  Defaults to scalyr-agent.  If you have specified a different name for the container with the --name parameter of the docker run command, you will need to specify that value here.

* `api_socket` - the unix socket on the container used to communicate to the Docker API.  Defaults to /var/scalyr/docker.sock  This needs to be mapped from the /run/docker.sock of the host.

* `docker_log_prefix` - a prefix added to the start of all log files created by the docker_monitor plugin.  Defaults to 'docker', so for a container named 'my-container', the plugin would create the log file docker-my-container-stdout.log

* `max_previous_lines` - when starting to track the logs of a container, the maximum number of lines to search backwards to find the most recent output.  Defaults to 5000.

* `log_timestamps` - whether or not to include the Docker timestamps in the logs.  Defaults to False.

When running, the docker_monitor plugin will upload standard error and output of all running docker containers on the host.

In order to have access to logs from other containers, the docker_monitor plugin requires a valid docker API socket.  You can provide this socket to the scalyr-agent container when you run it by adding an extra -v parameter to the run command `-v /run/docker.sock:/var/scalyr/docker.sock`

Which maps `/run/docker.sock` on the host to `/var/scalyr/docker.sock` on the container. Note that for the mapping to work, neither of these paths can contain symbolic links, hence the need for /run/docker.sock rather than /var/run/docker.sock

A typical run command making use of this would look something like:

	docker run -d --name scalyr-agent -v /path/to/config/agent.json:/etc/scalyr-agent-2/agent.json -v /run/docker.sock:/var/scalyr/docker.sock scalyr/scalyr-agent:2.0.6
