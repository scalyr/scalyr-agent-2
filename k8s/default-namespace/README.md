## Kubernetes Files for Versions 2.1.1 and Up

This directory contains the manifest files used for installing the Scalyr Agent prior to the 2.1 Scalyr Agent release.
Prior to 2.1, the Scalyr Agent K8s instructions created all objects in the default namespace. This has since changed to
create all objects in the scalyr namespace. You should only use these manifest files if you need to continue running the
Scalyr Agent in the default namespace, possibly as a stopgap measure until you can migrate your configuration.

Detailed instructions for installing and upgrading the Scalyr Agent in Kubernetes can be found [here](https://app.scalyr.com/help/install-agent-kubernetes).

The intended way to use these files is to:
1. Create a secret for your Scalyr API key like so:

    ```kubectl create secret generic scalyr-api-key --from-literal=scalyr-api-key="<write logs token>"```

2. Edit `scalyr-agent-2-configmap.yaml` to have configuration you want, then apply it.
3. Apply the `kustomization.yaml` file to create the service account and DaemonSet.

This will install the Scalyr Agent on your Kubernetes nodes.
