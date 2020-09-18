from __future__ import absolute_import

import glob
import os
import re
import copy
import time
from string import Template

import six

from scalyr_agent.json_lib import JsonObject

from scalyr_agent.builtin_monitors.journald_utils import LogConfigManager

import scalyr_agent.scalyr_logging as scalyr_logging
from six.moves import range

global_log = scalyr_logging.getLogger(__name__)


class SyslogLogConfigManager(LogConfigManager):
    def __init__(
        self,
        global_config,
        formatter,
        max_log_size=20 * 1024 * 1024,
        max_log_rotations=2,
        extra_config=None,
    ):
        LogConfigManager.__init__(
            self,
            global_config,
            formatter,
            max_log_size=max_log_size,
            max_log_rotations=max_log_rotations,
            extra_config=extra_config,
        )
        self.current_log_files = []
        self.log_deleter = LogDeleter(
            extra_config.get("docker_check_for_unused_logs_mins"),
            extra_config.get("docker_delete_unused_logs_hours"),
            extra_config.get("docker_check_rotated_timestamps"),
            max_log_rotations,
            Template(extra_config.get("message_log")),
        )

    def initialize(self):
        """ Generate the config matchers for this manager from the global config
        """
        config_matchers = []
        for config in self._global_config.syslog_log_configs:
            config_matcher = self.create_config_matcher(config)
            config_matchers.append(config_matcher)
        # Add a catchall matcher at the end in case one was not configured
        config_matchers.append(self.create_config_matcher({}))

        return config_matchers

    def create_config_matcher(self, conf):
        """ Create a function that will return a log configuration when passed in data that matches that config.
        Intended to be overwritten by users of LogConfigManager to match their own use case.
        If passed an empty dictionary in `conf` this should create a catchall matcher with default configuration.

        @param conf: Logger configuration in the form of a dictionary or JsonObject, that a matcher should be created for.
        @return: Logger configuration in the form of a dictionary or JsonObject if this matcher matches the passed
        in data, None otherwise
        """
        config = copy.deepcopy(conf)
        if "syslog_app" not in config:
            config["syslog_app"] = ".*"
        if "parser" not in config:
            config["parser"] = self._extra_config.get("parser")
        if "attributes" not in config:
            config["attributes"] = JsonObject({"monitor": six.text_type("agentSyslog")})
        elif "monitor" not in config["attributes"]:
            config["attributes"]["monitor"] = six.text_type("agentSyslog")
        config["attributes"]["containerName"] = self._extra_config.get("containerName")
        config["attributes"]["containerId"] = self._extra_config.get("containerId")
        file_template = Template(self._extra_config.get("message_log"))
        regex = re.compile(config["syslog_app"])
        match_hash = six.text_type(hash(config["syslog_app"]))
        if config["syslog_app"] == ".*":
            match_hash = ""
        full_path = os.path.join(
            self._global_config.agent_log_path,
            file_template.safe_substitute({"HASH": match_hash}),
        )
        matched_config = JsonObject({"parser": "syslog", "path": full_path})
        matched_config.update(config)

        def config_matcher(unit):
            if regex.match(unit) is not None:
                return matched_config
            return None

        return config_matcher

    def get_logger(self, unit):
        result = LogConfigManager.get_logger(self, unit)
        # self.log_deleter.add_current_log(self.get_config(unit)["path"])
        return result

    def check_for_old_logs(self):
        self.log_deleter.check_for_old_logs()


class LogDeleter(object):
    """Deletes unused log files that match a log_file_template"""

    def __init__(
        self,
        check_interval_mins,
        delete_interval_hours,
        check_rotated_timestamps,
        max_log_rotations,
        log_file_template,
    ):
        self._check_interval = check_interval_mins * 60
        self._delete_interval = delete_interval_hours * 60 * 60
        self._check_rotated_timestamps = check_rotated_timestamps
        self._max_log_rotations = max_log_rotations
        self._log_glob = log_file_template.safe_substitute(HASH="*")

        self._last_check = time.time()
        self.existing_logs = []

    def add_current_log(self, path):
        self.existing_logs.append(path)

    def _get_old_logs_for_glob(
        self, current_time, glob_pattern, existing_logs, check_rotated, max_rotations
    ):

        result = []

        for matching_file in glob.glob(glob_pattern):
            try:
                added = False
                mtime = os.path.getmtime(matching_file)
                if (
                    current_time - mtime > self._delete_interval
                    and matching_file not in existing_logs
                ):
                    result.append(matching_file)
                    added = True

                for i in range(max_rotations, 0, -1):
                    rotated_file = matching_file + (".%d" % i)
                    try:
                        if not os.path.isfile(rotated_file):
                            continue

                        if check_rotated:
                            mtime = os.path.getmtime(rotated_file)
                            if current_time - mtime > self._delete_interval:
                                result.append(rotated_file)
                        else:
                            if added:
                                result.append(rotated_file)

                    except OSError as e:
                        global_log.warn(
                            "Unable to read modification time for file '%s', %s"
                            % (rotated_file, six.text_type(e)),
                            limit_once_per_x_secs=300,
                            limit_key="mtime-%s" % rotated_file,
                        )

            except OSError as e:
                global_log.warn(
                    "Unable to read modification time for file '%s', %s"
                    % (matching_file, six.text_type(e)),
                    limit_once_per_x_secs=300,
                    limit_key="mtime-%s" % matching_file,
                )
        return result

    def check_for_old_logs(self):

        old_logs = []
        current_time = time.time()
        if current_time - self._last_check > self._check_interval:

            old_logs = self._get_old_logs_for_glob(
                current_time,
                self._log_glob,
                self.existing_logs,
                self._check_rotated_timestamps,
                self._max_log_rotations,
            )
            self._last_check = current_time

        for filename in old_logs:
            try:
                os.remove(filename)
                global_log.log(
                    scalyr_logging.DEBUG_LEVEL_1, "Deleted old log file '%s'" % filename
                )
            except OSError as e:
                global_log.warn(
                    "Error deleting old log file '%s', %s"
                    % (filename, six.text_type(e)),
                    limit_once_per_x_secs=300,
                    limit_key="delete-%s" % filename,
                )

        self.existing_logs = []
