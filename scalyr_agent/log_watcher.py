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
# author: Imron Alston <imron@scalyr.com>
from __future__ import unicode_literals

__author__ = "imron@scalyr.com"


class LogWatcher(object):
    """An interface class that contains methods allowing the caller
    to add/remove a set of log paths
    """

    def add_log_config(self, monitor_name, log_config, force_add=False):
        """Add the log_config item to the list of paths being watched
        If force_add is true and the log_config item is marked to be removed the removal will be canceled.
        Otherwise, the item will be added only if it's not monitored already.
        param: monitor_name - the name of the monitor adding the log config
        param: log_config - a log_config object containing the path to be added
        param force_add: bool, see above
        We really just want to use this with Docker monitor where there is a small windows between
        the container restart where the log file is not immediately removed.
        returns: an updated log_config object
        """
        pass

    def remove_log_config(self, monitor_name, log_config):
        """Remove the log_config item from the list of paths being watched.
        The log config is matched by monitor_name, log_path and worker_id / api_key (if present)
        param: monitor_name - the monitor removing the log config
        param: log_config - a log_config object containing the configuration to be removed
        """
        pass

    def remove_log_path(self, monitor_name, log_path):
        """Remove the log_path from the list of paths being watched
        param: monitor - the monitor removing the path
        param: log_path - a string containing path of the log file to remove
        """
        pass

    def update_log_config(self, monitor_name, log_config):
        """Update the config of any logs that match the
        path of the log_config param
        """
        pass

    def update_log_configs_on_path(self, path, monitor_name, log_configs):
        """
        Update the config of any logs that match the path and worker_id of the log_configs
        Remove the rest.
        """
        pass

    def schedule_log_path_for_removal(self, monitor_name, log_path):
        """
        Schedules a log path for removal.  The logger will only
        be removed once the number of pending bytes for that log reaches 0
        """
        pass

    def schedule_log_config_for_removal(self, monitor_name, log_config):
        """
        Schedule a log config for removal.
        The log config is matched by monitor_name, log_path and worker_id / api_key (if present)
        param: monitor_name - the monitor removing the log config
        param: log_config - a log_config object containing the configuration to be removed
        """
        pass
