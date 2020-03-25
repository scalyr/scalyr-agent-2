## Kubernetes Files for Versions 2.1.1 and Up

This directory contains the manifest files for running the Scalyr Agent on your Kubernetes cluster.
Specifically, it defines the service account and DaemonSet required to run the Scalyr Agent in the
scalyr namespace. You must create a secret key and configmap before creating the service account
and DaemonSet (see instructions below).

Prior to the Scalyr Agent 2.1 release, the Scalyr Agent K8s instructions created objects in the default
namespace. If you used these instructions prior to Scalyr Agent 2.1, you must either use the manifest
files in the [default-namespace](./default-namespace) directory or perform the upgrade instructions
documented [here](https://app.scalyr.com/help/install-agent-kubernetes)

Detailed instructions for installing and upgrading the Scalyr Agent in Kubernetes can be found [here](https://app.scalyr.com/help/install-agent-kubernetes).

The intended way to use these files is to:
1. Create a secret for your Scalyr API key like so:

    ```kubectl create secret generic scalyr-api-key --from-literal=scalyr-api-key="<write logs token>"```

2. Edit `scalyr-agent-2-configmap.yaml` to have configuration you want, then apply it.
3. Apply the `kustomization.yaml` file to create the service account and DaemonSet.

This will install the Scalyr Agent on your Kubernetes nodes.
