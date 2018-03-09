# Install Scalyr Agent (Kubernetes)

This document describes the recommended method for importing logs from a Kubernetes cluster to Scalyr.

These instructions are for installing the Scalyr Agent as a Daemonset on your Kubernetes cluster. If you plan to run the Agent directly on Linux, see the [Linux installation page](https://www.scalyr.com/help/install-agent-linux). For Windows, see the [Windows installation page](https://www.scalyr.com/help/install-agent-windows), and for running the Agent separately in a Docker container, see the [Docker installation page](https://www.scalyr.com/help/install-agent-docker).

The Scalyr Agent is a daemon that uploads logs and system metrics to the Scalyr servers. This page provides streamlined instructions to get you up and running quickly in a Kubernetes environment.

In our recommended architecture, you will run the Scalyr Agent as a Daemonset on your cluster. The Daemonset runs a Scalyr Agent pod on each node in your cluster that will collect logs and metrics from all other pods running on the same node. Note that this will run the agent on the master node; if you do not want to run the agent on the master, comment the following in https://github.com/scalyr/scalyr-agent-2/blob/k8s_preview/k8s/scalyr-agent-2.yaml:

```
tolerations:
  - key: "node-role.kubernetes.io/master"
    operator: "Exists"
    effect: "NoSchedule"
```

To create and launch the Scalyr Agent Daemonset, please do the following:

1. Configure a secret that contains your Scalyr API key

```
kubectl create secret generic scalyr-api-key --from-literal=scalyr-api-key="<your scalyr api key>"
```

2. Launch the Daemonset

```
kubectl create -f https://raw.githubusercontent.com/scalyr/scalyr-agent-2/k8s_preview/k8s/scalyr-agent-2.yaml
```

## That's It!

We hope that was easy. If you've had any trouble, please [let us know](support@scalyr.com). Otherwise, if this is your first time using Scalyr, this would be an excellent time to head on to the [Getting Started guide](https://www.scalyr.com/help/getting-started).

You should also check out the [Log Parsing](https://www.scalyr.com/help/parsing-logs) page to set up a parser for your logs. Scalyr becomes an even more powerful tool for analysis and visualization when your logs are properly parsed.

For complete documentation on agent configuration options, see the [agent reference](https://www.scalyr.com/help/scalyr-agent).

For more details on creating custom images with your configuration files, modifying the configuration files in the agent, setting a server host name, assigning parsers, etc, read on...

## Further Reading

### Creating custom Scalyr Agent configurations

The default Kubernetes configuration file for the Scalyr Agent does the following:

* Creates a Daemonset running the `scalyr/scalyr-k8s-preview-agent:latest` container image (this image is available on Dockerhub).  This image differs from our standard docker container `scalyr-docker-agent` in that it has been configured to read the raw container logs from the Kubernetes node rather than relying on syslog or the Docker API.

* Maps `/var/lib/docker/containers` of the node to `/var/lib/docker/containers` on the scalyr-k8s-preview-agent container.  This gives the container access to the raw logs from other pods and containers running on that node.

* Exposes your Scalyr API key to the container in the environment variable `SCALYR_API_KEY`.  This is required by the default scalyr configuration file of the scalyr-k8s-preview-agent image.

You can see the full configuration file [here](https://raw.githubusercontent.com/scalyr/scalyr-agent-2/k8s_preview/k8s/scalyr-agent-2.yaml).

### Creating custom Scalyr Agent Docker images

You can turn on several useful features in the Scalyr Agent by modifying its configuration files. Modifying these files on a single instance of the Scalyr Agent is relatively simple, but can become burdensome when you wish to use the same configuration files on many nodes in your cluster. To ease this burden, we have provided tools to allow you to easily create new Scalyr Agent Docker images that include your custom configuration files, which you can then run on your Kubernetes cluster.

You can create a test a configuration on a single Docker container and once it is working to your satisfaction you can use these tools to export the configuration along with a Dockerfile that will build a custom image that uses your custom configuration.

Assuming you have created and tested your configuration changes on a standalone docker container called 'scalyr-agent' (based off the `scalyr/scalyr-k8s-preview-agent:latest` image) you can create a custom Docker image based on that configuration by executing the following commands on the currently running container:

```
mkdir /tmp/scalyr-agent
cd /tmp/scalyr-agent
docker exec -i scalyr-agent scalyr-agent-2-config --k8s-create-custom-dockerfile - | tar -xz
docker build -t customized-scalyr-k8s-preview-agent .
```

This will leave a new Docker image on your local Docker instance with the repository tag `customized-scalyr-k8s-preview-agent`. You can change the name using the docker tag command. From there, you can use any of the standard methods to make this container available to your Kubernetes cluster.

You can launch a Daemonset that uses the new Scalyr Agent container by changing the `image` specified in your Kubernetes config file:

```
...
spec:
  template:
      spec:
        containers:
        - name: scalyr-agent
          image: customized-scalyr-k8s-preview-agent
...
```

and then launching the Daemonset based on the new configuration file

`kubectl create -f my-custom-configuration.yaml`

### Testing your custom configuration locally

Before deploying a custom Scalyr Agent image to your cluster, it's a good idea to test it locally first to make sure there are no configuration errors or problems.

 This can be done via Docker with the following command:

```
docker run -ti -e SCALYR_API_KEY="$SCALYR_API_KEY" \
  --name scalyr-k8s-preview-agent \
  -v /var/lib/docker/containers:/var/lib/docker/containers \
  -v /var/run/docker.sock:/var/scalyr/docker.sock \
  customized-scalyr-k8s-preview-agent /bin/bash
```

Which will launch a single container based on your customized image and drop you in to a bash shell.

Make sure to replace `$SCALYR_API_KEY` with your scalyr api key (or export it to an environment variable called `$SCALYR_API_KEY` before running the above command in order to expose your api key to the container.

Then from the shell prompt you can manually launch the Scalyr agent by executing:

``scalyr-agent-2 start``

If everything is configured correctly, you should see a message similar to 'Configuration and server connection verified, starting agent in background.'

Once you can confirm that the scalyr-agent runs correctly and is uploading logs to the Scalyr server, then you are ready to run that container on your Kubernetes cluster.

### Modifying configuration files

If you want to modify the configuration of the Scalyr Agent on the fly, you need to create and enable a [Config Map](https://kubernetes.io/docs/tasks/configure-pod-container/configmap/#understanding-configmaps).

You can create a Config Map based on an existing Scalyr Agent's configuration.  For example, if you had a test container called `scalyr-k8s-preview-agent` running on Docker as a standalone container you can run the following commands to export its configuration files:

```
mkdir /tmp/scalyr-agent-config
cd /tmp/scalyr-agent-config
docker exec -i scalyr-k8s-preview-agent scalyr-agent-2-config --export-config - | tar -xz
```

After these commands finish, your current directory will have one file agent.json and a directory agent.d. The agent.json file is a copy of the running Scalyr Agent's /etc/scalyr-agent-2/agent.json configuration file. Likewise, the agent.d directory is a copy of the /etc/scalyr-agent-2/agent.d directory.

**Note:** It's important to run this command on a container based off the scalyr/scalyr-k8s-preview-agent rather than the scalyr/scalyr-docker-agent in order to have the correct default configuration.

You can then edit those files to make whatever changes you need and write the changes back to the container for further testing, with this command:

```
tar -zc agent.json agent.d/* | docker exec -i scalyr-k8s-preview-agent scalyr-agent-2-config --import-config -
```

There is no need to restart the Scalyr Agent after writing the configuration files. The running Scalyr Agent should notice the new configuration files and read them within 30 seconds.

Once you have configured the Agent to your needs, and confirmed the configuration changes are working as expected, export the configuration files once more, and in the exported directory (which will contain a single agent.json file and an agent.d/ directory) you can execute the following command to create a Config Map called `scalyr-config`

```
kubectl create configmap scalyr-config $(for i in $(find .); do echo "--from-file=\"$i\""; done)
```

This creates a single config map containing all files in the current directory and any subdirectories.

Once you have created a Config Map, you need to add it to the Daemonset's configuration.  This can be done as follows:

```
...
spec:
  template:
    spec:
      containers:
        volumeMounts:
        - name: scalyr-config
          mountPath: /etc/scalyr-agent-2
...          
      volumes:
        - name: scalyr-config
          configMap:
            name: scalyr-config
...
```

This will write the contents of each of the files in the `scalyr-config` Config Map to a volume mount located in the scalyr-agent-2 configuration directory, overwriting any existing files.

**Note**: If you specify a Config Map as a volume mount in your Daemonset configuration, but you have not yet created that Config Map, then Kubernetes will not start any pods that require the Config Map until it has been created.

Once you have configured the Daemonset to use Config Map, then when you wish to update the configuration, and assuming once again you are in a directory containing an exported Scalyr Agent configuration (that is a directory with a single agent.json file and an agent.d/ directory) you can replace the contents of Config Map by executing:

```
kubectl create configmap scalyr-config $(for i in $(find .); do echo "--from-file=\"$i\""; done) -o yaml --dry-run | kubectl replace -f -
```

The changes will manifest on all nodes running the daemonset that are configured to use the Config Map, and once the configuration files have changed the Scalyr Agent will automatically detect these changes and start using the new configuration.

### Stopping the Scalyr Agent Daemonset

If you wish to stop running the Scalyr Agent Daemonset entirely then assuming you are using the default configuration and your Daemonset's name is 'scalyr-agent-2' you can run:

`kubectl delete daemonset scalyr-agent-2`

There is currently no convenient way to temporarily stop the Scalyr Agent already running on a specific node.  If you wish to avoid running the Scalyr Agent on a specific node in your cluster, then see the section on [Running the Daemonset on only some nodes](#running-only-on-some-nodes).

### Checking the status of a node running the scalyr-agent

To check the status of a currently running Scalyr Agent container, first use kubectl to find the name of the pod you are interested in, e.g.:

`kubectl get pods`

And once you have the name of the pod that is running the Scalyr Agent use the following command:

`kubectl exec scalyr-pod-name -- scalyr-docker-agent scalyr-agent-2 status`

or

`kubectl exec scalyr-pod-name -- scalyr-docker-agent scalyr-agent-2 status -v`

to get more verbose output.

### Running the Daemonset on only some nodes <a name="running-only-on-some-nodes"></a>

If you would like to run the Scalyr Agent only on certain nodes of your cluster, you can do so by adding a *nodeSelector* or a *nodeAffinity* section to your config file.  For example, if the nodes that you wanted to run the Scalyr Agent on had a label 'logging=scalyr' then you could add the following nodeSelector to your configuration file:

```
...
spec:
  nodeSelector:
    logging: scalyr
...
```

or if you wanted to use nodeAffinity:

```
...
spec:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: logging
            operator: In
            values: ["scalyr"]
...
```

You can read more about specifying node selectors and affinity [here](https://kubernetes.io/docs/concepts/configuration/assign-pod-node/).

