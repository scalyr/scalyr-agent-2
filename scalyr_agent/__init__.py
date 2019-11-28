"""
Implements the Scalyr Agent 2 application as well as provide support for constructing Monitor Plugins.

Scalyr Agent 2 is a daemon process run on Scalyr customer's machines to collect metrics and logs and send them
to the Scalyr servers for indexing and analysis.  Which logs are sent are set via a configuration file.  Customers
may also set redaction and sampling rules to ensure only a subset of the logs are sent to Scalyr.  Additionally,
the agent will collect system metrics such as CPU usage and send to Scalyr.

Customers can also extend the agent by building their own ScalyrMonitors or utilizing ones built by others.  These
monitors collect metrics from the local system and send them to Scalyr.  The monitors can do anything from
execute a shell script and record some of the input to start up a server to accept metrics using the Graphite
protocol.

If you are using this package as a library, then it is assumed you are using it to build your own monitors.
This package generally only exports the abstractions you should require to build your own monitor.

The classes exported by this package are:
  ScalyrMonitor            -- The base class for all ScalyrMonitors which can be used to implement your own plugin.
  MonitorConfig            -- Object used to hold and retrieve configuration information about a monitor instance.
  AgentLogger              -- Scalyr's version of logging.Logger that implements some useful extensions.
  StoppableThread          -- Small extensions to Thread that provides a centralized way to stop the thread.
  RunState                 -- Small abstraction that communicates when an ongoing process should stop.
  BadMonitorConfiguration  -- Exception thrown when the configuration information is bad.
  UnsupportedSystem        -- Exception thrown by a monitor when it does not support the current system/platform.

The methods exported are:
  getLogger                -- Can be used similar to logging.getLogger to retrieve a AgentLogger instance for module.

The constants exported are:
  DEBUG_LEVEL_0 to DEBUG_LEVEL_5  -- Well known log levels that can be used to log debugging information.

The packages exported are:
  json_lib       -- A light-weight JSON library that includes some Scalyr specific extensions.
  monitor_utils  -- A collection of abstractions that can be used to implement monitors.
"""

__author__ = 'Steven Czerwinski <czerwin@scalyr.com>'

from scalyr_agent.scalyr_monitor import ScalyrMonitor
from scalyr_agent.scalyr_monitor import BadMonitorConfiguration
from scalyr_agent.scalyr_monitor import MonitorConfig
from scalyr_agent.scalyr_monitor import UnsupportedSystem
from scalyr_agent.scalyr_monitor import define_metric
from scalyr_agent.scalyr_monitor import define_config_option
from scalyr_agent.scalyr_monitor import define_log_field

from scalyr_agent.util import StoppableThread
from scalyr_agent.util import RunState

from scalyr_agent.scalyr_logging import getLogger
from scalyr_agent.scalyr_logging import AgentLogger
from scalyr_agent.scalyr_logging import DEBUG_LEVEL_0, DEBUG_LEVEL_1, DEBUG_LEVEL_2
from scalyr_agent.scalyr_logging import DEBUG_LEVEL_3, DEBUG_LEVEL_4, DEBUG_LEVEL_5
from scalyr_agent.scalyr_logging import AutoFlushingRotatingFileHandler

import json_lib
import monitor_utils

__all__ = ['ScalyrMonitor', 'MonitorConfig', 'BadMonitorConfiguration', 'UnsupportedSystem', 'getLogger', 'AgentLogger',
           'StoppableThread', 'RunState', 'DEBUG_LEVEL_0', 'DEBUG_LEVEL_1', 'DEBUG_LEVEL_2', 'DEBUG_LEVEL_3',
           'DEBUG_LEVEL_4', 'DEBUG_LEVEL_5', 'json_lib', 'monitor_utils', 'define_metric', 'define_config_option',
           'define_log_field', 'AutoFlushingRotatingFileHandler']