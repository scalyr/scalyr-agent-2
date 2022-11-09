#!/usr/bin/env python
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
# flake8: noqa: E266
###
# chkconfig: 2345 98 02
# description: Manages the Scalyr Agent 2, which provides log copying
#     and basic system metric collection.
###
### BEGIN INIT INFO
# Provides: scalyr-agent-2
# Required-Start: $network
# Required-Stop: $network
# Default-Start: 2 3 4 5
# Default-Stop: 0 1 6
# Description: Manages the Scalyr Agent 2, which provides log copying
#     and back system metric collection.
### END INIT INFO
#
# author: Steven Czerwinski <czerwin@scalyr.com>
from __future__ import unicode_literals
from __future__ import print_function
from __future__ import absolute_import

__author__ = "czerwin@scalyr.com"

import collections
import datetime
import json
import platform
import subprocess
import tempfile
import traceback
import errno
import gc
import os
import sys
import time
import re
import argparse
import ssl
from io import open

if False:
    from typing import Optional
    from typing import Dict

# Work around with a striptime race we see every now and then with docker monitor run() method.
# That race would occur very rarely, since it depends on the order threads are started and when
# strptime is first called.
# See:
# 1. https://github.com/scalyr/scalyr-agent-2/pull/700#issuecomment-761676613
# 2. https://bugs.python.org/issue7980
import _strptime  # NOQA

try:
    import psutil
except ImportError:
    psutil = None

try:
    from __scalyr__ import SCALYR_VERSION
    from __scalyr__ import scalyr_init
    from __scalyr__ import INSTALL_TYPE
    from __scalyr__ import DEV_INSTALL
except ImportError:
    from scalyr_agent.__scalyr__ import SCALYR_VERSION
    from scalyr_agent.__scalyr__ import scalyr_init
    from scalyr_agent.__scalyr__ import INSTALL_TYPE
    from scalyr_agent.__scalyr__ import DEV_INSTALL

# We must invoke this since we are an executable script.
scalyr_init()

import six

try:
    import glob
except ImportError:
    import glob2 as glob  # type: ignore

import scalyr_agent.scalyr_logging as scalyr_logging
import scalyr_agent.util as scalyr_util
import scalyr_agent.remote_shell as remote_shell

# We have to be careful to set this logger class very early in processing, even before other
# imports to ensure that any loggers created are AgentLoggers.
from scalyr_agent.monitors_manager import MonitorsManager
from scalyr_agent.scalyr_monitor import UnsupportedSystem

# Set up the main logger.  We set it up initially to log to standard out,
# but once we run fork off the daemon, we will use a rotating log file.
log = scalyr_logging.getLogger("scalyr_agent")

scalyr_logging.set_log_destination(use_stdout=True)


from optparse import OptionParser

from scalyr_agent.profiler import ScalyrProfiler
from scalyr_agent.scalyr_client import ScalyrClientSession
from scalyr_agent.scalyr_client import create_client, verify_server_certificate
from scalyr_agent.copying_manager import CopyingManager
from scalyr_agent.monitors_manager import set_monitors_manager
from scalyr_agent.configuration import Configuration
from scalyr_agent.util import RunState, ScriptEscalator
from scalyr_agent.util import warn_on_old_or_unsupported_python_version
from scalyr_agent.agent_status import AgentStatus
from scalyr_agent.agent_status import ConfigStatus
from scalyr_agent.agent_status import OverallStats
from scalyr_agent.agent_status import GCStatus
from scalyr_agent.agent_status import report_status
from scalyr_agent.platform_controller import (
    PlatformController,
    AgentAlreadyRunning,
    CannotExecuteAsUser,
)
from scalyr_agent.platform_controller import AgentNotRunning
from scalyr_agent.build_info import get_build_revision
from scalyr_agent.metrics.base import clear_internal_cache

from scalyr_agent import config_main
from scalyr_agent import compat
import scalyr_agent.monitors_manager


STATUS_FILE = "last_status"
STATUS_FORMAT_FILE = "status_format"

VALID_STATUS_FORMATS = ["text", "json"]

AGENT_LOG_FILENAME = "agent.log"

AGENT_NOT_RUNNING_MESSAGE = "The agent does not appear to be running."

# Message which is logged when locale used for the scalyr agent process is not UTF-8
NON_UTF8_LOCALE_WARNING_LINUX_MESSAGE = """
Detected a non UTF-8 locale (%s) being used. You are strongly encouraged to set the locale /
coding for the agent process to UTF-8. Otherwise things won't work when trying to monitor files
with non-ascii content or non-ascii characters in the log file names. On Linux you can do that by
setting LANG and LC_ALL environment variable: e.g. export LC_ALL=en_US.UTF-8.
""".strip().replace(
    "\n", " "
)

NON_UTF8_LOCALE_WARNING_WINDOWS_MESSAGE = """
Detected a non UTF-8 locale (%s) being used. You are strongly encouraged to set the locale /
coding for the agent process to UTF-8. Otherwise things won't work when trying to monitor files
with non-ascii content or non-ascii characters in the log file names. On Windows you can do that by
setting setting PYTHONUTF8=1 environment variable.
""".strip().replace(
    "\n", " "
)

# Work around for a potential race which may happen when threads try to resolve a unicode hostname
# or similar
# See:
# - https://bugs.python.org/issue29288
# - https://github.com/aws/aws-cli/pull/4383/files#diff-45cb40c448cb3c90162a08a8d5c86559afb843a7678339500c3fb15933b5dcceR55
try:
    "".encode("idna")
except Exception as e:
    print("Failed to force idna encoding: %s" % (str(e)))


def _update_disabled_until(config_value, current_time):
    if config_value is not None:
        return config_value + current_time
    else:
        return current_time


def _check_disabled(current_time, other_time, message):
    result = current_time < other_time
    if result:
        log.log(
            scalyr_logging.DEBUG_LEVEL_0,
            "%s disabled for %d more seconds" % (message, other_time - current_time),
        )
    return result


