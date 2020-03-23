# Documentation

This directory holds various documentation.

* [monitors/](https://github.com/scalyr/scalyr-agent-2/tree/master/docs/monitors) - Documentation
  for monitors. Most of it is auto-generates from code comments on the monitor classes. You
  shouldn't not edit the auto-generated part manually, but run ``tox -egenerate-monitor-docs``
  command in the repo root instead.
* [architecture.md](https://github.com/scalyr/scalyr-agent-2/blob/master/docs/architecture.md) -
  Document which describes agent architecture and core code abstractions.
* [CREATING_MONITORS.md](https://github.com/scalyr/scalyr-agent-2/blob/master/docs/CREATING_MONITORS.md) -
  Instructions on how to create a monitor plugin.
