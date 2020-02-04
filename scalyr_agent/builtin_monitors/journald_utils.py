from __future__ import unicode_literals
from __future__ import absolute_import

import os
import re
import copy
import logging
from string import Template

import six

from scalyr_agent import scalyr_logging
from scalyr_agent.json_lib import JsonObject

# TODO: The plan for this LogConfigManager is to eventually have it as a base class without any of the journald specific
# code, but for now since this is the only use of it we will have it as a journald utility


class JournaldLogFormatter(scalyr_logging.BaseFormatter):
    """Formatter used for the logs produced by the journald monitor.

    In general, it formats each line as:
        time (with milliseconds)
        component (`journald_monitor()` so we don't have to have ugly hashes in the log line for extended config.)
        message (the logged message)
    """

    def __init__(self):
        scalyr_logging.BaseFormatter.__init__(
            self, "%(asctime)s [journald_monitor()] %(message)s", "metric-formatter"
        )


class LogConfigManager:
    """A manager for the logs needed by the journald monitor.

    TODO: The intent is to use this as a base for similar managers in other monitors, so we need to generalize it more
    and move it to general utils eventually

    Keeps track of loggers for all the journald log configurations defined in `journald_logs`. Creates loggers when
    calling `get_logger`, only creating the one that matches the passed in message and extra fields, and only if it has
    not already been created.
    Expects `set_log_watcher` to be called with a valid log watcher before attempting to call `get_logger`.
    Expects that `close()` will be called when it is no longer needed, usually when the monitor is shutting down.
    """

    def __init__(
        self,
        global_config,
        formatter,
        max_log_size=20 * 1024 * 1024,
        max_log_rotations=2,
    ):
        self._loggers = {}
        self._max_log_size = max_log_size
        self._max_log_rotations = max_log_rotations
        self._global_config = global_config
        self._formatter = formatter
        self.log_watcher = None

        self.__log_config_creators = self.initialize()

    def initialize(self):
        """ Generate the config matchers for this manager from the global config
        """
        config_matchers = []
        for config in self._global_config.journald_log_configs:
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
        if "journald_unit" not in config:
            config["journald_unit"] = ".*"
        file_template = Template("journald_${ID}.log")
        regex = re.compile(config["journald_unit"])
        match_hash = six.text_type(hash(config["journald_unit"]))
        if config["journald_unit"] == ".*":
            match_hash = "monitor"
        full_path = os.path.join(
            self._global_config.agent_log_path,
            file_template.safe_substitute({"ID": match_hash}),
        )
        matched_config = JsonObject({"parser": "journald", "path": full_path})
        matched_config.update(config)

        def config_matcher(unit):
            if regex.match(unit) is not None:
                return matched_config
            return None

        return config_matcher

    def get_config(self, unit):
        """ Get a log configuration that matches the passed in data based on the configured config matchers.

        @param unit: Arbitrary data that the configured config matchers will attempt to match against
        @return: Logger configuration if a config matcher matched on `unit`, None otherwise
        """
        for matcher in self.__log_config_creators:
            config = matcher(unit)
            if config is not None:
                return config
        return None

    def get_logger(self, unit):
        """ Get a logger that matches the passed in data based on the configured config matchers. This will create
        a logger if the configuration gets matched but no logger exists yet

        @param unit: Arbitrary data that the configured config matchers will attempt to match against
        @return: Logger who's configuration matched on `unit`, None if there was no match
        """
        config = self.get_config(unit)
        if config is not None and "path" in config:
            if config["path"] not in self._loggers:
                self.create_logger(config)
            return self._loggers[config["path"]]["logger"]
        return None

    def set_log_watcher(self, log_watcher):
        """Set the log_watcher so we can use it to register new log files

        @param log_watcher:
        @return:
        """
        self.log_watcher = log_watcher

    def create_logger(self, log_config):
        """ Create a logger with the given configuration.

        @param log_config: Configuration for this logger
        """
        assert self.log_watcher is not None

        logger = logging.getLogger(log_config["path"])
        log_handler = logging.handlers.RotatingFileHandler(
            filename=log_config["path"],
            maxBytes=self._max_log_size,
            backupCount=self._max_log_rotations,
        )
        log_handler.setFormatter(self._formatter)
        logger.addHandler(log_handler)
        logger.propagate = False

        self.log_watcher.add_log_config(log_config["path"], log_config)

        if log_config["path"] not in self._loggers:
            self._loggers[log_config["path"]] = {}
        self._loggers[log_config["path"]]["logger"] = logger
        self._loggers[log_config["path"]]["handler"] = log_handler
        self._loggers[log_config["path"]]["config"] = log_config

    def close(self):
        """Close all log handlers currently managed by this LogConfigManager.
        """
        for logger in self._loggers.values():
            logger["logger"].removeHandler(logger["handler"])
            logger["handler"].close()
        self._loggers = {}