class ScalyrAgent(object):
    """Encapsulates the entire Scalyr Agent 2 application."""

    def __init__(self, platform_controller):
        """Initialize the object.

        @param platform_controller:  The controller for this platform.
        @type platform_controller: PlatformController
        """
        # NOTE:  This abstraction is not thread safe, but it does not need to be.  Even the calls to
        # create the status file are always issued on the main thread since that's how signals are handled.

        # The current config being used to run the agent.  This may not be the latest
        # version of the config, if that latest version had parsing errors.
        self.__config = None
        # The platform-specific controller that does things like fork daemon processes, sleeps, etc.
        self.__controller = platform_controller
        # A helper for running this script as another user if need be.
        self.__escalator = None

        # The DefaultPaths object for defining the default paths for various things like the log directory based on
        # the platform.
        self.__default_paths = platform_controller.default_paths

        self.__config_file_path = None

        # An extra directory for config snippets
        self.__extra_config_dir = None

        # If the current contents of the configuration file has errors in it, then this will be set to the config
        # object produced by reading it.
        self.__current_bad_config = None
        # The last time the configuration file was checked to see if it had changed.
        self.__last_config_check_time = None
        self.__start_time = None
        # The path where the agent log file is being written.
        self.__log_file_path = None
        # The current copying manager.
        self.__copying_manager = None
        # The current monitors manager.
        self.__monitors_manager = None

        # Tracks whether or not the agent should still be running.  When a terminate signal is received,
        # the run state is set to false.  Threads are expected to notice this and finish as quickly as
        # possible.
        self.__run_state = None

        # Store references to the last value of the OverallStats instance
        self.__overall_stats = OverallStats()

        # Whether or not the unsafe debugging mode is running (meaning the RemoteShell is accepting connections
        # on the local host port and the memory profiler is turned on).  Note, this mode is very unsafe since
        # arbitrary python commands can be executed by any user on the system as the user running the agent.
        self.__unsafe_debugging_running = False
        # A reference to the remote shell debug server.
        self.__debug_server = None
        # Used below for a small cache for a slight optimization.
        self.__last_verify_config = None

        # Collection of generation time intervals for recent status reports.
        self.__agent_status_report_durations = collections.deque(maxlen=100)
        # Average duration of the status report preparation, based on collection
        # of all recent status report durations.
        self.__agent_avg_status_report_duration = None

        self.__no_fork = False
        self.__last_total_bytes_skipped = 0
        self.__last_total_bytes_copied = 0
        self.__last_total_bytes_pending = 0
        self.__last_total_rate_limited_time = 0

    @staticmethod
    def agent_run_method(controller, config_file_path, perform_config_check=False):
        """Begins executing the agent service on the current thread.

        This will not return until the service is requested to terminate.

        This method can be used as an entry point by PlatformControllers that cannot invoke the ``agent_run_method``
        argument passed in the ``start_agent_service`` method.  It immediately because execution of the service.

        @param controller: The controller to use to run the service.
        @param config_file_path: The path to the configuration file to use.
        @param perform_config_check:  If true, will check common configuration errors such as forgetting to
            provide an api token and raise an exception if they fail.

        @type controller: PlatformController
        @type config_file_path: six.text_type
        @type perform_config_check: bool

        @return: The return code when the agent exits.
        @rtype: int
        """

        class Options(object):
            pass

        my_options = Options()
        my_options.quiet = True
        my_options.verbose = False
        my_options.health_check = False
        my_options.status_format = "text"
        my_options.no_fork = True
        my_options.no_change_user = True
        my_options.no_check_remote = False
        my_options.extra_config_dir = None
        my_options.debug = False
        my_options.stats_capture_interval = 1

        if perform_config_check:
            command = "inner_run_with_checks"
        else:
            command = "inner_run"
        try:
            return ScalyrAgent(controller).main(config_file_path, command, my_options)
        except Exception:
            log.exception("Agent failed while running.  Will be shutting down.")
            raise

    def main(self, config_file_path, command, command_options):
        """Run the Scalyr Agent.

        @param config_file_path: The path to the configuration file.
        @param command: The command passed in at the commandline for the agent to execute, such as 'start', 'stop', etc.
        @param command_options: The options from the commandline.  These will include 'quiet', 'verbose', etc.

        @type config_file_path: six.text_type
        @type command: six.text_type

        @return:  The exit status code to exit with, such as 0 for success.
        @rtype: int
        """
        quiet = command_options.quiet
        verbose = command_options.verbose
        health_check = command_options.health_check
        status_format = command_options.status_format
        extra_config_dir = command_options.extra_config_dir
        self.__no_fork = command_options.no_fork
        no_check_remote = False

        self.__extra_config_dir = Configuration.get_extra_config_dir(extra_config_dir)

        # We process for the 'version' command early since we do not need the configuration file for it.
        if command == "version":
            print("The Scalyr Agent 2 version is %s" % SCALYR_VERSION)
            return 0

        # Read the configuration file.  Fail if we can't read it, unless the command is stop or status.
        if config_file_path is None:
            config_file_path = self.__default_paths.config_file_path

        self.__config_file_path = config_file_path

        no_check_remote = command_options.no_check_remote

        try:
            log_warnings = command not in ["status", "stop"]
            self.__config = self.__read_and_verify_config(
                config_file_path, log_warnings=log_warnings
            )

            # NOTE: isatty won't be available on Redirector object on Windows when doing permission
            # escalation so we need to handle this scenario as well
            isatty_func = getattr(getattr(sys, "stdout", None), "isatty", None)
            if not isatty_func or (isatty_func and not isatty_func()):
                # If stdout.atty is not available or if it is and returns False, we fall back to
                # "check_remote_if_no_tty" config option
                # check if not a tty and override the no check remote variable
                no_check_remote = not self.__config.check_remote_if_no_tty
        except Exception as e:
            # We ignore a bad configuration file for 'stop' and 'status' because sometimes you do just accidentally
            # screw up the config and you want to let the rest of the system work enough to do the stop or get the
            # status.
            if command != "stop" and command != "status":
                import traceback

                raise Exception(
                    "Error reading configuration file: %s\n"
                    "Terminating agent, please fix the configuration file and restart agent.\n%s"
                    % (six.text_type(e), traceback.format_exc())
                )
            else:
                self.__config = None
                print(
                    "Could not parse configuration file at '%s'" % config_file_path,
                    file=sys.stderr,
                )

        if log_warnings:
            warn_on_old_or_unsupported_python_version()

        self.__controller.consume_config(self.__config, config_file_path)

        self.__escalator = ScriptEscalator(
            self.__controller,
            config_file_path,
            os.getcwd(),
            command_options.no_change_user,
        )

        # noinspection PyBroadException
        try:
            # Execute the command.
            if command == "start":
                return self.__start(quiet, no_check_remote)
            elif command == "inner_run_with_checks":
                self.__perform_config_checks(no_check_remote)
                return self.__run(self.__controller)
            elif command == "inner_run":
                return self.__run(self.__controller)
            elif command == "stop":
                return self.__stop(quiet)
            elif command == "status" and not (verbose or health_check):
                return self.__status()
            elif command == "status" and (verbose or health_check):
                if self.__config is not None:
                    agent_data_path = self.__config.agent_data_path
                else:
                    agent_data_path = self.__default_paths.agent_data_path
                    print(
                        "Assuming agent data path is '%s'" % agent_data_path,
                        file=sys.stderr,
                    )
                return self.__detailed_status(
                    agent_data_path,
                    command_options=command_options,
                    status_format=status_format,
                    health_check=health_check,
                )
            elif command == "restart":
                return self.__restart(quiet, no_check_remote)
            elif command == "condrestart":
                return self.__condrestart(quiet, no_check_remote)
            else:
                print('Unknown command given: "%s".' % command, file=sys.stderr)
                return 1
        except SystemExit:
            return 0
        except Exception as e:
            # We special case the inner_run_with checks since we know that exception is human-readable.
            if command == "inner_run_with_checks":
                raise e
            else:
                import traceback

                raise Exception(
                    "Caught exception when attempt to execute command %s.  Exception was %s. "
                    "Traceback:\n%s"
                    % (command, six.text_type(e), traceback.format_exc())
                )

    def __read_and_verify_config(self, config_file_path, log_warnings=True):
        """Reads the configuration and verifies it can be successfully parsed including the monitors existing and
        having valid configurations.

        @param config_file_path: The path to read the configuration from.
        @type config_file_path: six.text_type

        @param log_warnings: True if config.parse() should log any warnings which may come up during
                             parsing.
        @type log_warnings: bool

        @return: The configuration object.
        @rtype: scalyr_agent.Configuration
        """
        config = self.__make_config(config_file_path, log_warnings=log_warnings)
        self.__verify_config(config)
        return config

    def __make_config(self, config_file_path, log_warnings=True):
        """Make Configuration object. Does not read nor verify.

        You must call ``__verify_config`` to read and fully verify the configuration.

        @param config_file_path: The path to read the configuration from.
        @type config_file_path: six.text_type

        @param log_warnings: True if config.parse() should log any warnings which may come up during
                             parsing.
        @type log_warnings: bool

        @return: The configuration object.
        @rtype: scalyr_agent.Configuration
        """
        return Configuration(
            config_file_path,
            self.__default_paths,
            log,
            extra_config_dir=self.__extra_config_dir,
            log_warnings=log_warnings,
        )

    def __verify_config(
        self,
        config,
        disable_create_monitors_manager=False,
        disable_create_copying_manager=False,
        disable_cache_config=False,
    ):
        """Verifies the passed-in configuration object is valid, and that the referenced monitors exist and have
        valid configuration.

        @param config: The configuration object.
        @type config: scalyr_agent.Configuration

        @return: A boolean value indicating whether or not the configuration was fully verified
        """
        try:
            config.parse()

            if disable_create_monitors_manager:
                log.info("verify_config - creation of monitors manager disabled")
                return False

            monitors_manager = MonitorsManager(config, self.__controller)

            if disable_create_copying_manager:
                log.info("verify_config - creation of copying manager disabled")
                return False

            copying_manager = CopyingManager(config, monitors_manager.monitors)
            # To do the full verification, we have to create the managers.  However, this call does not need them,
            # but it is very likely the caller of this method will invoke ``__create_worker_thread`` next, so let's
            # save them for that call.  This helps us avoid having to read and instantiate the monitors multiple times.
            if disable_cache_config:
                log.info("verify_config - not caching verify_config results")
                self.__last_verify_config = None
                # return true here because config is verified, just not cached
                # this means the rest of the loop will continue but the config
                # will be verified again when the worker thread is created
                return True

            self.__last_verify_config = {
                "config": config,
                "monitors_manager": monitors_manager,
                "copying_manager": copying_manager,
            }
        except UnsupportedSystem as e:
            # We want to emit a better error message for this exception, so capture it here.
            raise Exception(
                "Configuration file uses a monitor that is not supported on this system Monitor '%s' "
                "cannot be used due to: %s.  If you require support for this monitor for your system, "
                "please e-mail contact@scalyr.com" % (e.monitor_name, six.text_type(e))
            )
        return True

    def __create_worker_thread(self, config):
        """Creates the worker thread that will run the copying and monitor managers for the specified configuration.

        @param config: The configuration object.
        @type config: scalyr_agent.Configuration

        @return: The worker thread object to use.  You must start it.
        @rtype: WorkerThread
        """
        # Use the cached results from __last_verify_config if available.  If not, force it to create them.
        if (
            self.__last_verify_config is None
            or self.__last_verify_config["config"] is not config
        ):
            self.__verify_config(config)

        # Apply any global config options
        if self.__last_verify_config and self.__last_verify_config.get("config", None):
            self.__last_verify_config["config"].apply_config()

        return WorkerThread(
            self.__last_verify_config["config"],
            self.__last_verify_config["copying_manager"],
            self.__last_verify_config["monitors_manager"],
        )

    def __perform_config_checks(self, no_check_remote):
        """Perform checks for common configuration errors.  Raises an exception with a human-readable message
        if any of the checks fail.

        In particular, this checks if (1) the user has actually entered an api_key, (2) the agent process can
        write to the logs directory, (3) we can send a request to the the configured scalyr server
        and (4) the api key is correct.
        """
        # Make sure the user has set an API key... a common step that can be forgotten.
        # If they haven't set it, it will have REPLACE_THIS as the value since that's what is in the template.
        if self.__config.api_key == "REPLACE_THIS" or self.__config.api_key == "":
            raise Exception(
                "Error, you have not set a valid api key in the configuration file.\n"
                'Edit the file %s and replace the value for "api_key" with a valid logs '
                "write key for your account.\n"
                "You can see your write logs keys at https://www.scalyr.com/keys"
                % self.__config.file_path
            )

        self.__verify_can_write_to_logs_and_data(self.__config)

        # Begin writing to the log once we confirm we are able to, so we can log any connection errors
        scalyr_logging.set_log_destination(
            use_disk=True,
            no_fork=self.__no_fork,
            stdout_severity=self.__config.stdout_severity,
            max_bytes=self.__config.log_rotation_max_bytes,
            backup_count=self.__config.log_rotation_backup_count,
            logs_directory=self.__config.agent_log_path,
            agent_log_file_path=AGENT_LOG_FILENAME,
        )

        # Send a test message to the server to make sure everything works.  If not, print a decent error message.
        if not no_check_remote or self.__config.use_new_ingestion:
            client = create_client(self.__config, quiet=True)
            try:
                ping_result = client.ping()
                if ping_result != "success":
                    if "badClientClockSkew" in ping_result:
                        # TODO:  The server does not yet send this error message, but it will in the future.
                        log.error(
                            "Sending request to the server failed due to bad clock skew.  The system "
                            "clock on this host is too far off from actual time. The agent will keep "
                            "trying to connect in the background."
                        )
                        print(
                            "Sending request to the server failed due to bad clock skew.  The system "
                            "clock on this host is too far off from actual time. The agent will keep "
                            "trying to connect in the background.",
                            file=sys.stderr,
                        )
                    elif "invalidApiKey" in ping_result:
                        # TODO:  The server does not yet send this error message, but it will in the future.
                        raise Exception(
                            "Sending request to the server failed due to an invalid API key.  This probably "
                            "means the 'api_key' field in configuration file  '%s' is not correct.  "
                            "Please visit https://www.scalyr.com/keys and copy a Write Logs key into the "
                            "'api_key' field in the configuration file"
                            % self.__config.file_path
                        )
                    else:
                        log.error(
                            "Failed to send request to the server.  The server address could be "
                            "wrong, there could be a network connectivity issue, or the provided "
                            "token could be incorrect. The agent will keep trying to connect in the "
                            "background. You can disable this check with --no-check-remote-server."
                        )
                        print(
                            "Failed to send request to the server.  The server address could be "
                            "wrong, there could be a network connectivity issue, or the provided "
                            "token could be incorrect. The agent will keep trying to connect in the "
                            "background. You can disable this check with --no-check-remote-server.",
                            file=sys.stderr,
                        )
            finally:
                client.close()

    def __start(self, quiet, no_check_remote):
        """Executes the start command.

        This will perform some initial checks to see if the agent can be started, such as making sure it can
        read and write to the logs and data directory, and that it can send a successful message to the
        Scalyr servers (therefore verifying the authentication token is correct.)

        After it determines that the agent is likely to be able to run, it will start the real agent.  If self.__no_fork
        is False, then a new process will be started in the background and this method will return.  Otherwise,
        this method will not return.

        @param quiet: True if output should be kept to a minimal and only record errors that occur.
        @param no_check_remote:  True if this method should not try to contact the remote Scalyr servers to
            verify connectivity.  If it does try to contact the remote servers and it cannot connect, then
            the script exits with a failure.
        @type quiet: bool
        @type no_check_remote: bool

        @return:  The exit status code for the process.
        @rtype: int
        """
        # First, see if we have to change the user that is executing this script to match the owner of the config.
        if self.__escalator.is_user_change_required():
            return self.__escalator.change_user_and_rerun_script(
                "start the scalyr agent"
            )

        # Make sure we do not try to start it up again.
        self.__fail_if_already_running()

        # noinspection PyBroadException
        try:
            self.__perform_config_checks(no_check_remote)
        except Exception as e:
            print(file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            print(
                "Terminating agent, please fix the error and restart the agent.",
                file=sys.stderr,
            )
            log.error("%s" % six.text_type(e))
            log.error("Terminating agent, please fix the error and restart the agent.")
            return 1

        if not self.__no_fork:
            # Do one last check to just cut down on the window of race conditions.
            self.__fail_if_already_running()

            if not quiet:
                if no_check_remote:
                    print("Configuration verified, starting agent in background.")
                else:
                    print(
                        "Configuration and server connection verified, starting agent in background."
                    )
            self.__controller.start_agent_service(self.__run, quiet, fork=True)
        else:
            self.__controller.start_agent_service(self.__run, quiet, fork=False)

        return 0

    def __handle_terminate(self):
        """Invoked when the process is requested to shutdown, such as by a signal"""
        if self.__run_state.is_running():
            log.info("Received signal to shutdown, attempt to shutdown cleanly.")
            self.__run_state.stop()

    def _get_system_and_agent_stats(
        self, data_directory, status_file_path
    ):  # type: (six.text_type, six.text_type) -> Optional[Dict]
        """
        Return current machine's and agent process' stats.
        :return: Dict with stats.
        """

        # Get information about agent process.
        def get_agent_process_stats():
            agent_process_stats = {}
            if psutil is None:
                return {"error": "No psutil"}

            pidfile = os.path.join(self.__config.agent_log_path, "agent.pid")

            if not os.path.exists(pidfile):
                return {"error": "No PID file."}

            try:
                with open(pidfile, "r") as fp:
                    pidfile_content = fp.read().strip()
            except OSError as e:
                return {"error": "Error during PID file read. Error: {}".format(e)}

            try:
                psutil_process = psutil.Process(pid=int(pidfile_content))
            except psutil.Error as e:
                return {"error": "Can't create psutil process. Error: {}".format(e)}

            try:
                with psutil_process.oneshot():
                    agent_process_stats["pid"] = psutil_process.pid
                    agent_process_stats["cpu_percent"] = psutil_process.cpu_percent()
                    agent_process_stats["memory_rss"] = psutil_process.memory_info().rss
            except Exception as e:
                agent_process_stats["error"] = str(e)

            return agent_process_stats

        # Get information about machine's current state.
        def get_machine_stats():
            machine_stats = {}
            try:
                machine_stats["cpu_percent"] = psutil.cpu_percent()
                machine_stats["cpu_count"] = psutil.cpu_count()
                machine_stats["getloadavg"] = psutil.getloadavg()
                machine_stats[
                    "virtual_memory_percent"
                ] = psutil.virtual_memory().percent
            except Exception as e:
                machine_stats["error"] = str(e)

            return machine_stats

        # Get list of related processes'
        def find_agent_processes():
            agent_processes = []
            try:
                ps_output = subprocess.check_output(
                    [
                        "ps",
                        "aux",
                    ]
                ).decode()
            except Exception as e:
                return {"error": "Can't get list of processes. Error: {}".format(e)}

            for line in ps_output.splitlines():
                if "scalyr-agent" in line or "python" in line or "agent_main" in line:
                    agent_processes.append(line)

            return agent_processes

        # Get status file stats and content.
        def get_status_files_info():
            result = {}
            try:
                ls_output = subprocess.check_output(
                    ["ls", "-la", data_directory]
                ).decode()
                result["data_root_file_stats"] = ls_output.splitlines()
            except Exception as e:
                result["data_root_file_stats"] = six.text_type(e)

            try:
                with open(status_file_path, "rb") as fp:
                    content = fp.read()
                result["content"] = content.decode(errors="ignore")
            except Exception as e:
                result["content"] = six.text_type(e)

            return result

        result = {}
        result.update(get_machine_stats())
        result["timestamp"] = datetime.datetime.now().microsecond * 1000
        result["agent_process"] = get_agent_process_stats()
        if not platform.system().lower().startswith("windows"):
            result["processes"] = find_agent_processes()
            result["status_file_info"] = get_status_files_info()

        return result

    def __detailed_status(
        self,
        data_directory,
        command_options,
        status_format="text",
        health_check=False,
        zero_status_file=True,
    ):
        """Execute the status -v or -H command.

        This will request the current agent to dump its detailed status to a file in the data directory, which
        this process will then read.

        @param data_directory: The path to the data directory.
        @type data_directory: str

        :param zero_status_file: True to zero the status file content so we can detect when agent writes
                             a new status file This is primary meant to be used in testing where we can
                             set it to False which means we can avoid a lot of nasty mocking if
                             open() and related functiond.

        @return:  An exit status code for the status command indicating success or failure.
        @rtype: int
        """
        # Health check ignores format but uses `json` under the hood
        if health_check:
            status_format = "json"

        # List of all debug stats that are captured during status report.
        debug_stats = []

        status_file = os.path.join(data_directory, STATUS_FILE)
        status_format_file = os.path.join(data_directory, STATUS_FORMAT_FILE)

        # Capture debug stats at the beginning.
        if command_options.debug:
            stats = self._get_system_and_agent_stats(
                data_directory=data_directory, status_file_path=status_file
            )
            debug_stats.append(stats)

        if status_format not in VALID_STATUS_FORMATS:
            print(
                "Invalid status format: %s. Valid formats are: %s"
                % (status_format, ", ".join(VALID_STATUS_FORMATS))
            )
            return 1

        # First, see if we have to change the user that is executing this script to match the owner of the config.
        if self.__escalator.is_user_change_required():
            try:
                return self.__escalator.change_user_and_rerun_script(
                    "retrieved detailed status", handle_error=False
                )
            except CannotExecuteAsUser:
                # For now, we just ignore the error and try to get the status anyway.  This might work on Linux
                # platforms depending on permissions.  This is legacy behavior.
                pass

        try:
            self.__controller.is_agent_running(fail_if_not_running=True)
        except AgentNotRunning as e:
            print(AGENT_NOT_RUNNING_MESSAGE)
            print("%s" % six.text_type(e))
            return 1

        # The status works by sending telling the running agent to dump the status into a well known file and
        # then we read it from there, echoing it to stdout.
        if not os.path.isdir(data_directory):
            print(
                'Cannot get status due to bad config.  The data path "%s" is not a directory'
                % data_directory,
                file=sys.stderr,
            )
            return 1

        # This users needs to zero out the current status file (if it exists), so they need write access to it.
        # When we do create the status file, we give everyone read/write access, so it should not be an issue.
        if os.path.isfile(status_file) and not os.access(status_file, os.W_OK):
            print(
                "Cannot get status due to insufficient permissions.  The current user does not "
                'have write access to "%s" as required.' % status_file,
                file=sys.stderr,
            )
            return 1

        # Zero out the current file so that we can detect once the agent process has updated it.
        if os.path.isfile(status_file) and zero_status_file:
            f = open(status_file, "w")
            f.truncate(0)
            f.close()

        # Write the file with the format we need to use
        with open(status_format_file, "w") as fp:
            status_format = six.text_type(status_format)
            fp.write(status_format)

        # Signal to the running process.  This should cause that process to write to the status file
        result = self.__controller.request_agent_status()
        if result is not None:
            if result == errno.ESRCH:
                print(AGENT_NOT_RUNNING_MESSAGE, file=sys.stderr)
                return 1
            elif result == errno.EPERM:
                # TODO:  We probably should just get the name of the user running the agent and output it
                # here, instead of hard coding it to root.
                print(
                    "To view agent status, you must be running as the same user as the agent. "
                    "Try running this command as root or Administrator.",
                    file=sys.stderr,
                )
                return 2

        # We wait for five seconds at most to get the status.
        deadline = time.time() + 5

        last_debug_stat_time = 0
        # Now loop until we see it show up.
        while True:
            # Capture debug stats every second while waiting.
            if command_options.debug and (
                last_debug_stat_time + command_options.stats_capture_interval
                < time.time()
            ):
                stats = self._get_system_and_agent_stats(
                    data_directory=data_directory, status_file_path=status_file
                )
                debug_stats.append(stats)
                last_debug_stat_time = time.time()

            try:
                if os.path.isfile(status_file) and os.path.getsize(status_file) > 0:
                    break
            except OSError as e:
                if e.errno == 2:
                    # File doesn't exist - it could mean isfile() returned true, but getsize()
                    # raised an exception since the file was deleted after isfile() call, but
                    # before getsize()
                    pass
                else:
                    raise e

            if time.time() > deadline:
                if self.__config is not None:
                    agent_log = os.path.join(
                        self.__config.agent_log_path, AGENT_LOG_FILENAME
                    )
                else:
                    agent_log = os.path.join(
                        self.__default_paths.agent_log_path, AGENT_LOG_FILENAME
                    )

                # Capture debug stats on timeout.
                if command_options.debug:
                    debug_stats.append(
                        self._get_system_and_agent_stats(
                            data_directory=data_directory, status_file_path=status_file
                        )
                    )

                if command_options.debug:
                    debug_stats_str = "Debug stats: {}".format(
                        json.dumps(debug_stats, sort_keys=True, indent=4)
                    )
                else:
                    debug_stats_str = ""

                print(
                    "Failed to get status within 5 seconds.  Giving up.  The agent process is "
                    "possibly stuck.  See %s for more details.\n%s"
                    % (agent_log, debug_stats_str),
                    file=sys.stderr,
                )
                return 1

            time.sleep(0.03)

        if not os.access(status_file, os.R_OK):
            print(
                "Cannot get status due to insufficient permissions.  The current user does not "
                'have read access to "%s" as required.' % status_file,
                file=sys.stderr,
            )
            return 1

        return_code = 0

        with open(status_file, "r") as fp:
            content = fp.read()

        # Health check invocation, try to parse status from the report and print and handle it here
        health_result = self.__find_health_result_in_status_data(content)

        if health_result:
            if health_result.lower() == "good":
                return_code = 0
            else:
                return_code = 2

        # Regular non-health check invocation, just print the stats, but still use the correct exit
        # code based on the health check value.
        if not health_check:
            print(content)
            return return_code

        # Health check invocation, try to parse status from the report and print and handle it here
        if health_result:
            print("Health check: %s" % health_result)
        elif not health_result:
            return_code = 3
            print("Cannot get health check result.")

        return return_code

    @staticmethod
    def __find_health_result_in_status_data(data):
        """
        Parse health result from the agent status content (either in JSON or text format).

        param data: last_status agent file content (either in JSON or text format).
        """
        # Keep in mind that user could have requested health check (json format), but concurrent
        # scalyr-agent status invocation requested text format so we handle both here to avoid
        # introducing global agent status read write lock.
        try:
            status = scalyr_util.json_decode(data.strip())

            copying_manager_status = status.get("copying_manager_status", {}) or {}
            health_check_result = copying_manager_status.get(
                "health_check_result", None
            )

            if health_check_result:
                return health_check_result
        except ValueError as e:
            # Likely not JSON, assume it's text format
            match = re.search(r"^Health check\:\s+(.*?)$", data, flags=re.MULTILINE)

            if match:
                return match.groups()[0]

        return None

    def __stop(self, quiet):
        """Stop the current agent.

        @param quiet: Whether or not only errors should be written to stdout.
        @type quiet: bool

        @return: the exit status code
        @rtype: int
        """
        # First, see if we have to change the user that is executing this script to match the owner of the config.
        if self.__escalator.is_user_change_required():
            return self.__escalator.change_user_and_rerun_script(
                "stop the scalyr agent"
            )

        try:
            self.__controller.is_agent_running(fail_if_not_running=True)
            status = self.__controller.stop_agent_service(quiet)
            return status
        except AgentNotRunning as e:
            print(
                "Failed to stop the agent because it does not appear to be running.",
                file=sys.stderr,
            )
            print("%s" % six.text_type(e), file=sys.stderr)
            return 0  # For the sake of restart, we need to return non-error code here.

    def __status(self):
        """Execute the 'status' command to indicate if the agent is running or not.

        @return: The exit status code.  It will return zero only if it is running.
        @rtype: int
        """
        if self.__controller.is_agent_running():
            print('The agent is running. For details, use "scalyr-agent-2 status -v".')
            return 0
        else:
            print(AGENT_NOT_RUNNING_MESSAGE)
            return 4

    def __condrestart(self, quiet, no_check_remote):
        """Execute the 'condrestart' command which will only restart the agent if it is already running.
        self.__no_form determines if this method should not fork a separate process to run the agent, but run it
        directly instead.  If it is False, then a daemon process will be forked and will run the agent.

        @param quiet: True if output should be kept to a minimal and only record errors that occur.
        @param no_check_remote:  True if this method should not try to contact the remote Scalyr servers to
            verify connectivity.  If it does try to contact the remote servers and it cannot connect, then
            the script exits with a failure.

        @type quiet: bool
        @type no_check_remote: bool

        @return: the exit status code
        @rtype: int
        """
        # First, see if we have to change the user that is executing this script to match the owner of the config.
        if self.__escalator.is_user_change_required():
            return self.__escalator.change_user_and_rerun_script(
                "restart the scalyr agent"
            )

        if self.__controller.is_agent_running():
            if not quiet:
                print("Agent is running, restarting now.")
            if self.__stop(quiet) != 0:
                print(
                    "Failed to stop the running agent.  Cannot restart until it is killed.",
                    file=sys.stderr,
                )
                return 1

            return self.__start(quiet, no_check_remote)
        elif not quiet:
            print("Agent is not running, not restarting.")
            return 0
        else:
            return 0

    def __restart(self, quiet, no_check_remote):
        """Execute the 'restart' which will start the agent, stopping the existing agent if it is running.
        self.__no_fork determines if this method should not fork a separate process to run the agent, but run it
        directly instead.  If it is False, then a daemon process will be forked and will run the agent.

        @param quiet: True if output should be kept to a minimal and only record errors that occur.
        @param no_check_remote:  True if this method should not try to contact the remote Scalyr servers to
            verify connectivity.  If it does try to contact the remote servers and it cannot connect, then
            the script exits with a failure.

        @type quiet: bool
        @type no_check_remote: bool

        @return: the exit status code, zero if it was successfully restarted, non-zero if it was not running or
            could not be started.
        @rtype: int
        """
        # First, see if we have to change the user that is executing this script to match the owner of the config.
        if self.__escalator.is_user_change_required():
            return self.__escalator.change_user_and_rerun_script(
                "restart the scalyr agent"
            )

        if self.__controller.is_agent_running():
            if not quiet:
                print("Agent is running, stopping it now.")
            if self.__stop(quiet) != 0:
                print(
                    "Failed to stop the running agent.  Cannot restart until it is killed",
                    file=sys.stderr,
                )
                return 1

        return self.__start(quiet, no_check_remote)

    def __print_force_https_message(self, scalyr_server, raw_scalyr_server):
        """Convenience function for printing a message stating whether the scalyr_server was forced to use https"""
        if scalyr_server != raw_scalyr_server:
            log.info(
                "Forcing https protocol for server url: %s -> %s.  You can prevent this by setting the `allow_http` global config option, but be mindful that there are security implications with doing this, including tramsitting your Scalyr api key over an insecure connection."
                % (raw_scalyr_server, scalyr_server)
            )

    def __get_log_files_initial_positions(self, only_new_files=False):
        # type: (bool) -> Optional[Dict]
        """
        According to the current configuration, determine all agent log files (including main agent.log and
        multi-process worker sessions logs), create those files (if they do not exist) and get their current positions.

        The preliminarily creation of the log files, in case of their absence, is needed because agent log messages may
        be written to the agent log file before this log file is processed by the copying manager. In this case,
        the copying manager will start sending log file from its current position, skipping everything before that and
        causing data loss.

        :param only_new_files: This option should be used when configuration is reloaded and more worker sessions were
        added. We ignore existing files and only process log files for new worker sessions.
        :return:
        """

        # all paths for all agent log files.
        log_file_paths_to_check = [self.__log_file_path]

        # we also add log files for all worker session if they are in multiprocess configuration.
        if self.__config.use_multiprocess_workers:
            for worker_session_id in self.__config.get_session_ids_from_all_workers():
                log_file_path = self.__config.get_worker_session_agent_log_path(
                    worker_session_id
                )
                log_file_paths_to_check.append(log_file_path)

        log_file_paths = []
        for log_file_path in log_file_paths_to_check:
            include_file = True
            if os.path.isfile(log_file_path):
                if only_new_files:
                    # Only new files are handled, skip this file.
                    include_file = False
            else:
                # the file does not exist, create it now so we can get its current position.
                with open(log_file_path, "w"):
                    pass

            if include_file:
                log_file_paths.append(log_file_path)

        logs_initial_positions = {}

        # get initial positions for the files. The copying manager will start copying files from those positions.
        for log_path in log_file_paths:
            log_position = self.__get_file_initial_position(log_path)
            if log_position is not None:
                logs_initial_positions[log_path] = log_position

        if logs_initial_positions:
            return logs_initial_positions
        else:
            return None

    def _check_config_change(self, logs_initial_positions):  # type: (Dict) -> Generator
        """
        Generator function which checks the config for changes and reloads it if needed.
        It runs in its own infinite loop and yields on each iteration until the agent's main loop requests
        for the next check.

        @param logs_initial_positions: A dict mapping file paths to the offset with the file to begin copying.
            That dist has to contain positions for all agent log files and has to be passed to the copying manager.
        """

        # The stats we track for the lifetime of the agent.  This variable tracks the accumulated stats since the
        # last stat reset (the stats get reset every time we read a new configuration).
        base_overall_stats = OverallStats()

        # We only emit the overall stats once ever ten minutes.  Track when we last reported it.
        last_overall_stats_report_time = self.__start_time
        # We only emit the bandwidth stats once every minute.  Track when we last reported it.
        last_bw_stats_report_time = self.__start_time
        # We only emit the copying_manager stats once every 5 minutes.  Track when we last reported it.
        last_copy_manager_stats_report_time = self.__start_time

        # The thread that runs the monitors and and the log copier.
        worker_thread = None

        try:

            scalyr_server = self.__config.scalyr_server

            # NOTE: We call this twice - once before and once after creating the client and
            # applying global config options. This way we ensure config options are also printed
            # even if the agent fails to connect.
            config_pre_global_apply = self.__config
            self.__config.print_useful_settings()

            # verify server certificates.
            verify_server_certificate(self.__config)

            def start_worker_thread(config, logs_initial_positions=None):
                wt = self.__create_worker_thread(config)
                # attach callbacks before starting monitors
                wt.monitors_manager.set_user_agent_augment_callback(
                    wt.copying_manager.augment_user_agent_for_workers_sessions
                )
                # configure currently active monitor manager instance variable
                set_monitors_manager(monitors_manager=wt.monitors_manager)
                wt.start(logs_initial_positions)
                return wt, wt.copying_manager, wt.monitors_manager

            (
                worker_thread,
                self.__copying_manager,
                self.__monitors_manager,
            ) = start_worker_thread(
                self.__config, logs_initial_positions=logs_initial_positions
            )

            # NOTE: It's important we call this after worker thread has been created since
            # some of the global configuration options are only applied after creating a worker
            # thread
            self.__config.print_useful_settings(config_pre_global_apply)

            current_time = time.time()

            disable_all_config_updates_until = _update_disabled_until(
                self.__config.disable_all_config_updates, current_time
            )
            disable_verify_config_until = _update_disabled_until(
                self.__config.disable_verify_config, current_time
            )
            disable_config_equivalence_check_until = _update_disabled_until(
                self.__config.disable_config_equivalence_check, current_time
            )
            disable_verify_can_write_to_logs_until = _update_disabled_until(
                self.__config.disable_verify_can_write_to_logs, current_time
            )
            disable_config_reload_until = _update_disabled_until(
                self.__config.disable_config_reload, current_time
            )
            disable_verify_config_create_monitors_manager_until = (
                _update_disabled_until(
                    self.__config.disable_verify_config_create_monitors_manager,
                    current_time,
                )
            )
            disable_verify_config_create_copying_manager_until = _update_disabled_until(
                self.__config.disable_verify_config_create_copying_manager,
                current_time,
            )

            gc_interval = self.__config.garbage_collect_interval
            last_gc_time = current_time

            prev_server = scalyr_server

            profiler = ScalyrProfiler(self.__config)

            while True:

                # Each iteration we return control to the agent's main loop.
                yield

                # The run state is switched to stopped and generator is
                # called for the last time to acknowledge that.
                if not self.__run_state.is_running():
                    break

                current_time = time.time()
                self.__last_config_check_time = current_time

                profiler.update(self.__config, current_time)

                if self.__config.disable_overall_stats:
                    log.log(scalyr_logging.DEBUG_LEVEL_0, "overall stats disabled")
                else:
                    # Log the overall stats once every 10 mins (by default)
                    log_stats_delta = self.__config.overall_stats_log_interval
                    if current_time > last_overall_stats_report_time + log_stats_delta:
                        self.__overall_stats = self.__calculate_overall_stats(
                            base_overall_stats,
                        )
                        self.__log_overall_stats(self.__overall_stats)
                        last_overall_stats_report_time = current_time

                if self.__config.disable_bandwidth_stats:
                    log.log(scalyr_logging.DEBUG_LEVEL_0, "bandwidth stats disabled")
                else:
                    # Log the bandwidth-related stats once every minute:
                    log_stats_delta = self.__config.bandwidth_stats_log_interval
                    if current_time > last_bw_stats_report_time + log_stats_delta:
                        self.__overall_stats = self.__calculate_overall_stats(
                            base_overall_stats
                        )

                        self.__log_bandwidth_stats(
                            self.__calculate_overall_stats(self.__overall_stats)
                        )
                        last_bw_stats_report_time = current_time

                if self.__config.disable_copy_manager_stats:
                    log.log(scalyr_logging.DEBUG_LEVEL_0, "copy manager stats disabled")
                else:
                    # Log the copy manager stats once every 5 mins (by default)
                    log_stats_delta = self.__config.copying_manager_stats_log_interval
                    if (
                        current_time
                        > last_copy_manager_stats_report_time + log_stats_delta
                    ):
                        self.__overall_stats = self.__calculate_overall_stats(
                            base_overall_stats,
                            copy_manager_warnings=True,
                        )
                        self.__log_copy_manager_stats(self.__overall_stats)
                        last_copy_manager_stats_report_time = current_time

                log.log(
                    scalyr_logging.DEBUG_LEVEL_1,
                    "Checking for any changes to config file",
                )
                new_config = None
                try:
                    if _check_disabled(
                        current_time,
                        disable_all_config_updates_until,
                        "all config updates",
                    ):
                        continue

                    new_config = self.__make_config(self.__config_file_path)
                    # TODO:  By parsing the configuration file, we are doing a lot of work just to have it thrown
                    # out in a few seconds when we discover it is equivalent to the previous one.  Maybe we should
                    # rework the equivalence so that it can work on the raw files, but this is difficult since
                    # we need to parse the main configuration file to at least get the fragment directory.  For
                    # now, we will just wait this work.  We only do it once every 30 secs anyway.

                    if _check_disabled(
                        current_time, disable_verify_config_until, "verify config"
                    ):
                        continue

                    disable_create_monitors_manager = _check_disabled(
                        current_time,
                        disable_verify_config_create_monitors_manager_until,
                        "verify config create monitors manager",
                    )
                    disable_create_copying_manager = _check_disabled(
                        current_time,
                        disable_verify_config_create_copying_manager_until,
                        "verify config create copying manager",
                    )
                    disable_cache_config = (
                        self.__config.disable_verify_config_cache_config
                    )
                    verified = self.__verify_config(
                        new_config,
                        disable_create_monitors_manager=disable_create_monitors_manager,
                        disable_create_copying_manager=disable_create_copying_manager,
                        disable_cache_config=disable_cache_config,
                    )

                    # Skip the rest of the loop if the config wasn't fully verified because
                    # later code relies on the config being fully validated
                    if not verified:
                        continue

                    if self.__config.disable_update_debug_log_level:
                        log.log(
                            scalyr_logging.DEBUG_LEVEL_0,
                            "update debug_log_level disabled",
                        )
                    else:
                        # Update the debug_level based on the new config.. we always update it.
                        self.__update_debug_log_level(new_config.debug_level)

                    # see if we need to perform a garbage collection
                    if gc_interval > 0 and current_time > (last_gc_time + gc_interval):
                        gc.collect()
                        last_gc_time = current_time

                    if self.__config.enable_gc_stats:
                        # If GC stats are enabled, enable tracking uncollectable objects
                        if gc.get_debug() == 0:
                            log.log(
                                scalyr_logging.DEBUG_LEVEL_5,
                                "Enabling GC debug mode",
                            )
                            gc.set_debug(gc.DEBUG_UNCOLLECTABLE)
                    else:
                        if gc.get_debug() != 0:
                            log.log(
                                scalyr_logging.DEBUG_LEVEL_5,
                                "Disabling GC debug mode",
                            )
                            gc.set_debug(0)

                    if _check_disabled(
                        current_time,
                        disable_config_equivalence_check_until,
                        "config equivalence check",
                    ):
                        continue

                    if self.__current_bad_config is None and new_config.equivalent(
                        self.__config, exclude_debug_level=True
                    ):
                        log.log(
                            scalyr_logging.DEBUG_LEVEL_1,
                            "Config was not different than previous",
                        )
                        continue

                    if _check_disabled(
                        current_time,
                        disable_verify_can_write_to_logs_until,
                        "verify check for writing to logs and data",
                    ):
                        continue

                    self.__verify_can_write_to_logs_and_data(new_config)

                except Exception as e:
                    if self.__current_bad_config is None:
                        log.error(
                            "Bad configuration file seen.  Ignoring, using last known good configuration file.  "
                            'Exception was "%s"',
                            six.text_type(e),
                            error_code="badConfigFile",
                        )
                    self.__current_bad_config = new_config
                    log.log(
                        scalyr_logging.DEBUG_LEVEL_1,
                        "Config could not be read or parsed",
                    )
                    continue

                if _check_disabled(
                    current_time, disable_config_reload_until, "config reload"
                ):
                    continue

                log.log(
                    scalyr_logging.DEBUG_LEVEL_1,
                    "Config was different than previous.  Reloading.",
                )
                # We are about to reset the current workers and ScalyrClientSession, so we will lose their
                # contribution to the stats, so recalculate the base.
                base_overall_stats = self.__calculate_overall_stats(base_overall_stats)
                log.info("New configuration file seen.")
                log.info("Stopping copying and metrics threads.")
                worker_thread.stop()

                worker_thread = None

                new_config.print_useful_settings(self.__config)

                self.__config = new_config
                self.__controller.consume_config(new_config, new_config.file_path)

                self.__start_or_stop_unsafe_debugging()

                # get the server and the raw server to see if we forced https
                scalyr_server = self.__config.scalyr_server
                raw_scalyr_server = self.__config.raw_scalyr_server

                # only print a message if this is the first time we have seen this scalyr_server
                # and the server field is different from the raw server field
                if scalyr_server != prev_server:
                    self.__print_force_https_message(scalyr_server, raw_scalyr_server)

                prev_server = scalyr_server

                log.info("Starting new copying and metrics threads")

                # get log files initial positions for new worker session log files if they were added in
                # a new configuration.
                logs_initial_positions = self.__get_log_files_initial_positions(
                    only_new_files=True
                )

                (
                    worker_thread,
                    self.__copying_manager,
                    self.__monitors_manager,
                ) = start_worker_thread(
                    new_config, logs_initial_positions=logs_initial_positions
                )

                self.__current_bad_config = None

                gc_interval = self.__config.garbage_collect_interval

                disable_all_config_updates_until = _update_disabled_until(
                    self.__config.disable_all_config_updates, current_time
                )
                disable_verify_config_until = _update_disabled_until(
                    self.__config.disable_verify_config, current_time
                )
                disable_config_equivalence_check_until = _update_disabled_until(
                    self.__config.disable_config_equivalence_check, current_time
                )
                disable_verify_can_write_to_logs_until = _update_disabled_until(
                    self.__config.disable_verify_can_write_to_logs, current_time
                )
                disable_config_reload_until = _update_disabled_until(
                    self.__config.disable_config_reload, current_time
                )
                disable_verify_config_create_monitors_manager_until = (
                    _update_disabled_until(
                        self.__config.disable_verify_config_create_monitors_manager,
                        current_time,
                    )
                )
                disable_verify_config_create_copying_manager_until = (
                    _update_disabled_until(
                        self.__config.disable_verify_config_create_copying_manager,
                        current_time,
                    )
                )

                # Clear metrics functions related cache
                clear_internal_cache()

            # The previous while loop is over. That means that the agent stops it work.
            # Log the stats one more time before we terminate.
            self.__log_overall_stats(self.__calculate_overall_stats(base_overall_stats))
        finally:
            if worker_thread is not None:
                worker_thread.stop()

    def __run(self, controller):
        """Runs the Scalyr Agent 2.

        This method will not return until a TERM signal is received or a fatal error occurs.

        @param controller The controller that started this agent service.
        @type controller: PlatformController

        @return: the exit status code
        @rtype: int
        """

        self.__start_time = time.time()
        controller.register_for_termination(self.__handle_terminate)

        # Register handler for when we get an interrupt signal.  That indicates we should dump the status to
        # a file because a user has run the 'detailed_status' command.
        self.__controller.register_for_status_requests(self.__report_status_to_file)

        # noinspection PyBroadException
        try:

            self.__run_state = RunState()
            self.__log_file_path = os.path.join(
                self.__config.agent_log_path, AGENT_LOG_FILENAME
            )
            scalyr_logging.set_log_destination(
                use_disk=True,
                no_fork=self.__no_fork,
                stdout_severity=self.__config.stdout_severity,
                max_bytes=self.__config.log_rotation_max_bytes,
                backup_count=self.__config.log_rotation_backup_count,
                logs_directory=self.__config.agent_log_path,
                agent_log_file_path=AGENT_LOG_FILENAME,
            )

            self.__update_debug_log_level(
                self.__config.debug_level, self.__config.debug_level_logger_names
            )

            # We record where the log files(including multiprocess worker sessions logs) currently are
            # so that we can (in the worse case) start copying them from those position.
            logs_initial_positions = self.__get_log_files_initial_positions()

            start_up_msg = scalyr_util.get_agent_start_up_message()
            log.info(start_up_msg)
            log.log(scalyr_logging.DEBUG_LEVEL_1, start_up_msg)

            # Log warn message if non UTF-8 locale is used - this would cause issues when trying
            # to monitor files with unicode characters inside the file names or inside the
            # content
            _, encoding, _ = scalyr_util.get_language_code_coding_and_locale()
            if encoding.lower() not in ["utf-8", "utf8"]:
                if sys.platform.startswith("win"):
                    log.warn(NON_UTF8_LOCALE_WARNING_WINDOWS_MESSAGE % (encoding))
                else:
                    log.warn(NON_UTF8_LOCALE_WARNING_LINUX_MESSAGE % (encoding))

            self.__controller.emit_init_log(log, self.__config.debug_init)

            self.__start_or_stop_unsafe_debugging()

            raw_scalyr_server = self.__config.raw_scalyr_server
            self.__print_force_https_message(
                self.__config.scalyr_server, raw_scalyr_server
            )

            last_config_change_check_time = (
                last_essential_monitors_check_time
            ) = time.time()

            # Create generator that has to check config for changes and, if so, reload everything which is needed
            # according to a new configuration.
            check_config_for_change_gen = self._check_config_change(
                logs_initial_positions=logs_initial_positions
            )

            # Advance generator to the beginning of the first loop iteration.
            next(check_config_for_change_gen)

            try:
                while not self.__run_state.sleep_but_awaken_if_stopped(0.1):

                    # Check config for changes when it's time.
                    if (
                        time.time()
                        >= last_config_change_check_time
                        + self.__config.config_change_check_interval
                    ):
                        next(check_config_for_change_gen)
                        last_config_change_check_time = time.time()

                    # Check for essential monitors every 5 sec.
                    if time.time() >= last_essential_monitors_check_time + 5:
                        self._fail_if_essential_monitors_are_not_running()
                        last_essential_monitors_check_time = time.time()

                # The while loop is over, meaning that the agent is about to stop.
                # Before fully exiting, we have to be sure that the config check generator has also finished and
                # performed all its cleanups. Since the generator also looks at the '__run_state' to know when
                # to finish, we just advance it once more with stopped run state.
                try:
                    next(check_config_for_change_gen)
                except StopIteration:
                    pass

            finally:
                # If there is an error from the outside of the check config generator, or the generator itself
                # hasn't been exhausted for this moment, then close it, so it can do its cleanups.
                # NOTE: the 'close' method is just ignored if generator is already exhausted.
                check_config_for_change_gen.close()

        except Exception:
            log.exception(
                "Main run method for agent failed due to exception",
                error_code="failedAgentMain",
            )
        finally:
            # NOTE: We manually call close_handlers() here instead of registering it to call it as
            # part of run state stop routine.
            # The reason for that is that run state stop callbacks are called before we get here
            # which means that some messages which are produced after that and before fully shutting
            # down are lost and not logged.
            scalyr_logging.close_handlers()

    def _fail_if_essential_monitors_are_not_running(self):
        """
        Searches for dead monitors in monitor manager's status and raises
            error if dead "essential" monitors are found.

        Essential means that the monitor has a special configuration option which tells
        agent that it can not continue operating without this monitor.
        """
        monitor_manager_status = self.__monitors_manager.generate_status()
        for monitor_status in monitor_manager_status.monitors_status:
            if monitor_status.is_alive:
                continue

            stopped_monitor = self.__monitors_manager.find_monitor_by_short_hash(
                monitor_status.monitor_short_hash
            )
            if stopped_monitor.get_stop_agent_on_failure():
                raise Exception(
                    "Monitor '{}' with short hash '{}' is not running, stopping the agent because it is configured "
                    "not to run without this monitor.".format(
                        monitor_status.monitor_name, monitor_status.monitor_short_hash
                    )
                )

    def __fail_if_already_running(self):
        """If the agent is already running, prints an appropriate error message and exits the process."""
        try:
            self.__controller.is_agent_running(fail_if_running=True)
        except AgentAlreadyRunning as e:
            print(
                "Failed to start agent because it is already running.", file=sys.stderr
            )
            print("%s" % six.text_type(e), file=sys.stderr)
            sys.exit(4)

    def __update_debug_log_level(self, debug_level, debug_level_logger_names=None):
        """Updates the debug log level of the agent.
        @param debug_level: The debug level, ranging from 0 (no debug) to 5.

        @type debug_level: int
        """
        levels = [
            scalyr_logging.DEBUG_LEVEL_0,
            scalyr_logging.DEBUG_LEVEL_1,
            scalyr_logging.DEBUG_LEVEL_2,
            scalyr_logging.DEBUG_LEVEL_3,
            scalyr_logging.DEBUG_LEVEL_4,
            scalyr_logging.DEBUG_LEVEL_5,
        ]

        scalyr_logging.set_log_level(
            level=levels[debug_level], debug_level_logger_names=debug_level_logger_names
        )

    def __create_new_client(self):
        result = None
        if self.__config.use_new_ingestion:
            from scalyr_agent.scalyr_client import NewScalyrClientSession

            result = NewScalyrClientSession(self.__config)
        return result

    def __get_file_initial_position(self, path):
        """Returns the file size for the specified file.

        @param path: The path of the file
        @type path: str

        @return: The file size
        @rtype: int
        """
        try:
            return os.path.getsize(path)
        except OSError as e:
            if e.errno == errno.EPERM:
                log.warn("Insufficient permissions to read agent logs initial position")
                return None
            elif e.errno == errno.ENOENT:
                # If file doesn't exist, just return 0 as its initial position
                return 0
            else:
                log.exception("Error trying to read agent logs initial position")
                return None

    def __verify_can_write_to_logs_and_data(self, config):
        """Checks to make sure the user account running the agent has permission to read and write files
        to the log and data directories as specified in the config.

        If any verification fails, an exception is raised.

        @param config: The configuration
        @type config: Configuration
        """

        if self.__controller.install_type == DEV_INSTALL:
            # The agent is running from source, make sure that its directories exist.
            if not os.path.exists(config.agent_log_path):
                os.makedirs(config.agent_log_path)
            if not os.path.exists(config.agent_data_path):
                os.makedirs(config.agent_data_path)

        if not os.path.isdir(config.agent_log_path):
            raise Exception(
                "The agent log directory '%s' does not exist." % config.agent_log_path
            )

        if not os.access(config.agent_log_path, os.W_OK):
            raise Exception(
                "User cannot write to agent log directory '%s'." % config.agent_log_path
            )

        if not os.path.isdir(config.agent_data_path):
            raise Exception(
                "The agent data directory '%s' does not exist." % config.agent_data_path
            )

        if not os.access(config.agent_data_path, os.W_OK):
            raise Exception(
                "User cannot write to agent data directory '%s'."
                % config.agent_data_path
            )

    def __start_or_stop_unsafe_debugging(self):
        """Starts or stops the debugging tool.

        This runs a thread that listens to a server port and connects any incoming connection to a shell
        that can be used to execute Python commands to investigate issues on the live server.

        Since opening up a socket is dangerous, we control this with a configuration option and only use it
        when really needed.
        """
        should_be_running = self.__config.use_unsafe_debugging

        if should_be_running and not self.__unsafe_debugging_running:
            self.__unsafe_debugging_running = True
            self.__debug_server = remote_shell.DebugServer()
            self.__debug_server.start()
        elif not should_be_running and self.__unsafe_debugging_running:
            if self.__debug_server is not None:
                self.__debug_server.stop()
                self.__debug_server = None
            self.__unsafe_debugging_running = False

    def __generate_status(self, warn_on_rate_limit=False):
        """Generates the server status object and returns it.

        The returned status object is used to create the detailed status page.

        @return: The status object filled in with the values from the current agent.
        @rtype: AgentStatus
        """
        # Basic agent stats first.
        result = AgentStatus()
        result.launch_time = self.__start_time
        result.user = self.__controller.get_current_user()
        result.revision = get_build_revision()
        result.version = SCALYR_VERSION
        result.server_host = self.__config.server_attributes["serverHost"]
        result.compression_type = self.__config.compression_type
        result.compression_level = self.__config.compression_level
        result.scalyr_server = self.__config.scalyr_server
        result.log_path = self.__log_file_path
        result.python_version = sys.version.replace("\n", "")

        # Describe the status of the configuration file.
        config_result = ConfigStatus()
        result.config_status = config_result

        config_result.last_check_time = self.__last_config_check_time
        if self.__current_bad_config is not None:
            config_result.path = self.__current_bad_config.file_path
            config_result.additional_paths = list(
                self.__current_bad_config.additional_file_paths
            )
            config_result.last_read_time = self.__current_bad_config.read_time
            config_result.status = "Error, using last good configuration"
            config_result.last_error = self.__current_bad_config.last_error
            config_result.last_good_read = self.__config.read_time
            config_result.last_check_time = self.__last_config_check_time
        else:
            config_result.path = self.__config.file_path
            config_result.additional_paths = list(self.__config.additional_file_paths)
            config_result.last_read_time = self.__config.read_time
            config_result.status = "Good"
            config_result.last_error = None
            config_result.last_good_read = self.__config.read_time

        # Include the copying and monitors status.
        if self.__copying_manager is not None:
            result.copying_manager_status = self.__copying_manager.generate_status(
                warn_on_rate_limit=warn_on_rate_limit
            )
        if self.__monitors_manager is not None:
            result.monitor_manager_status = self.__monitors_manager.generate_status()

        result.avg_status_report_duration = self.__agent_avg_status_report_duration

        # Include GC stats (if enabled)
        if self.__config.enable_gc_stats:
            gc_stats = GCStatus()
            gc_stats.garbage = len(gc.garbage)
            result.gc_stats = gc_stats

        return result

    def __log_overall_stats(self, overall_stats):
        """Logs the agent_status message that we periodically write to the agent log to give overall stats.

        This includes such metrics as the number of logs being copied, the total bytes copied, the number of
        running monitors, etc.

        @param overall_stats: The overall stats for the agent.
        @type overall_stats: OverallStats
        """
        stats = overall_stats
        log.info(
            'agent_status launch_time="%s" version="%s" watched_paths=%ld copying_paths=%ld total_bytes_copied=%ld '
            "total_bytes_skipped=%ld total_bytes_subsampled=%ld total_redactions=%ld total_bytes_failed=%ld "
            "total_copy_request_errors=%ld total_monitor_reported_lines=%ld running_monitors=%ld dead_monitors=%ld "
            "user_cpu_=%f system_cpu=%f ram_usage=%ld skipped_new_bytes=%ld skipped_preexisting_bytes=%ld "
            "total_bytes_pending=%ld"
            % (
                scalyr_util.format_time(stats.launch_time),
                stats.version,
                stats.num_watched_paths,
                stats.num_copying_paths,
                stats.total_bytes_copied,
                stats.total_bytes_skipped,
                stats.total_bytes_subsampled,
                stats.total_redactions,
                stats.total_bytes_failed,
                stats.total_copy_requests_errors,
                stats.total_monitor_reported_lines,
                stats.num_running_monitors,
                stats.num_dead_monitor,
                stats.user_cpu,
                stats.system_cpu,
                stats.rss_size,
                stats.skipped_new_bytes,
                stats.skipped_preexisting_bytes,
                stats.total_bytes_pending,
            )
        )

        log.debug(
            'agent_status_debug avg_status_report_duration="%s"'
            % (stats.avg_status_report_duration,)
        )

    def __log_bandwidth_stats(self, overall_stats):
        """Logs the agent_requests message that we periodically write to the agent log to give overall request
        stats.

        This includes such metrics the total bytes sent and received, failed requests, etc.

        @param overall_stats: The overall stats for the agent.
        @type overall_stats: OverallStats
        """
        stats = overall_stats
        # Ok, this is cheating, but we are going to hide some debug information in this line when it is turned on.
        if self.__config.debug_init:
            extra = " is_agent=%d" % self.__controller.is_agent()
        else:
            extra = ""

        log.info(
            "agent_requests requests_sent=%ld requests_failed=%ld bytes_sent=%ld compressed_bytes_sent=%ld bytes_received=%ld "
            "request_latency_secs=%lf connections_created=%ld%s"
            % (
                stats.total_requests_sent,
                stats.total_requests_failed,
                stats.total_request_bytes_sent,
                stats.total_compressed_request_bytes_sent,
                stats.total_response_bytes_received,
                stats.total_request_latency_secs,
                stats.total_connections_created,
                extra,
            )
        )

    def __log_copy_manager_stats(self, overall_stats):
        """Logs the copy_manager_status message that we periodically write to the agent log to give copying manager
        stats.

        This includes such metrics as the amount of times through the main loop and time spent in various sections.

        @param overall_stats: The overall stats for the agent.
        @type overall_stats: OverallStats
        """
        stats = overall_stats

        log.info(
            "copy_manager_status num_worker_sessions=%ld total_scan_iterations=%ld total_read_time=%lf total_compression_time=%lf total_waiting_time=%lf total_blocking_response_time=%lf "
            "total_request_time=%lf total_pipelined_requests=%ld avg_bytes_produced_rate=%lf avg_bytes_copied_rate=%lf"
            % (
                stats.num_worker_sessions,
                stats.total_scan_iterations,
                stats.total_read_time,
                stats.total_compression_time,
                stats.total_waiting_time,
                stats.total_blocking_response_time,
                stats.total_request_time,
                stats.total_pipelined_requests,
                stats.avg_bytes_produced_rate,
                stats.avg_bytes_copied_rate,
            )
        )

    def __calculate_overall_stats(
        self, base_overall_stats, copy_manager_warnings=False
    ):
        """Return a newly calculated overall stats for the agent.

        This will calculate the latest stats based on the running agent.  Since most stats only can be
        calculated since the last time the configuration file changed and was read, we need to separately
        track the accumulated stats that occurred before the last config change.

        @param base_overall_stats: The accummulated stats from before the last config change.
        @type base_overall_stats: OverallStats

        @return:  The combined stats
        @rtype: OverallStats
        """
        current_status = self.__generate_status(
            warn_on_rate_limit=copy_manager_warnings
        )

        delta_stats = OverallStats()

        watched_paths = 0
        copying_paths = 0

        # Accumulate all the stats from the running processors in all workers that are copying log files.
        if current_status.copying_manager_status is not None:
            delta_stats.total_copy_requests_errors = (
                current_status.copying_manager_status.total_errors
            )
            delta_stats.total_rate_limited_time = (
                current_status.copying_manager_status.total_rate_limited_time
            )
            delta_stats.total_read_time = (
                current_status.copying_manager_status.total_read_time
            )
            delta_stats.total_waiting_time = (
                current_status.copying_manager_status.total_waiting_time
            )
            delta_stats.total_blocking_response_time = (
                current_status.copying_manager_status.total_blocking_response_time
            )
            delta_stats.total_request_time = (
                current_status.copying_manager_status.total_request_time
            )
            delta_stats.total_pipelined_requests = (
                current_status.copying_manager_status.total_pipelined_requests
            )
            delta_stats.rate_limited_time_since_last_status = (
                current_status.copying_manager_status.rate_limited_time_since_last_status
            )

            delta_stats.total_scan_iterations = (
                current_status.copying_manager_status.total_scan_iterations
            )

            watched_paths = len(current_status.copying_manager_status.log_matchers)
            for matcher in current_status.copying_manager_status.log_matchers:
                copying_paths += len(matcher.log_processors_status)
                for processor_status in matcher.log_processors_status:
                    delta_stats.total_bytes_copied += (
                        processor_status.total_bytes_copied
                    )
                    delta_stats.total_bytes_pending += (
                        processor_status.total_bytes_pending
                    )
                    delta_stats.total_bytes_skipped += (
                        processor_status.total_bytes_skipped
                    )
                    delta_stats.skipped_new_bytes += processor_status.skipped_new_bytes
                    delta_stats.skipped_preexisting_bytes += (
                        processor_status.skipped_preexisting_bytes
                    )
                    delta_stats.total_bytes_subsampled += (
                        processor_status.total_bytes_dropped_by_sampling
                    )
                    delta_stats.total_bytes_failed += (
                        processor_status.total_bytes_failed
                    )
                    delta_stats.total_redactions += processor_status.total_redactions

        running_monitors = 0
        dead_monitors = 0

        if current_status.monitor_manager_status is not None:
            running_monitors = (
                current_status.monitor_manager_status.total_alive_monitors
            )
            dead_monitors = (
                len(current_status.monitor_manager_status.monitors_status)
                - running_monitors
            )
            for monitor_status in current_status.monitor_manager_status.monitors_status:
                delta_stats.total_monitor_reported_lines += (
                    monitor_status.reported_lines
                )
                delta_stats.total_monitor_errors += monitor_status.errors

        # get client session states from all workers of the copying manager and sum up all their stats.
        session_states = (
            self.__copying_manager.get_worker_session_scalyr_client_statuses()
        )
        for session_state in session_states:

            delta_stats.total_requests_sent += session_state.total_requests_sent
            delta_stats.total_requests_failed += session_state.total_requests_failed
            delta_stats.total_request_bytes_sent += (
                session_state.total_request_bytes_sent
            )
            delta_stats.total_compressed_request_bytes_sent += (
                session_state.total_compressed_request_bytes_sent
            )
            delta_stats.total_response_bytes_received += (
                session_state.total_response_bytes_received
            )
            delta_stats.total_request_latency_secs += (
                session_state.total_request_latency_secs
            )
            delta_stats.total_connections_created += (
                session_state.total_connections_created
            )
            delta_stats.total_compression_time += session_state.total_compression_time

        # Add in the latest stats to the stats before the last restart.
        result = delta_stats + base_overall_stats

        # Overwrite some of the stats that are not affected by the add operation.
        result.launch_time = current_status.launch_time
        result.version = current_status.version
        result.num_watched_paths = watched_paths
        result.num_copying_paths = copying_paths
        result.num_running_monitors = running_monitors
        result.num_dead_monitors = dead_monitors
        if current_status.copying_manager_status is not None:
            result.num_worker_sessions = (
                current_status.copying_manager_status.num_worker_sessions
            )

        (
            result.user_cpu,
            result.system_cpu,
            result.rss_size,
        ) = self.__controller.get_usage_info()

        if copy_manager_warnings:
            result.avg_bytes_copied_rate = (
                result.total_bytes_copied - self.__last_total_bytes_copied
            ) / self.__config.copying_manager_stats_log_interval

            total_bytes_produced = (
                result.total_bytes_skipped
                + result.total_bytes_copied
                + result.total_bytes_pending
            )
            last_total_bytes_produced = (
                self.__last_total_bytes_skipped
                + self.__last_total_bytes_copied
                + self.__last_total_bytes_pending
            )
            result.avg_bytes_produced_rate = (
                total_bytes_produced - last_total_bytes_produced
            ) / self.__config.copying_manager_stats_log_interval

            # NOTE: If last_total_bytes_produced is 0 and total_bytes_skip is > 0 this
            # indicates bytes were skipped for staleness reasons (skipForStaleness) aka agent was
            # offline for a while or similar so we don't log the message in this case because
            # we already have another place which logs skipForStalness.
            if (
                result.total_bytes_skipped > self.__last_total_bytes_skipped
                and last_total_bytes_produced > 0
            ):
                # NOTE: Right now we also report very small rates (e.g. 0.0001 MB/s) which can be
                # somewhat annoying and confusing. One option would be to just report the value in
                # case it's larger than some value (e.g. 0.1 MB/s)
                if self.__config.parsed_max_send_rate_enforcement:
                    log.warning(
                        "Warning, skipping copying log lines.  Only copied %.5f MB/s log bytes when %.5f MB/s "
                        "were generated over the last %.1f minutes. This may be due to "
                        "max_send_rate_enforcement. Log upload has been delayed %.1f seconds in the last "
                        "%.1f minutes  This may be desired (due to excessive "
                        "bytes from a problematic log file).  Please contact support@scalyr.com for additional "
                        "help."
                        % (
                            result.avg_bytes_copied_rate / 1000000.0,
                            result.avg_bytes_produced_rate / 1000000.0,
                            self.__config.copying_manager_stats_log_interval / 60.0,
                            result.rate_limited_time_since_last_status,
                            self.__config.copying_manager_stats_log_interval / 60.0,
                        )
                    )
                else:
                    log.warning(
                        "Warning, skipping copying log lines.  Only copied %.5f MB/s log bytes when %.5f MB/s "
                        "were generated over the last %.1f minutes.  This may be desired (due to excessive "
                        "bytes from a problematic log file).  Please contact support@scalyr.com for additional "
                        "help."
                        % (
                            result.avg_bytes_copied_rate / 1000000.0,
                            result.avg_bytes_produced_rate / 1000000.0,
                            self.__config.copying_manager_stats_log_interval / 60.0,
                        )
                    )
            self.__last_total_bytes_skipped = result.total_bytes_skipped
            self.__last_total_bytes_copied = result.total_bytes_copied
            self.__last_total_bytes_pending = result.total_bytes_pending

        return result

    def __report_status_to_file(self):
        # type: () -> str
        """
        Handles the signal sent to request this process write its current detailed status out.

        :return: File path status data has been written to.
        :rtype: ``str``
        """

        # First determine the format user request. If no file with the requested format, we assume
        # text format is used (this way it's backward compatible and works correctly on upgraded)
        status_format = "text"
        start_ts = time.time()

        status_format_file = os.path.join(
            self.__config.agent_data_path, STATUS_FORMAT_FILE
        )

        if os.path.isfile(status_format_file):
            try:
                with open(status_format_file, "r") as fp:
                    status_format = fp.read().strip()
            except OSError:
                # Non fatal race
                status_format = "text"

        if not status_format or status_format not in VALID_STATUS_FORMATS:
            status_format = "text"

        tmp_file = None
        try:
            # We do a little dance to write the status.  We write it to a temporary file first, and then
            # move it into the real location after the write has finished.  This way, the process watching
            # the file we are writing does not accidentally read it when it is only partially written.
            tmp_file_path = os.path.join(
                self.__config.agent_data_path, "last_status.tmp"
            )
            final_file_path = os.path.join(self.__config.agent_data_path, "last_status")

            if os.path.isfile(final_file_path):
                os.remove(final_file_path)
            tmp_file = open(tmp_file_path, "w")

            agent_status = self.__generate_status()

            if not status_format or status_format == "text":
                report_status(tmp_file, agent_status, time.time())
            elif status_format == "json":
                status_data = agent_status.to_dict()
                status_data["overall_stats"] = self.__overall_stats.to_dict()
                status_data[
                    "avg_status_report_duration"
                ] = agent_status.avg_status_report_duration
                tmp_file.write(scalyr_util.json_encode(status_data))

            tmp_file.close()
            tmp_file = None

            os.rename(tmp_file_path, final_file_path)

            # Calculate time that is spent for the whole status report.
            end_ts = time.time()
            self.__agent_status_report_durations.append(end_ts - start_ts)
            # Calculate average status report duration.
            if self.__agent_status_report_durations:
                self.__agent_avg_status_report_duration = round(
                    sum(self.__agent_status_report_durations)
                    / len(self.__agent_status_report_durations),
                    4,
                )

        except (OSError, IOError) as e:
            # Temporary workaround to make race conditions less likely.
            # If agent status or health check is requested multiple times or concurrently around the
            # same time, it's likely the race will occur and rename will fail because the file  was
            # already renamed by the other process.
            # This workaround is not 100%, only 100% solution is to use a global read write lock
            # and only allow single invocation of status command at the same time.
            if tmp_file is not None:
                tmp_file.close()

            if os.path.isfile(final_file_path):
                return final_file_path

            log.exception(
                "Exception caught will try to report status", error_code="failedStatus"
            )

        log.log(
            scalyr_logging.DEBUG_LEVEL_4,
            'Wrote agent status data in "%s" format to %s'
            % (status_format, final_file_path),
        )

        return final_file_path


class WorkerThread(object):
    """A thread used to run the log copier and the monitor manager."""

    def __init__(self, configuration, copying_manager, monitors):
        self.config = configuration
        self.copying_manager = copying_manager
        self.monitors_manager = monitors

    def start(self, log_initial_positions=None):

        self.copying_manager.start_manager(log_initial_positions)
        # We purposely wait for the copying manager to begin copying so that if the monitors create any new
        # files, they will be guaranteed to be copying up to the server starting at byte index zero.
        # Note, if copying never begins then the copying manager will sys exit, so this next call will never just
        # block indefinitely will the process hangs around.
        self.copying_manager.wait_for_copying_to_begin()
        self.monitors_manager.start_manager()

    def stop(self):
        log.debug("Shutting down monitors")
        self.monitors_manager.stop_manager()

        log.debug("Shutting copy monitors")
        self.copying_manager.stop_manager()


if __name__ == "__main__":
    my_controller = PlatformController.new_platform()

    commands = [
        "start",
        "stop",
        "status",
        "restart",
        "condrestart",
        "version",
        "config",
    ]

    if platform.system() == "Windows":
        # If this is Windows, then also add service option.
        # Using this option we can use windows executable as a base for the Windows Agent service.
        # It has to save us from building multiple frozen binaries, when packaging.
        commands.append("service")

    # Create a special parser that does not print anything on error.
    # This is needed to parse first positional argument and to decide which parser to use next.
    # for example scalyr-agent-config parser or windows service.
    # Also that is needed because we have to keep old behaviour of the script
    # and when theres no any arguments, to show usage for the agent_main script.
    class ErrorSilentParser(argparse.ArgumentParser):
        def error(self, message):
            pass

    # Create parser that only has to parse first positional argument - our main command.
    command_parser = ErrorSilentParser(
        add_help=False,
    )
    command_parser.add_argument("command", choices=commands)

    # Parse the main command by command parser.
    raw_args = command_parser.parse_known_args()

    # If argument parser ends with error, it does not exit automatically and just returns None.
    if raw_args:
        args, other_argv = raw_args
        if args.command == "service":
            # Windows specific command that tell to start Agent's Windows service.
            from scalyr_agent import platform_windows

            # Create fully valid command line args so the Windows service could handle it properly.
            argv = [sys.argv[0]]
            argv.extend(other_argv)
            platform_windows.parse_options(argv)
            exit(0)

        if args.command == "config":
            # Add the config option. So we can configure the agent from the same executable.
            # It has to save us from building multiple frozen binaries, when packaging.
            config_main.parse_config_options(other_argv)
            exit(0)

    # Also create parser for the agent command line.
    parser = argparse.ArgumentParser(
        usage="scalyr-agent-2 [options] ({})".format("|".join(commands)),
    )

    parser.add_argument("command", help="Agent command to run", choices=commands)

    parser.add_argument(
        "-c",
        "--config-file",
        dest="config_filename",
        help="Read configuration from FILE",
        metavar="FILE",
    )
    parser.add_argument(
        "--extra-config-dir",
        default=None,
        help="An extra directory to check for configuration files",
        metavar="PATH",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        dest="quiet",
        default=False,
        help="Only print error messages when running the start, stop, and condrestart commands",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        dest="verbose",
        default=False,
        help="For status command, prints detailed information about running agent.",
    )
    parser.add_argument(
        "-H",
        "--health_check",
        action="store_true",
        dest="health_check",
        default=False,
        help="For status command, prints health check status. Return code will be 0 for a passing check, and 2 for failing",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        dest="debug",
        default=False,
        help="Prints additional debug output. For now works only with --health-check option.",
    )

    parser.add_argument(
        "--stats-capture-interval",
        dest="stats_capture_interval",
        type=float,
        default=1,
        help="Set interval before debug stats in the agent status are gathered. Only works with --debug option.",
    )

    parser.add_argument(
        "--format",
        dest="status_format",
        default="text",
        help="Format to use (text / json) for the agent status command.",
    )

    parser.add_argument(
        "--no-fork",
        action="store_true",
        dest="no_fork",
        default=False,
        help="For the run command, does not fork the program to the background.",
    )
    parser.add_argument(
        "--no-check-remote-server",
        action="store_true",
        dest="no_check_remote",
        help="For the start command, does not perform the first check to see if the agent can "
        "communicate with the Scalyr servers.  The agent will just keep trying to contact it in "
        "the background until it is successful.  This is useful if the network is not immediately "
        "available when the agent starts.",
    )
    my_controller.add_options(parser)

    options = parser.parse_args()

    my_controller.consume_options(options)

    if options.config_filename is not None and not os.path.isabs(
        options.config_filename
    ):
        options.config_filename = os.path.abspath(options.config_filename)

    main_rc = 1
    try:
        main_rc = ScalyrAgent(my_controller).main(
            options.config_filename, options.command, options
        )
    except Exception as mainExcept:
        print(six.text_type(mainExcept), file=sys.stderr)
        sys.exit(1)

    # We do this outside of the try block above because sys.exit raises an exception itself.
    sys.exit(main_rc)
