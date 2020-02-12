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
