# Scalyr Agent Benchmarks

This directory contains various scripts which are used to continuously track
agent performance and result utilization over time (commits).

[![Screenshot from 2022-02-19 16-12-13](https://user-images.githubusercontent.com/125088/74847646-c3670400-5332-11ea-94a6-0d984aa824a0.png)](https://scalyr-agent-codespeed.herokuapp.com/)

Those scripts run various benchmarks and checks and submit those results to
[CodeSpeed instance][https://scalyr-agent-codespeed.herokuapp.com/] where this
data is tracked and compared over time.

## Directory / File Structure

* ``benchmarks/scripts/`` - contains various scripts used for running the
   benchmark and submitting data to CodeSpeed.
* ``benchmarks/scripts/requirements.txt`` - contains Python requirements for
  scripts inside that directory.
* ``benchmarks/configs/`` - contains various agent config files which are
   used by the benchmarks

## Benchmark Suites

This section describes available "Executables" and "Benchmarks".

An Executable represents a combination of a Python version and Agent
configuration which we use to run a particular benchmark.

For example - ``Python 2.7.17 - idle conf 1`` represents an idle agent process
(no logs configured to watch) which runs under Python 2.7.17.

### Agent Process Level Benchmarks

Those benchmarks are designed to spin up the whole agent process and measure
resource utilization (memory usage, CPU consumption, etc.) of that process.

We do that under different scenarios:

* Idle agent - agent which doesn't watch any logs and doesn't run any monitors.
  This means it only runs the default Linux process metrics monitor for the
  agent process and Linux system metrics monitor.
* Loaded agent - agent is configured to watch log file(s) for changes and send
  that data to API.

#### Executables

##### [Python version] - idle conf 3

Runs agent with an idle configuration with no monitored logs and default built-in monitors
enabled (Linux process metrics for the agent process and Linux system metrics).

##### [Python version] - idle conf 4

Runs agent with an idle configuration with no monitored logs and default built-in
monitors disabled (Linux process metrics for the agent process and Linux system metrics).

##### [Python version] - loaded conf 3

Runs an agent which is configured to consume existing 50 MB Apache log file from disk. That
log path is also configured to use ``accessLog`` parser.

###### [Python version] - loaded conf 4

Runs an agent which is configured to consume 22 MB file which is dynamically generated and
written to during the benchmark run.

NOTE: To avoid line generation overhead, we currently use random data from ``/dev/urandom``
which is not totally ideal, because this data doesn't represent well actual log lines (this
random data is not compresible, etc).

#### Benchmarks

You can think of a benchmark as a metric which is captured during the benchmark run. We have
two types of metrics:

* Gauges - those represent values which can change during the agent run time (think memory usage).
  We capture / sample those values multiple time during the run-time of the benchmark and at the
  end, calculate 99.9 percentile and send that value as long as min, max and std_dev to CodeSpeed.
* Counters - those represent values which monotonically increase during the agent run time (think
  total number of disk write requests).

Each benchmark can also have a "less is better" flag associated with it. This flag represents a
benchmark where smaller value is better (think duration or memory usage). On the other hand, there
are benchmarks where larger value is better (think throughput).

* ``cpu_time_system`` (counter) - System mode CPU usage in 3/100th of a second.
* ``cpu_time_user`` (counter) - User mode CPU usage in 3/100th of a second.
* ``io_read_count_requests`` (counter) - Total disk read requests.
* ``io_write_count_requests`` (counter) - Total disk write requests.
* ``io_read_count_bytes`` (counter) - Total bytes read from a disk.
* ``io_write_count_bytes`` (counter) - Total bytes written to a disk.

* ``cpu_threads`` (counter) - Number of threads spawned during the agent process run time.
* ``memory_usage_rss`` (counter) - Resident memory usage in MB.
* ``memory_usage_rss_shared`` (counter) - Shared part of the resident memory usage in MB.
* ``memory_usage_rss_private`` (counter) - Private part of the resident memory usage in MB.
* ``memory_usage_vss`` (counter) - Virtual memory usage in MB.
* ``io_open_fds`` (counter) - Number of open file descriptors.

* ``log_lines_debug`` (counter) - Number of DEBUG log lines emitted during the run in the agent
  debug log file.
* ``log_lines_info`` (counter) - Number of INFO log lines emitted during the run in the agent
  log file
* ``log_lines_warning`` (counter) - Number of WARNING log lines emitted during the run in the agent
  log file
* ``log_lines_error`` (counter) - Number of ERROR log lines emitted during the run in the agent
  log file

### Synthetic Benchmarks

Those benchmarks are designed to measure performance of various pieces of code
which are critical to the overall agent performance (json serialization and
deserialization, compression algorithms, disk reader, etc).

## Fixture Files

Agents under load utilize static log file fixtures from this repo -
https://github.com/scalyr/codespeed-agent-fixtures.
