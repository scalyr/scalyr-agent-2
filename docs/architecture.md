# Agent Architecture and Code Abstractions

This document describes agent architecture and some the major abstractions and threads in the
code base.

It's based on a brain dump from @czerwingithub to @Kami in the end of January 2020.

## Major Threads and Abstractions

Agent relies on 3 primary threads and related abstractions which are described below.

Threads are isolated and cross thread interaction / communication is mostly limited to
starting a thread, stopping a thread and asking thread for a status.

### 1. Agent Main Thread ([agent_main.py](https://github.com/scalyr/scalyr-agent-2/blob/master/scalyr_agent/agent_main.py))

* Serves as the program main entry point
* Starts the agent process and other threads which are needed (copy manager, monitor manager)
* Once the threads are started, it watches configuration for changes (every 30 seconds by default)
  and re-loads it + re-instantiates all the internal objects and threads if changes are found (think
  graceful reload / restart)
* Relies on the configuration abstraction in configuration.py

#### Configuration Abstraction ([configuration.py](https://github.com/scalyr/scalyr-agent-2/blob/master/scalyr_agent/configuration.py))

* The goal is to make it easy for the user to configure the agent
* That's done via JSON config files (well, there is a small extension to the JSON parser so the
  config file supports JavaScript style comments)
* Major configuration options can also be set via environment variables (that was done to better
  support modern Docker / Kubernetes environments which usually utilize environment variables for
  config option)
* It supports "standard" Linux approach of a single configuration file (
  ``/etc/scalyr-agent-2/agent.json``) with support for merging in options from "add-on"
  configuration files from ``/etc/scalyr-agent-2/agent.d/*.json``)

#### Platform / OS Abstraction

* Agent supports Linux and Windows
* Platform specific functionality is available in ``platform_*.py`` files

### 2. Copy Manager ([copy_manager.py](https://github.com/scalyr/scalyr-agent-2/blob/master/scalyr_agent/copy_manager.py))

* It's responsible for reading the log content from disk and sending it to the Scalyr API
* It's told what it should be reading / copying.
  * It get's a list of log files which it should be copying / uploading to Scalyr + the
    corresponding log file settings (what parser should be used, any redaction or sampling rules,
    arbitrary attributes associated with that log file, etc.)
* It also performs glob expansion (user can specify a glob for files to monitor, e.g.
  ``/var/log/mongodb/*.log``)
* Once every 30 seconds it checks and expands globs if new files for a particular glob are found.
  It adds those files to the files watched (glob expansion poll value can be configured via config
  option)
* It relies on a couple of other abstractions from log_processing.py which are documented below

#### LogMatcher ([log_processing.py](https://github.com/scalyr/scalyr-agent-2/blob/master/scalyr_agent/log_processing.py))

* Responsible for resolving globs. There is an instance of ``LogMatcher`` for each glob pattern (it
  takes whole configuration for that log file glob entry).
* When a new file matching a glob is found, it instantiates LogProcessor class

#### LogFileProcessor ([log_processing.py](https://github.com/scalyr/scalyr-agent-2/blob/master/scalyr_agent/log_processing.py))

* Responsible for copying one physical file content to the Scalyr API.
* Reads bytes out of the log file and inserts it into the API request.
* It also manages check points.
* Check point represents up to which point in file we have copied bytes so far. To take log
  rotation, file moving and other possible changes into account, it relies on the ``LogFileIterator``
  abstraction.

#### LogFileIterator ([log_processing.py](https://github.com/scalyr/scalyr-agent-2/blob/master/scalyr_agent/log_processing.py))

* It's responsible to watch a single file path and give an illusion that you are iterating over
  all long lines in a log file even if that log file has been rotated.
* Think of it as a logical file path.
* There are various "tricks" and heuristics needed to make that work reliably on multiple operating
  systems. Those includes:
  * Keeping the open file handle and checking when that file handle is not the same anymore as the
    one pointed to by the log file.
  * Also uses inode information from fstat on Linux
* To be able to recover from restarts, etc. it stores information on each log file "state" (aka how
  far each file has been consumed, etc.) in a check point file on disk

#### ScalyrClient ([scalyr_client.py](https://github.com/scalyr/scalyr-agent-2/blob/master/scalyr_agent/scalyr_client.py))

* This abstraction represents API session to the Scalyr API.
* Each CopyManager gets a single session which is supposed to use.
* Mostly based around a single main method - ``add_events()``

### 3. Monitors Manager ([monitors_manager.py](https://github.com/scalyr/scalyr-agent-2/blob/master/scalyr_agent/monitors_manager.py))

* Monitors are agent plugins
* Monitors represents different integrations we've done (e.g. nginx monitor which polls nginx for
  queue size, etc.)
* Those can be configured and enabled by the user.
* By default two monitors are enabled:
  * Linux system metrics monitor (system level metrics - CPU usage, memory usage, disk usage, etc.)
  * Process monitor - monitors a specific process for various metrics. By default that monitor is
    enabled for the main scalyr-agent-2 process
* A thread is spawned for each monitor and MonitorsManager manages those threads
* Monitors either discover log files or produce new files on disk
  * This way it can rely on the same abstractions which are used for sending log file content to
    Scalyr API also for sending data / metrics produced by those monitors.
* Once it writes data to disk, it's responsibility ends. After that, copy manager is responsible for
  picking up that content and sending it to Scalyr API.
* For safety reasons, there are rate limits put in place for each monitor writes. Each write
  represents data which is sent to the Scalyr API and that's data end user needs to pay for. To
  avoid bad plugins which could result in a lot of data being produced and written to disk, rate
  limits are put in place for each monitor.
