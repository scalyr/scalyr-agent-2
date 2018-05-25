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
#
# author: Imron Alston <imron@imralsoftware.com>

__author__ = 'imron@imralsoftware.com'

class LogWatcher( object ):
    """An interface class that contains methods allowing the caller
    to add/remove a set of log paths
    """

    def add_log_config( self, monitor, log_config ):
        """Add the path specified by the log_config to the list of paths being watched
        param: monitor - the monitor adding the log_config
        param: log_config - a log_config object containing at least a path
        returns: the log_config variable with updated path and default information
        """
        pass

    def remove_log_path( self, monitor_name, log_path ):
        """Remove the log_path from the list of paths being watched
        param: monitor - the monitor removing the path
        param: log_path - a string containing path of the log file to remove
        """
        pass

    def update_log_config( self, monitor_name, log_config ):
        """Update the config of any logs that match the
           path of the log_config param
        """
        pass

    def schedule_log_path_for_removal( self, monitor_name, log_path ):
        """
            Schedules a log path for removal.  The logger will only
            be removed once the number of pending bytes for that log reaches 0
        """
        pass
