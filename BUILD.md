# Build Agent docker images

In order to work with images, use the next commands of the build script:

```bash
python3 build_package_new.py image <builder_name> <action>
```

where: 

`builder_name` is name of the builder, for now there are `ubuntu` and `alpine` builder, that build images, which are
based on those respective distibutions.

and ``action`` is the action that has to be done, for now it can be:

* ``publish``: Build and already publish image to a registry


* ``build-tarball`` Build image in the for of OCI layout tarball. May be useful when you need to 
need image in form of the file. For example, we use this tarball in our GitHub Action CI/CD when
we build our images in the form on tarballs and share those tarballs with others, for example test jobs.


* ``load`` Build and loads docker image directly to the current docker engine, so the image has to appear 
in the result of the ``docker image ls`` command. This is only a single arch image because docker 
does not store multi-arch images.

## Publish an image

In order to publish agent image, additional options has to be provided to the ``publish`` command

``image-type``: Type of the images. Available image types:

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

next required options can be looked up by running the command:

```python3 build_package_new.py image <builder_name> publish --help```

As an example you can publish image to a local registry in a container.

```bash
docker run -it --rm --name registry -p 5005:5000 registry:2

python3 build_package_new.py image ubuntu publish --image-type k8s --registry localhost:5000 --tags=latest --registry-username user --no-verify-tls
```

NOTE: This builds a multi-arch image with all supported architecture. 
Meaning that you will have to wait longer because non-native architecture requirement are build with using emulation.
If you need image just to run it on your local machine, you can use the ``load`` command instead of ``publish``

## Using locally built images with minikube

If you want to use locally built images with minikube, the easiest way to do that is to load
local Docker image into minikube using ``minikube image load`` command as shown in the example
below:

```bash
python3 build_package_new.py image ubuntu k8s load --image-type k8s --image-name my-image:latest

minikube image load my-image:latest
```

In addition to that, you also need to update ``k8s/no-kustomize/scalyr-agent-2.yaml``  image
section to look something like this:

```yaml
...
        image: my-image:latest
        imagePullPolicy: Never
...
```

## Supported Images and Architectures

Right now we provide Debian bullseye-slim and Alpine linux based images for the following platforms:
  * ``linux/amd64``
  * ``linux/arm64``
  * ``linux/arm/v7``

Alpine based Linux images are around 50% smaller in size than Debian based ones and can be recognized
using ``-alpine`` tag name suffix (e.g. ``latest-alpine``).


# Build agent Linux packages.

To build agent package for Linux which is managed by OS's package manager run command:

```
python3 build_package_new_refactored.py <build_name> [--last-repo-python-package-file <python_package_file>] [--last-repo-agent-libs-package-file <agent_libs_file>]
```

Possible values for the 'build_name':
    - deb-{amd64}
    - rpm-{x86_64}

It is important to note that along with the agent package itself, the dependency packages ``scalyr-agent-python3`` and 
``scalyr-agent-libs`` are also built. Since those packages are updated less often than the agent package and if 
they are already presented in the repository, then we can provide additional options ``--last-repo-python-package-file`` 
and ``--last-repo-agent-libs-package-file`` to the command, so those existing dependency packages will be reused from 
that repo.


