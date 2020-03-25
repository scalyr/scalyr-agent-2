## Kubernetes Files for Versions Before 2.1.1

Detailed instructions for installing and upgrading the Scalyr Agent in kubernetes can be found [here](https://app.scalyr.com/help/install-agent-kubernetes).

These files are intended for users who wish to remove a Scalyr Agent installation from their Kubernetes
cluster running an Agent version earlier than 2.1.1.

Running `kubectl delete -f` on this directory will will remove everything except the secret key from
a standard deployment.
