# Build Agent docker images

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

```bash
python3 build_package_new.py <build_name> --push
```

That will push a result image to the default (dockerhub) registry. By default, it will use only
tag ``latest``, but it can be overwritten buy ``--tag`` options.

```bash
python3 build_package_new.py <build_name> --push --tag preview --tag debug
```

It is also possible to set other registries, for example, to spin up a container with local docker registry
and to push an image there. That is also a possible workaround for a local build's architecture limitation.

```bash
docker run -it --rm --name registry -p 5005:5000 registry:2

python3 build_package_new.py <build_name> --push --registry localhost:5000
```

Pushing image with username:

```bash
python3 build_package_new.py <build_name> --push --user my-dockerhub-user
```

## Using Locally built images with minikube

If you want to use locally built images with minikube, the easiest way to do that is to load
local Docker image into minikube using ``minikube image load`` command as shown in the example
below:

```bash
minikube image load scalyr-k8s-agent:latest
python build_package_new.py k8s-debian --platforms linux/amd64
```

## Supported Images and Architectures

Right now we provide Debian bullseye-slim and Alpine linux based images for the following platforms:
  * ``linux/amd64``
  * ``linux/arm64``
  * ``linux/arm/v7``

Alpine based Linux images are around 50% smaller in size than Debian based ones and can be recognized
using ``-alpine`` tag name suffix (e.g. ``latest-alpine``).

Since cross compilation in emulated environments (QEMU) is very slow and pre-built ARM musl wheels
are not available, we don't bundle orjson and zstandard dependency in Alpine ARMv7 images.
