# Copyright 2014 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ------------------------------------------------------------------------
r"""A small collection of utilities that can be used to implement ScalyrMonitors.

Currently, this set is small and is just meant to support the current monitors.
As more experience is gained building monitors, the shared abstractions in this
package will grow.

The classes exported by this package are:
  ServerProcessor           -- Base class that can be used to implement very simple network servers, handling requests.
  LineRequestParser         -- Used with ServerProcessor to implement servers whose commands come in single lines.
  Int32RequestParser        -- Used with ServerProcessor to implement servers whose commands are sent using the Int32
                               format (which each command is prefixed with a number indicating the number of bytes to
                               follow).
  AutoFlushingRotatingFile  -- A file-like object that automatically rotates the file over a certain size.  Used instead
                               of the usual logger version for performance reasons when a formatted log message is not needed
"""

__author__ = 'Steven Czerwinski <czerwin@scalyr.com>'

from scalyr_agent.monitor_utils.server_processors import ServerProcessor
from scalyr_agent.monitor_utils.server_processors import LineRequestParser
from scalyr_agent.monitor_utils.server_processors import Int32RequestParser
from scalyr_agent.monitor_utils.auto_flushing_rotating_file import AutoFlushingRotatingFile

__all__ = ['ServerProcessor', 'LineRequestParser', 'Int32RequestParser', 'AutoFlushingRotatingFile' ]
