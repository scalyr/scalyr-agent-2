# Build Agent docker images.

To build agent docker image run command:

```
python3 build_package_new.py <build_name>
```

Available builds:
* **[docker-json](https://app.scalyr.com/help/install-agent-docker)** - an image for running on Docker configured to fetch 
  logs via the file system (the container log directory is mounted to the agent container.) This is the preferred way 
  of running on Docker. This image is published to scalyr/scalyr-agent-docker-json. 
* **[docker-syslog](https://app.scalyr.com/help/install-agent-docker)** - an image for running on Docker configured to 
  receive logs from other containers via syslog. This is the deprecated approach (but is still published under 
  scalyr/scalyr-docker-agent for backward compatibility.)  We also publish this under scalyr/scalyr-docker-agent-syslog 
  to help with the eventual migration.
* **docker-api** - an image for running on 
    Docker configured to fetch logs via the Docker API using docker_raw_logs: false configuration option.

* **[k8s](https://app.scalyr.com/help/install-agent-kubernetes)** - an image for running the agent on Kubernetes.
    This image is published to scalyr/scalyr-k8s-agent.


This command will build the image, but only for a local use and only for the current architecture. That's because
image is build by using ``docker buildx`` and it can not pass multi-arch images back to the local docker engine.

To push image to the registry use optional argument ``--push``

```
python3 build_package_new.py <build_name> --push
```

That will push a result image to the default (dockerhub) registry. By default, it will use only
tag ``latest``, but it can be overwritten buy ``--tag`` options.

```
python3 build_package_new.py <build_name> --push --tag preview --tag debug
```

It is also possible to set other registries, for example, to spin up a container with local docker registry
and to push an image there. That is also a possible workaround for a local build's architecture limitation.
```
docker run --it --rm --name registry -p 5000:5000 registry:2

python3 build_package_new.py <build_name> --push --registry localhost:5000
```


