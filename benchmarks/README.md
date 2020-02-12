# Scalyr Agent Benchmarks

This directory contains various scripts which are used to continuously track
agent performance and result utilization over time (commits).

Those scripts run various benchmarks and checks and submit those results to
[CodeSpeed instance][TBW] where this data is tracked and compared over time.

## Directory / File Structure

* ``benchmarks/scripts/`` - contains various scripts used for running the
   benchmark and submitting data to CodeSpeed.
* ``benchmarks/scripts/requirements.txt`` - contains Python requirements for
  scripts inside that directory.
* ``benchmarks/configs/`` - contains various agent config files which are
   used by the benchmarks

## Benchmark Suites

### Agent Process Level Benchmarks

Those benchmarks are designed to spin up the whole agent process and measure
resource utilization (memory usage, CPU consumption, etc.) of that process.

We do that under different scenarios:

* idle agent - agent which doesn't watch any logs and doesn't run any monitors.
  This means it only runs default linux process metrics monitor for the agent
  process.
* loaded agent - agent is configured to watch multiple log files for changes.

### Synthetic Benchmarks

Those benchmarks are designed to measure performance of various pieces of code
which are critical to the overall agent performance (json serialization and
deserialization, compression algorithms, disk reader, etc).
