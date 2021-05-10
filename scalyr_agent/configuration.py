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
#
# author: Steven Czerwinski <czerwin@scalyr.com>

from __future__ import unicode_literals
from __future__ import absolute_import

__author__ = "czerwin@scalyr.com"

if False:
    from typing import Tuple
    from typing import Dict
    from typing import List

import os
import re
import sys
import socket
import time
import logging
import copy
import json
import stat
import platform

import six
import six.moves.urllib.parse
from six.moves import range

try:
    import win32file
except ImportError:
    # Likely not running on Windows
    win32file = None

import scalyr_agent.util as scalyr_util

from scalyr_agent.json_lib import JsonConversionException, JsonMissingFieldException
from scalyr_agent.json_lib.objects import (
    JsonObject,
    JsonArray,
    ArrayOfStrings,
    SpaceAndCommaSeparatedArrayOfStrings,
)
from scalyr_agent.monitor_utils.blocking_rate_limiter import BlockingRateLimiter
from scalyr_agent.config_util import BadConfiguration, get_config_from_env

from scalyr_agent.__scalyr__ import get_install_root
from scalyr_agent.compat import os_environ_unicode
from scalyr_agent import compat

FILE_WRONG_OWNER_ERROR_MSG = """
File \"%s\" is not readable by the current user (%s).

You need to make sure that the file is owned by the same account which is used to run the agent.

Original error: %s
""".strip()

MASKED_CONFIG_ITEM_VALUE = "********** MASKED **********"

# prefix for the worker session log file name.
AGENT_WORKER_SESSION_LOG_NAME_PREFIX = "agent-worker-session-"


class Configuration(object):
    """Encapsulates the results of a single read of the configuration file.

    An instance of this object can be used to read and validate the configuration file.  It supports
    reading the main contents of the configuration, as well as configuration fragments in the 'configs.d'
    directory.  It handles merging the contents of the configuration files together and filling in any default
    values for fields not set.  You can also use the equivalent method to determine if two instances of this
    object have the same configuration content.

    You may also use environment variable substitution in any string value in the configuration file.  You just
    need to define the ``import_vars`` configuration field to be a list of variable names to import from the
    shell and then use the $VAR_NAME in any string field.  Each entry in ``import_vars`` may also be a dict with
    two entries: ``var`` for the name of the environment variable and ``default`` for the value to use if the
    the environment variable is not set or is empty.

    This also handles reporting status information about the configuration state, including what time it was
    read and what error (if any) was raised.

    Note:
    UNDOCUMENTED_CONFIG: These are undocumented config params, meaning they are not described in the public online docs
        in order to simplify the mental model.  In rare cases, a customer may need to tune these params under direct
        guidance from support.
    """

    DEFAULT_K8S_IGNORE_NAMESPACES = ["kube-system"]
    DEFAULT_K8S_INCLUDE_NAMESPACES = ["*"]

    def __init__(
        self, file_path, default_paths, logger, extra_config_dir=None, log_warnings=True
    ):
        # Captures all environment aware variables for testing purposes
        self._environment_aware_map = {}
        self.__file_path = os.path.abspath(file_path)
        # Paths for additional configuration files that were read (from the config directory).
        self.__additional_paths = []
        # The JsonObject holding the contents of the configuration file, along with any default
        # values filled in.
        self.__config = None
        # The number of seconds past epoch when the file was read.
        self.__read_time = None
        # The exception, if any, that was raised when the state was read.  This will be a BadConfiguration exception.
        self.__last_error = None
        # The log configuration objects from the configuration file.  This does not include logs required by
        # the monitors.
        self.__log_configs = []
        # Optional configuration for journald monitor logging
        self.__journald_log_configs = []
        # Optional configuration for k8s monitor logging
        self.__k8s_log_configs = []
        # The monitor configuration objects from the configuration file.  This does not include monitors that
        # are created by default by the platform.
        self.__monitor_configs = []

        self.__worker_configs = []

        # The DefaultPaths object that specifies the default paths for things like the data and log directory
        # based on platform.
        self.__default_paths = default_paths

        # FIX THESE:
        # Add documentation, verify, etc.
        self.max_retry_time = 15 * 60
        self.max_allowed_checkpoint_age = 15 * 60

        # An additional directory to look for config snippets
        self.__extra_config_directory = extra_config_dir

        # True to emit warnings on parse. In some scenarios such as when parsing config for agent
        # status command we don't want to emit / log warnings since they will interleve with the
        # status output
        self.__log_warnings = log_warnings

        self.__logger = logger

    def parse(self):
        self.__read_time = time.time()

        try:
            try:
                # First read the file.  This makes sure it exists and can be parsed.
                self.__config = scalyr_util.read_config_file_as_json(self.__file_path)

                # What implicit entries do we need to add?  metric monitor, agent.log, and then logs from all monitors.
            except Exception as e:
                # Special case - file is not readable, likely means a permission issue so return a
                # more user-friendly error
                msg = str(e).lower()
                if (
                    "file is not readable" in msg
                    or "error reading" in msg
                    or "failed while reading"
                ):
                    from scalyr_agent.platform_controller import PlatformController

                    platform_controller = PlatformController.new_platform()
                    current_user = platform_controller.get_current_user()

                    msg = FILE_WRONG_OWNER_ERROR_MSG % (
                        self.__file_path,
                        current_user,
                        six.text_type(e),
                    )
                    raise BadConfiguration(msg, None, "fileParseError")

                raise BadConfiguration(six.text_type(e), None, "fileParseError")

            # Import any requested variables from the shell and use them for substitutions.
            self.__perform_substitutions(self.__config)

            self._check_config_file_permissions_and_warn(self.__file_path)

            # get initial list of already seen config keys (we need to do this before
            # defaults have been applied)
            already_seen = {}
            for k in self.__config.keys():
                already_seen[k] = self.__file_path

            self.__verify_main_config_and_apply_defaults(
                self.__config, self.__file_path
            )
            api_key, api_config_file = self.__check_field(
                "api_key", self.__config, self.__file_path
            )
            scalyr_server, scalyr_server_config_file = self.__check_field(
                "scalyr_server", self.__config, self.__file_path
            )
            self.__verify_logs_and_monitors_configs_and_apply_defaults(
                self.__config, self.__file_path
            )

            # these variables are allowed to appear in multiple files
            allowed_multiple_keys = (
                "import_vars",
                "logs",
                "journald_logs",
                "k8s_logs",
                "monitors",
                "server_attributes",
                "workers",
            )

            # map keys to their deprecated versions to replace them later.
            allowed_multiple_keys_deprecated_synonyms = {"workers": ["api_keys"]}

            # Get any configuration snippets in the config directory
            extra_config = self.__list_files(self.config_directory)

            # Plus any configuration snippets in the additional config directory
            extra_config.extend(self.__list_files(self.extra_config_directory))

            # Now, look for any additional configuration in the config fragment directory.
            for fp in extra_config:
                self.__additional_paths.append(fp)
                content = scalyr_util.read_config_file_as_json(fp)

                # if deprecated key names are used, then replace them with their current versions.
                for k, v in list(content.items()):
                    for (
                        key,
                        key_synonyms,
                    ) in allowed_multiple_keys_deprecated_synonyms.items():
                        if k in key_synonyms:
                            # replace deprecated key.
                            content[key] = v
                            del content[k]
                            break

                for k in content.keys():
                    if k not in allowed_multiple_keys:
                        if k in already_seen:
                            self.__last_error = BadConfiguration(
                                'Configuration fragment file "%s" redefines the config key "%s", first seen in "%s". '
                                "The only config items that can be defined in multiple config files are: %s."
                                % (fp, k, already_seen[k], allowed_multiple_keys),
                                k,
                                "multipleKeys",
                            )
                            raise self.__last_error
                        else:
                            already_seen[k] = fp

                self._check_config_file_permissions_and_warn(fp)

                self.__perform_substitutions(content)
                self.__verify_main_config(content, self.__file_path)
                self.__verify_logs_and_monitors_configs_and_apply_defaults(content, fp)

                for (key, value) in six.iteritems(content):
                    if key not in allowed_multiple_keys:
                        self.__config.put(key, value)

                self.__add_elements_from_array("logs", content, self.__config)
                self.__add_elements_from_array("journald_logs", content, self.__config)
                self.__add_elements_from_array("k8s_logs", content, self.__config)
                self.__add_elements_from_array("monitors", content, self.__config)
                self.__add_elements_from_array(
                    "workers", content, self.__config, deprecated_names=["api_keys"]
                )
                self.__merge_server_attributes(fp, content, self.__config)

            self.__set_api_key(self.__config, api_key)
            if scalyr_server is not None:
                self.__config.put("scalyr_server", scalyr_server)
            self.__verify_or_set_optional_string(
                self.__config,
                "scalyr_server",
                "https://agent.scalyr.com",
                "configuration file %s" % self.__file_path,
                env_name="SCALYR_SERVER",
            )

            self.__config["raw_scalyr_server"] = self.__config["scalyr_server"]

            # force https unless otherwise instructed not to
            if not self.__config["allow_http"]:
                server = self.__config["scalyr_server"].strip()
                https_server = server

                parts = six.moves.urllib.parse.urlparse(server)

                # use index-based addressing for 2.4 compatibility
                scheme = parts[0]

                if not scheme:
                    https_server = "https://" + server
                elif scheme == "http":
                    https_server = re.sub("^http://", "https://", server)

                if https_server != server:
                    self.__config["scalyr_server"] = https_server

            # Set defaults based on `max_send_rate_enforcement` value
            if (
                not self.__config["disable_max_send_rate_enforcement_overrides"]
                and not self.__config["max_send_rate_enforcement"] == "legacy"
            ):
                self._warn_of_override_due_to_rate_enforcement(
                    "max_allowed_request_size", 1024 * 1024
                )
                self._warn_of_override_due_to_rate_enforcement(
                    "pipeline_threshold", 1.1
                )
                self._warn_of_override_due_to_rate_enforcement(
                    "min_request_spacing_interval", 1.0
                )
                self._warn_of_override_due_to_rate_enforcement(
                    "max_request_spacing_interval", 5.0
                )
                self._warn_of_override_due_to_rate_enforcement(
                    "max_log_offset_size", 5 * 1024 * 1024
                )
                self._warn_of_override_due_to_rate_enforcement(
                    "max_existing_log_offset_size", 100 * 1024 * 1024
                )

                self.__config["max_allowed_request_size"] = 5900000
                self.__config["pipeline_threshold"] = 0
                self.__config["min_request_spacing_interval"] = 0.0
                self.__config["max_request_spacing_interval"] = 5.0
                self.__config["max_log_offset_size"] = 200000000
                self.__config["max_existing_log_offset_size"] = 200000000

            # Parse `max_send_rate_enforcement`
            if (
                self.__config["max_send_rate_enforcement"] != "unlimited"
                and self.__config["max_send_rate_enforcement"] != "legacy"
            ):
                try:
                    self.__config[
                        "parsed_max_send_rate_enforcement"
                    ] = scalyr_util.parse_data_rate_string(
                        self.__config["max_send_rate_enforcement"]
                    )
                except ValueError as e:
                    raise BadConfiguration(
                        six.text_type(e), "max_send_rate_enforcement", "notDataRate"
                    )

            # Add in 'serverHost' to server_attributes if it is not set.  We must do this after merging any
            # server attributes from the config fragments.
            if "serverHost" not in self.server_attributes:
                self.__config["server_attributes"][
                    "serverHost"
                ] = self.__get_default_hostname()

            # Add in implicit entry to collect the logs generated by this agent and its worker sessions.
            agent_log = None
            worker_session_agent_logs = None
            if self.implicit_agent_log_collection:
                # set path as glob to handle log files from the multiprocess worker sessions.
                config = JsonObject(
                    path="agent.log",
                    parser="scalyrAgentLog",
                )

                # add log config for the worker session agent log files.
                worker_session_logs_config = JsonObject(
                    path="%s*.log" % AGENT_WORKER_SESSION_LOG_NAME_PREFIX,
                    # exclude debug files for the worker session debug logs.
                    # NOTE: the glob for the excluded files has to be restrictive enough,
                    # so it matches only worker session debug logs.
                    exclude=JsonArray(
                        "*%s*_debug.log" % AGENT_WORKER_SESSION_LOG_NAME_PREFIX
                    ),
                    parser="scalyrAgentLog",
                )
                self.__verify_log_entry_and_set_defaults(
                    config, description="implicit rule"
                )
                self.__verify_log_entry_and_set_defaults(
                    worker_session_logs_config, description="implicit rule"
                )

                agent_log = config
                worker_session_agent_logs = worker_session_logs_config

            self.__log_configs = list(self.__config.get_json_array("logs"))
            if agent_log is not None:
                self.__log_configs.append(agent_log)
            if worker_session_agent_logs is not None:
                self.__log_configs.append(worker_session_agent_logs)

            self.__journald_log_configs = list(
                self.__config.get_json_array("journald_logs")
            )

            self.__k8s_log_configs = list(self.__config.get_json_array("k8s_logs"))

            # add in the profile log if we have enabled profiling
            if self.enable_profiling:
                profile_config = JsonObject(
                    path=self.profile_log_name,
                    copy_from_start=True,
                    staleness_threshold_secs=20 * 60,
                    parser="scalyrAgentProfiling",
                )
                self.__verify_log_entry_and_set_defaults(
                    profile_config, description="CPU profile log config"
                )
                self.__log_configs.append(profile_config)

            self.__monitor_configs = list(self.__config.get_json_array("monitors"))

            # Perform validation for k8s_logs option
            self._check_k8s_logs_config_option_and_warn()

            # NOTE do this verifications only after all config fragments were added into configurations.
            self.__verify_workers()
            self.__verify_and_match_workers_in_logs()

            self.__worker_configs = list(self.__config.get_json_array("workers"))

        except BadConfiguration as e:
            self.__last_error = e
            raise e

    def __verify_workers(self):
        """
        Verify all worker config entries from the "workers" list in config.
        """

        workers = list(self.__config.get_json_array("workers"))

        unique_worker_ids = {}
        # Apply other defaults to all worker entries
        for i, worker_entry in enumerate(workers):
            self.__verify_workers_entry_and_set_defaults(worker_entry, entry_index=i)
            worker_id = worker_entry["id"]
            if worker_id in unique_worker_ids:
                raise BadConfiguration(
                    "There are multiple workers with the same '%s' id. Worker id's must remain unique."
                    % worker_id,
                    "workers",
                    "workerIdDuplication",
                )
            else:
                unique_worker_ids[worker_id] = worker_entry

        default_worker_entry = unique_worker_ids.get("default")

        if default_worker_entry is None:
            default_worker_entry = JsonObject(api_key=self.api_key, id="default")
            self.__verify_workers_entry_and_set_defaults(default_worker_entry)
            workers.insert(0, default_worker_entry)
            self.__config.put("workers", JsonArray(*workers))

    def __verify_and_match_workers_in_logs(self):
        """
        Check if every log file entry contains a valid reference to the worker.
        Each log file config entry has to have a field "worker_id" which refers to some entry in the "workers" list.
        If such "worker_id" field is not specified, then the id of the default worker is used.
        If "worker_id" is specified but there is no such api key, then the error is raised.
        """

        # get the set of all worker ids.
        worker_ids = set()
        for worker_config in self.__config.get_json_array("workers"):
            worker_ids.add(worker_config["id"])

        # get all lists where log files entries may be defined.
        log_config_lists = [
            self.__log_configs,
            self.__k8s_log_configs,
            self.__journald_log_configs,
        ]

        for log_config_list in log_config_lists:
            for log_file_config in log_config_list:
                worker_id = log_file_config.get("worker_id", none_if_missing=True)

                if worker_id is None:
                    # set a default worker if worker_id is not specified.
                    log_file_config["worker_id"] = "default"
                else:
                    # if log file entry has worker_id which is not defined in the 'workers' list, then throw an error.
                    if worker_id not in worker_ids:
                        valid_worker_ids = ", ".join(sorted(worker_ids))
                        raise BadConfiguration(
                            "The log entry '%s' refers to a non-existing worker with id '%s'. Valid worker ids: %s."
                            % (
                                six.text_type(log_file_config),
                                worker_id,
                                valid_worker_ids,
                            ),
                            "logs",
                            "invalidWorkerReference",
                        )

    def _check_config_file_permissions_and_warn(self, file_path):
        # type: (str) -> None
        """
        Check config file permissions and log a warning is it's readable or writable by "others".
        """
        if not self.__log_warnings:
            return None

        if not os.path.isfile(file_path) or not self.__logger:
            return None

        st_mode = os.stat(file_path).st_mode

        if bool(st_mode & stat.S_IROTH) or bool(st_mode & stat.S_IWOTH):
            file_permissions = str(oct(st_mode)[4:])

            if file_permissions.startswith("0") and len(file_permissions) == 4:
                file_permissions = file_permissions[1:]

            limit_key = "config-permissions-warn-%s" % (file_path)
            self.__logger.warn(
                "Config file %s is readable or writable by others (permissions=%s). Config "
                "files can "
                "contain secrets so you are strongly encouraged to change the config "
                "file permissions so it's not readable by others."
                % (file_path, file_permissions),
                limit_once_per_x_secs=86400,
                limit_key=limit_key,
            )

    def _check_k8s_logs_config_option_and_warn(self):
        # type: () -> None
        """
        Check if k8s_logs attribute is configured, but kubernetes monitor is not and warn.

        k8s_logs is a top level config option, but it's utilized by Kubernetes monitor which means
        it will have no affect if kubernetes monitor is not configured as well.
        """
        if (
            self.__k8s_log_configs
            and not self._is_kubernetes_monitor_configured()
            and self.__log_warnings
        ):
            self.__logger.warn(
                '"k8s_logs" config options is defined, but Kubernetes monitor is '
                "not configured / enabled. That config option applies to "
                "Kubernetes monitor so for it to have an affect, Kubernetes "
                "monitor needs to be enabled and configured",
                limit_once_per_x_secs=86400,
                limit_key="k8s_logs_k8s_monitor_not_enabled",
            )

    def _is_kubernetes_monitor_configured(self):
        # type: () -> bool
        """
        Return true if Kubernetes monitor is configured, false otherwise.
        """
        monitor_configs = self.monitor_configs or []

        for monitor_config in monitor_configs:
            if (
                monitor_config.get("module", "")
                == "scalyr_agent.builtin_monitors.kubernetes_monitor"
            ):
                return True

        return False

    def _warn_of_override_due_to_rate_enforcement(self, config_option, default):
        if self.__log_warnings and self.__config[config_option] != default:
            self.__logger.warn(
                "Configured option %s is being overridden due to max_send_rate_enforcement setting."
                % config_option,
                limit_once_per_x_secs=86400,
                limit_key="max_send_rate_enforcement_override",
            )

    def apply_config(self):
        """
        Apply global configuration object based on the configuration values.

        At this point this only applies to the JSON library which is used and maxstdio settings on
        Windows.
        """
        if not self.__config:
            # parse() hasn't been called yet. We should probably throw here
            return

        # Set json library based on the config value. If "auto" is provided this means we use
        # default behavior which is try to use ujson and if that's not available fall back to
        # stdlib json
        json_library = self.json_library
        current_json_library = scalyr_util.get_json_lib()

        if json_library != "auto" and json_library != current_json_library:
            self.__logger.debug(
                'Changing JSON library from "%s" to "%s"'
                % (current_json_library, json_library)
            )
            scalyr_util.set_json_lib(json_library)

        # Call method which applies Windows specific global config options
        self.__apply_win32_global_config_options()

    def __apply_win32_global_config_options(self):
        """
        Method which applies Windows specific global configuration options.
        """
        if not sys.platform.startswith("win"):
            # Not a Windows platformn
            return

        # Change the value for maxstdio process specific option
        if not win32file:
            # win32file module not available
            return None

        # TODO: We should probably use platform Windows module for this
        max_open_fds = self.win32_max_open_fds
        current_max_open_fds = win32file._getmaxstdio()

        if (max_open_fds and current_max_open_fds) and (
            max_open_fds != current_max_open_fds
        ):
            self.__logger.debug(
                'Changing limit for max open fds (maxstdio) from "%s" to "%s"'
                % (current_max_open_fds, max_open_fds)
            )

            try:
                win32file._setmaxstdio(max_open_fds)
            except Exception:
                self.__logger.exception("Failed to change the value of maxstdio")

    def print_useful_settings(self, other_config=None):
        """
        Prints various useful configuration settings to the agent log, so we have a record
        in the log of the settings that are currently in use.

        @param other_config: Another configuration option.  If not None, this function will
        only print configuration options that are different between the two objects.
        """
        options = [
            "verify_server_certificate",
            "ca_cert_path",
            "compression_type",
            "compression_level",
            "pipeline_threshold",
            "max_send_rate_enforcement",
            "disable_max_send_rate_enforcement_overrides",
            "min_allowed_request_size",
            "max_allowed_request_size",
            "min_request_spacing_interval",
            "max_request_spacing_interval",
            "read_page_size",
            "max_line_size",
            "internal_parse_max_line_size",
            "line_completion_wait_time",
            "max_log_offset_size",
            "max_existing_log_offset_size",
            "json_library",
            "use_multiprocess_workers",
            "default_sessions_per_worker",
            "default_worker_session_status_message_interval",
            "enable_worker_session_process_metrics_gather",
            # NOTE: It's important we use sanitzed_ version of this method which masks the API key
            "sanitized_worker_configs",
        ]

        # get options (if any) from the other configuration object
        other_options = None
        if other_config is not None:
            other_options = {}
            for option in options:
                other_options[option] = getattr(other_config, option, None)

        first = True
        for option in options:
            value = getattr(self, option, None)
            print_value = False

            # check to see if we should be printing this option which will will
            # be True if other_config is None or if the other_config had a setting
            # that was different from our current setting
            if other_config is None:
                print_value = True
            elif (
                other_options is not None
                and option in other_options
                and other_options[option] != value
            ):
                print_value = True

            # For json_library config option, we also print actual library which is being used in
            # case the value is set to "auto"
            if option == "json_library" and value == "auto":
                json_lib = scalyr_util.get_json_lib()
                value = "%s (%s)" % (value, json_lib)

            if print_value:
                # if this is the first option we are printing, output a header
                if first:
                    self.__logger.info("Configuration settings")
                    first = False

                if isinstance(value, (list, dict)):
                    # We remove u"" prefix to ensure consistent output between Python 2 and 3
                    value = six.text_type(value).replace("u'", "'")

                self.__logger.info("\t%s: %s" % (option, value))

        # Print additional useful Windows specific information on Windows
        win32_max_open_fds_previous_value = getattr(
            other_config, "win32_max_open_fds", None
        )
        win32_max_open_fds_current_value = getattr(self, "win32_max_open_fds", None)

        if (
            sys.platform.startswith("win")
            and win32file
            and (
                win32_max_open_fds_current_value != win32_max_open_fds_previous_value
                or other_config is None
            )
        ):
            try:
                win32_max_open_fds_actual_value = win32file._getmaxstdio()
            except Exception:
                win32_max_open_fds_actual_value = "unknown"

            if first:
                self.__logger.info("Configuration settings")

            self.__logger.info(
                "\twin32_max_open_fds(maxstdio): %s (%s)"
                % (win32_max_open_fds_current_value, win32_max_open_fds_actual_value)
            )

        # If debug level 5 is set also log the raw config JSON excluding the api_key
        # This makes various troubleshooting easier.
        if self.debug_level >= 5:
            try:
                raw_config = self.__get_sanitized_raw_config()
                self.__logger.info("Raw config value: %s" % (json.dumps(raw_config)))
            except Exception:
                # If for some reason we fail to serialize the config, this should not be fatal
                pass

    def __get_sanitized_raw_config(self):
        # type: () -> dict
        """
        Return raw config values as a dictionary, masking any secret values such as  "api_key".
        """
        if not self.__config:
            return {}

        values_to_mask = [
            "api_key",
        ]

        raw_config = copy.deepcopy(self.__config.to_dict())

        for key in values_to_mask:
            if key in raw_config:
                raw_config[key] = MASKED_CONFIG_ITEM_VALUE

        # Ensure we also sanitize api_key values in workers dictionaries
        if "workers" in raw_config:
            raw_config["workers"] = self.sanitized_worker_configs

        return raw_config

    def __get_default_hostname(self):
        """Returns the default hostname for this host.
        @return: The default hostname for this host.
        @rtype: str
        """
        result = six.ensure_text(socket.gethostname())
        if result is not None and self.strip_domain_from_default_server_host:
            result = result.split(".")[0]
        return result

    @staticmethod
    def get_session_ids_of_the_worker(worker_config):  # type: (Dict) -> List
        """
        Generate the list of IDs of all sessions for the specified worker.
        :param worker_config: config entry for the worker.
        :return: List of worker session IDs.
        """
        result = []
        for i in range(worker_config["sessions"]):
            # combine the id of the worker and session's position in the list to get a session id.
            worker_session_id = "%s-%s" % (worker_config["id"], i)
            result.append(worker_session_id)
        return result

    def get_session_ids_from_all_workers(self):  # type: () -> List[six.text_type]
        """
        Get session ids for all workers.
        :return: List of worker session ids.
        """
        result = []

        for worker_config in self.worker_configs:
            result.extend(self.get_session_ids_of_the_worker(worker_config))

        return result

    def get_worker_session_agent_log_path(
        self, worker_session_id
    ):  # type: (six.text_type) -> six.text_type
        """
        Generate the name of the log file path for the worker session based on its id.
        :param worker_session_id: ID of the worker session.
        :return: path for the worker session log file.
        """
        return os.path.join(
            self.agent_log_path,
            "%s%s.log" % (AGENT_WORKER_SESSION_LOG_NAME_PREFIX, worker_session_id),
        )

    def parse_log_config(
        self,
        log_config,
        default_parser=None,
        context_description="uncategorized log entry",
    ):
        """Parses a given configuration stanza for a log file and returns the complete config with all the
        default values filled in.

        This is useful for parsing a log configuration entry that was not originally included in the configuration
        but whose contents still must be verified.  For example, a log configuration entry from a monitor.

        @param log_config: The configuration entry for the log.
        @param default_parser: If the configuration entry does not have a ``parser`` entry, set this as the default.
        @param context_description: The context of where this entry came from, used when creating an error message
            for the user.

        @type log_config: dict|JsonObject
        @type default_parser: str
        @type context_description: str

        @return: The full configuration for the log.
        @rtype: JsonObject
        """
        if type(log_config) is dict:
            log_config = JsonObject(content=log_config)

        log_config = log_config.copy()

        if default_parser is not None:
            self.__verify_or_set_optional_string(
                log_config, "parser", default_parser, context_description
            )
        self.__verify_log_entry_and_set_defaults(
            log_config, description=context_description
        )

        return log_config

    def parse_monitor_config(
        self, monitor_config, context_description="uncategorized monitor entry"
    ):
        """Parses a given monitor configuration entry and returns the complete config with all default values
        filled in.

        This is useful for parsing a monitor configuration entry that was not originally included in the
        configuration but whose contents still must be verified.  For example, a default monitor supplied by the
        platform.

        @param monitor_config: The configuration entry for the monitor.
        @param context_description: The context of where this entry came from, used when creating an error message
            for the user.

        @type monitor_config: dict|JsonObject
        @type context_description: str

        @return: The full configuration for the monitor.
        @rtype: JsonObject
        """
        if type(monitor_config) is dict:
            monitor_config = JsonObject(content=monitor_config)

        monitor_config = monitor_config.copy()

        self.__verify_monitor_entry_and_set_defaults(
            monitor_config, context_description=context_description
        )

        return monitor_config

    # k8s cache options
    @property
    def k8s_ignore_namespaces(self):
        return self.__get_config().get_json_array("k8s_ignore_namespaces")

    @property
    def k8s_include_namespaces(self):
        return self.__get_config().get_json_array("k8s_include_namespaces")

    @property
    def k8s_api_url(self):
        return self.__get_config().get_string("k8s_api_url")

    @property
    def k8s_verify_api_queries(self):
        return self.__get_config().get_bool("k8s_verify_api_queries")

    @property
    def k8s_verify_kubelet_queries(self):
        return self.__get_config().get_bool("k8s_verify_kubelet_queries")

    @property
    def k8s_kubelet_ca_cert(self):
        return self.__get_config().get_string("k8s_kubelet_ca_cert")

    @property
    def k8s_cache_query_timeout_secs(self):
        return self.__get_config().get_int("k8s_cache_query_timeout_secs")

    @property
    def k8s_cache_expiry_secs(self):
        return self.__get_config().get_int("k8s_cache_expiry_secs")

    @property
    def k8s_cache_expiry_fuzz_secs(self):
        return self.__get_config().get_int("k8s_cache_expiry_fuzz_secs")

    @property
    def k8s_cache_start_fuzz_secs(self):
        return self.__get_config().get_int("k8s_cache_start_fuzz_secs")

    @property
    def k8s_cache_purge_secs(self):
        return self.__get_config().get_int("k8s_cache_purge_secs")

    @property
    def k8s_service_account_cert(self):
        return self.__get_config().get_string("k8s_service_account_cert")

    @property
    def k8s_service_account_token(self):
        return self.__get_config().get_string("k8s_service_account_token")

    @property
    def k8s_service_account_namespace(self):
        return self.__get_config().get_string("k8s_service_account_namespace")

    @property
    def k8s_log_api_responses(self):
        # UNDOCUMENTED_CONFIG
        return self.__get_config().get_bool("k8s_log_api_responses")

    @property
    def k8s_log_api_exclude_200s(self):
        # UNDOCUMENTED_CONFIG
        return self.__get_config().get_bool("k8s_log_api_exclude_200s")

    @property
    def k8s_log_api_min_response_len(self):
        # UNDOCUMENTED_CONFIG
        return self.__get_config().get_int("k8s_log_api_min_response_len")

    @property
    def k8s_log_api_min_latency(self):
        # UNDOCUMENTED_CONFIG
        return self.__get_config().get_float("k8s_log_api_min_latency")

    @property
    def k8s_log_api_ratelimit_interval(self):
        # UNDOCUMENTED_CONFIG
        return self.__get_config().get_float("k8s_log_api_ratelimit_interval")

    @property
    def k8s_controlled_warmer_max_attempts(self):
        # UNDOCUMENTED_CONFIG
        return self.__get_config().get_int("k8s_controlled_warmer_max_attempts")

    @property
    def k8s_controlled_warmer_max_query_retries(self):
        # UNDOCUMENTED_CONFIG
        return self.__get_config().get_int("k8s_controlled_warmer_max_query_retries")

    @property
    def k8s_controlled_warmer_blacklist_time(self):
        # UNDOCUMENTED_CONFIG
        return self.__get_config().get_int("k8s_controlled_warmer_blacklist_time")

    @property
    def k8s_events_disable(self):
        return self.__get_config().get_bool("k8s_events_disable")

    @property
    def k8s_ratelimit_cluster_num_agents(self):
        # UNDOCUMENTED_CONFIG
        return self.__get_config().get_int("k8s_ratelimit_cluster_num_agents")

    @property
    def k8s_ratelimit_cluster_rps_init(self):
        # UNDOCUMENTED_CONFIG
        return self.__get_config().get_float("k8s_ratelimit_cluster_rps_init")

    @property
    def k8s_ratelimit_cluster_rps_min(self):
        # UNDOCUMENTED_CONFIG
        return self.__get_config().get_float("k8s_ratelimit_cluster_rps_min")

    @property
    def k8s_ratelimit_cluster_rps_max(self):
        # UNDOCUMENTED_CONFIG
        return self.__get_config().get_float("k8s_ratelimit_cluster_rps_max")

    @property
    def k8s_ratelimit_consecutive_increase_threshold(self):
        # UNDOCUMENTED_CONFIG
        return self.__get_config().get_int(
            "k8s_ratelimit_consecutive_increase_threshold"
        )

    @property
    def k8s_ratelimit_strategy(self):
        # UNDOCUMENTED_CONFIG
        return self.__get_config().get_string("k8s_ratelimit_strategy")

    @property
    def k8s_ratelimit_increase_factor(self):
        # UNDOCUMENTED_CONFIG
        return self.__get_config().get_float("k8s_ratelimit_increase_factor")

    @property
    def k8s_ratelimit_backoff_factor(self):
        # UNDOCUMENTED_CONFIG
        return self.__get_config().get_float("k8s_ratelimit_backoff_factor")

    @property
    def k8s_ratelimit_max_concurrency(self):
        # UNDOCUMENTED_CONFIG
        return self.__get_config().get_int("k8s_ratelimit_max_concurrency")

    @property
    def enforce_monotonic_timestamps(self):
        # UNDOCUMENTED_CONFIG
        return self.__get_config().get_bool("enforce_monotonic_timestamps")

    @property
    def include_raw_timestamp_field(self):
        """If True, adds an attribute called `raw_timestamp` to all events parsed using the
        parse_as_json or parse_as_cri features.  This field will be set to the timestamp included in the JSON or
        CRI line.  When parsing Docker or K8s logs, this represents the timestamp of the log
        message as recorded by those systems."""
        return self.__get_config().get_bool("include_raw_timestamp_field")

    @property
    def enable_profiling(self):
        return self.__get_config().get_bool("enable_profiling")

    @property
    def max_profile_interval_minutes(self):
        return self.__get_config().get_int("max_profile_interval_minutes")

    @property
    def profile_duration_minutes(self):
        return self.__get_config().get_int("profile_duration_minutes")

    @property
    def profile_clock(self):
        return self.__get_config().get_string("profile_clock")

    @property
    def profile_log_name(self):
        return self.__get_config().get_string("profile_log_name")

    @property
    def memory_profile_log_name(self):
        return self.__get_config().get_string("memory_profile_log_name")

    @property
    def disable_logfile_addevents_format(self):
        return self.__get_config().get_bool("disable_logfile_addevents_format")

    @property
    def json_library(self):
        return self.__get_config().get_string("json_library")

    # Debug leak flags
    @property
    def disable_send_requests(self):
        return self.__get_config().get_bool("disable_send_requests")

    # Debug leak flags
    @property
    def disable_monitor_threads(self):
        return self.__get_config().get_bool("disable_leak_monitor_threads")

    @property
    def disable_monitors_creation(self):
        return self.__get_config().get_bool("disable_leak_monitors_creation")

    @property
    def disable_new_file_matches(self):
        return self.__get_config().get_bool("disable_leak_new_file_matches")

    @property
    def disable_scan_for_new_bytes(self):
        return self.__get_config().get_bool("disable_leak_scan_for_new_bytes")

    @property
    def disable_processing_new_bytes(self):
        return self.__get_config().get_bool("disable_leak_processing_new_bytes")

    @property
    def disable_copying_thread(self):
        return self.__get_config().get_bool("disable_leak_copying_thread")

    @property
    def disable_overall_stats(self):
        return self.__get_config().get_bool("disable_leak_overall_stats")

    @property
    def disable_bandwidth_stats(self):
        return self.__get_config().get_bool("disable_leak_bandwidth_stats")

    @property
    def disable_copy_manager_stats(self):
        return self.__get_config().get_bool("disable_copy_manager_stats")

    @property
    def disable_update_debug_log_level(self):
        return self.__get_config().get_bool("disable_leak_update_debug_log_level")

    @property
    def enable_gc_stats(self):
        return self.__get_config().get_bool("enable_gc_stats")

    @property
    def disable_all_config_updates(self):
        return self.__get_config().get_int(
            "disable_leak_all_config_updates", none_if_missing=True
        )

    @property
    def disable_verify_config(self):
        return self.__get_config().get_int(
            "disable_leak_verify_config", none_if_missing=True
        )

    @property
    def disable_config_equivalence_check(self):
        return self.__get_config().get_int(
            "disable_leak_config_equivalence_check", none_if_missing=True
        )

    @property
    def disable_verify_can_write_to_logs(self):
        return self.__get_config().get_int(
            "disable_leak_verify_can_write_to_logs", none_if_missing=True
        )

    @property
    def disable_config_reload(self):
        return self.__get_config().get_int(
            "disable_leak_config_reload", none_if_missing=True
        )

    @property
    def config_change_check_interval(self):
        return self.__get_config().get_float("config_change_check_interval")

    @property
    def overall_stats_log_interval(self):
        return self.__get_config().get_float("overall_stats_log_interval")

    @property
    def copying_manager_stats_log_interval(self):
        return self.__get_config().get_float("copying_manager_stats_log_interval")

    @property
    def bandwidth_stats_log_interval(self):
        return self.__get_config().get_float("bandwidth_stats_log_interval")

    @property
    def user_agent_refresh_interval(self):
        return self.__get_config().get_float("user_agent_refresh_interval")

    @property
    def garbage_collect_interval(self):
        return self.__get_config().get_int("garbage_collect_interval")

    @property
    def disable_verify_config_create_monitors_manager(self):
        return self.__get_config().get_int(
            "disable_leak_verify_config_create_monitors_manager", none_if_missing=True
        )

    @property
    def disable_verify_config_create_copying_manager(self):
        return self.__get_config().get_int(
            "disable_leak_verify_config_create_copying_manager", none_if_missing=True
        )

    @property
    def disable_verify_config_cache_config(self):
        return self.__get_config().get_bool("disable_leak_verify_config_cache_config")

    # end Debug leak flags

    @property
    def read_time(self):
        """Returns the time this configuration file was read."""
        return self.__read_time

    @property
    def file_path(self):
        """Returns the time this path of the file that was read for the configuration."""
        return self.__file_path

    @property
    def additional_file_paths(self):
        """Returns a list of the paths for the additional files from the configuration directory that were read."""
        return self.__additional_paths

    @property
    def last_error(self):
        """Returns the error seen (if any) while processing the configuration."""
        return self.__last_error

    @property
    def log_configs(self):
        """Returns the list of configuration entries for all the logs specified in the configuration file.

        Note, this does not include logs required by monitors.  It is only logs explicitly listed in the configuration
        file and possible the agent log as well.

        @rtype list<JsonObject>"""
        return self.__log_configs

    @property
    def journald_log_configs(self):
        """Returns the list of configuration entries for all the journald loggers specified in the configuration file.

        @rtype list<JsonObject>"""
        return self.__journald_log_configs

    @property
    def k8s_log_configs(self):
        """Returns the list of configuration entries for all the k8s loggers specified in the configuration file.

        @rtype list<JsonObject>"""
        return self.__k8s_log_configs

    @property
    def monitor_configs(self):
        """Returns the list of configuration entries for all monitores specified in the configuration file.

        Note, this does not include default monitors for the platform.  It is only monitors explicitly listed in the
        configuration file.

        @rtype list<JsonObject>"""
        return self.__monitor_configs

    @property
    def agent_data_path(self):
        """Returns the configuration value for 'agent_data_path'."""
        return self.__get_config().get_string("agent_data_path")

    @property
    def agent_log_path(self):
        """Returns the configuration value for 'agent_log_path'."""
        return self.__get_config().get_string("agent_log_path")

    @property
    def additional_monitor_module_paths(self):
        """Returns the configuration value for 'additional_monitor_module_paths'."""
        return self.__get_config().get_string("additional_monitor_module_paths")

    @property
    def api_key(self):
        """Returns the configuration value for 'api_key'."""
        return self.__get_config().get_string("api_key")

    @property
    def scalyr_server(self):
        """Returns the configuration value for 'scalyr_server'."""
        return self.__get_config().get_string("scalyr_server")

    @property
    def raw_scalyr_server(self):
        """Returns the configuration value for 'raw_scalyr_server'."""
        return self.__get_config().get_string("raw_scalyr_server")

    @property
    def check_remote_if_no_tty(self):
        """Returns the configuration value for `check_remote_if_no_tty`"""
        return self.__get_config().get_bool("check_remote_if_no_tty")

    @property
    def server_attributes(self):
        """Returns the configuration value for 'server_attributes'."""
        return self.__get_config().get_json_object("server_attributes")

    @property
    def implicit_agent_log_collection(self):
        """Returns the configuration value for 'implicit_agent_log_collection'."""
        return self.__get_config().get_bool("implicit_agent_log_collection")

    @property
    def implicit_metric_monitor(self):
        """Returns the configuration value for 'implicit_metric_monitor'."""
        return self.__get_config().get_bool("implicit_metric_monitor")

    @property
    def implicit_agent_process_metrics_monitor(self):
        """Returns the configuration value for 'implicit_agent_process_metrics_monitor'."""
        return self.__get_config().get_bool("implicit_agent_process_metrics_monitor")

    @property
    def use_unsafe_debugging(self):
        """Returns the configuration value for 'unsafe_debugging'.

        Note, this should be used with extreme care.  It allows arbitrary commands to be executed by any local
        user on the system as the user running the agent."""
        return self.__get_config().get_bool("use_unsafe_debugging")

    @property
    def copying_thread_profile_interval(self):
        """Returns the interval (in seconds) between outputs of the profiling for the copying thread.
        This should be zero unless you are profiling the copying thread.
        """
        return self.__get_config().get_int("copying_thread_profile_interval")

    @property
    def copying_thread_profile_output_path(self):
        """Returns the path prefix for writing all profiling dumps for the copying thread, when
        ``copying_thread_profile_interval`` is greater than zero.
        @return:
        @rtype:
        """
        return self.__get_config().get_string("copying_thread_profile_output_path")

    @property
    def config_directory(self):
        """Returns the configuration value for 'config_directory', resolved to full path if necessary."""
        config_directory = self.__get_config().get_string("config_directory")

        # The configuration directory's path is relative to the the directory this configuration
        # file is stored in.
        return self.__resolve_absolute_path(
            config_directory, self.__get_parent_directory(self.__file_path)
        )

    @property
    def config_directory_raw(self):
        """Returns the configuration value for 'config_directory', as recorded in the configuration file."""
        return self.__get_config().get_string("config_directory")

    @property
    def parsed_max_send_rate_enforcement(self):
        """Returns the configuration value for 'max_send_rate_enforcement' in bytes per second if not `unlimited` or `legacy`."""
        return self.__get_config().get_float(
            "parsed_max_send_rate_enforcement", none_if_missing=True
        )

    @property
    def max_send_rate_enforcement(self):
        """Returns the raw value for 'max_send_rate_enforcement'."""
        return self.__get_config().get_string("max_send_rate_enforcement")

    @property
    def disable_max_send_rate_enforcement_overrides(self):
        """Returns the configuration value for 'disable_max_send_rate_enforcement_overrides'."""
        return self.__get_config().get_bool(
            "disable_max_send_rate_enforcement_overrides"
        )

    @property
    def extra_config_directory(self):
        """Returns the configuration value for `extra_config_directory`, resolved to full path if
        necessary."""

        # If `extra_config_directory` is a relative path, then it will be relative
        # to the directory containing the main config file
        if self.__extra_config_directory is None:
            return None

        return self.__resolve_absolute_path(
            self.__extra_config_directory,
            self.__get_parent_directory(self.__file_path),
        )

    @property
    def extra_config_directory_raw(self):
        """Returns the configuration value for 'extra_config_directory'."""
        return self.__extra_config_directory

    @property
    def max_allowed_request_size(self):
        """Returns the configuration value for 'max_allowed_request_size'."""
        return self.__get_config().get_int("max_allowed_request_size")

    @property
    def min_allowed_request_size(self):
        """Returns the configuration value for 'min_allowed_request_size'."""
        return self.__get_config().get_int("min_allowed_request_size")

    @property
    def min_request_spacing_interval(self):
        """Returns the configuration value for 'min_request_spacing_interval'."""
        return self.__get_config().get_float("min_request_spacing_interval")

    @property
    def max_request_spacing_interval(self):
        """Returns the configuration value for 'max_request_spacing_interval'."""
        return self.__get_config().get_float("max_request_spacing_interval")

    @property
    def max_error_request_spacing_interval(self):
        """Returns the configuration value for 'max_error_request_spacing_interval'."""
        return self.__get_config().get_float("max_error_request_spacing_interval")

    @property
    def low_water_bytes_sent(self):
        """Returns the configuration value for 'low_water_bytes_sent'."""
        return self.__get_config().get_int("low_water_bytes_sent")

    @property
    def low_water_request_spacing_adjustment(self):
        """Returns the configuration value for 'low_water_request_spacing_adjustment'."""
        return self.__get_config().get_float("low_water_request_spacing_adjustment")

    @property
    def high_water_bytes_sent(self):
        """Returns the configuration value for 'high_water_bytes_sent'."""
        return self.__get_config().get_int("high_water_bytes_sent")

    @property
    def high_water_request_spacing_adjustment(self):
        """Returns the configuration value for 'high_water_request_spacing_adjustment'."""
        return self.__get_config().get_float("high_water_request_spacing_adjustment")

    @property
    def max_new_log_detection_time(self):
        """Returns the configuration value for 'max_new_log_detection_time'."""
        return self.__get_config().get_float("max_new_log_detection_time")

    @property
    def failure_request_spacing_adjustment(self):
        """Returns the configuration value for 'failure_request_spacing_adjustment'."""
        return self.__get_config().get_float("failure_request_spacing_adjustment")

    @property
    def request_too_large_adjustment(self):
        """Returns the configuration value for 'request_too_large_adjustment'."""
        return self.__get_config().get_float("request_too_large_adjustment")

    @property
    def request_deadline(self):
        """Returns the configuration value for 'request_deadline'."""
        return self.__get_config().get_float("request_deadline")

    @property
    def debug_level(self):
        """Returns the configuration value for 'debug_level'."""
        return self.__get_config().get_int("debug_level")

    @property
    def stdout_severity(self):
        """Returns the configuration value for 'stdout_severity'.
        Only used when running in no-fork mode.
        """
        return self.__get_config().get_string("stdout_severity").upper()

    @property
    def ca_cert_path(self):
        """Returns the configuration value for 'ca_cert_path'."""
        return self.__get_config().get_string("ca_cert_path")

    @property
    def use_new_ingestion(self):
        """Returns the configuration value for 'use_new_ingestion'."""
        return self.__get_config().get_bool("use_new_ingestion")

    @property
    def new_ingestion_bootstrap_address(self):
        """Returns the configuration value for 'bootstrap_address'."""
        return self.__get_config().get_string("new_ingestion_bootstrap_address")

    @property
    def new_ingestion_use_tls(self):
        """Returns the configuration value for 'bootstrap_address'."""
        return self.__get_config().get_bool("new_ingestion_use_tls")

    @property
    def compression_type(self):
        """Returns the configuration value for 'compression_type'."""
        return self.__get_config().get_string("compression_type", none_if_missing=True)

    @property
    def compression_level(self):
        """Returns the configuration value for 'compression_level'."""
        return self.__get_config().get_int("compression_level", default_value=9)

    @property
    def use_requests_lib(self):
        """Returns the configuration value for 'use_requests_lib'."""
        return self.__get_config().get_bool("use_requests_lib")

    @property
    def use_tlslite(self):
        """Returns the configuration value for 'use_tlslite'."""
        return self.__get_config().get_bool("use_tlslite")

    @property
    def network_proxies(self):
        """Returns the proxy map created by the 'https_proxy' and 'http_proxy' configuration variables, or
        None if neither of those is set.
        """
        https_proxy = self.__get_config().get_string(
            "https_proxy", none_if_missing=True
        )
        http_proxy = self.__get_config().get_string("http_proxy", none_if_missing=True)
        if https_proxy is None and http_proxy is None:
            return None
        result = {}
        if https_proxy is not None:
            result["https"] = https_proxy
        if http_proxy is not None:
            result["http"] = http_proxy
        return result

    @property
    def global_monitor_sample_interval(self):
        """Returns the configuration value for 'global_monitor_sample_interval'."""
        return self.__get_config().get_float("global_monitor_sample_interval")

    @property
    def global_monitor_sample_interval_enable_jitter(self):
        """Returns the configuration value for 'global_monitor_sample_interval_enable_jitter'."""
        return self.__get_config().get_bool(
            "global_monitor_sample_interval_enable_jitter"
        )

    @property
    def full_checkpoint_interval(self):
        """Returns the configuration value for 'full_checkpoint_interval_in_seconds'."""
        return self.__get_config().get_int("full_checkpoint_interval_in_seconds")

    @property
    def minimum_scan_interval(self):
        """Returns the configuration value for 'minimum_scan_interval'."""
        return self.__get_config().get_int(
            "minimum_scan_interval", none_if_missing=True
        )

    @property
    def close_old_files_duration_in_seconds(self):
        """Returns the configuration value for 'close_old_files_duration_in_seconds'."""
        return self.__get_config().get_int("close_old_files_duration_in_seconds")

    @property
    def max_line_size(self):
        """Returns the configuration value for 'max_line_size'."""
        return self.__get_config().get_int("max_line_size")

    @property
    def line_completion_wait_time(self):
        """Returns the configuration value for 'line_completion_wait_time'."""
        return self.__get_config().get_float("line_completion_wait_time")

    @property
    def internal_parse_max_line_size(self):
        """Returns the configuration value for 'internal_parse_max_line_size'."""
        return self.__get_config().get_int("internal_parse_max_line_size")

    @property
    def max_log_offset_size(self):
        """Returns the configuration value for 'max_log_offset_size'."""
        return self.__get_config().get_int("max_log_offset_size")

    @property
    def max_existing_log_offset_size(self):
        """Returns the configuration value for 'max_existing_log_offset_size'."""
        return self.__get_config().get_int("max_existing_log_offset_size")

    @property
    def max_sequence_number(self):
        """Returns the maximum sequence number"""
        return self.__get_config().get_int("max_sequence_number")

    @property
    def read_page_size(self):
        """Returns the configuration value for 'read_page_size'."""
        return self.__get_config().get_int("read_page_size")

    @property
    def log_deletion_delay(self):
        """Returns the configuration value for 'log_deletion_delay'."""
        return self.__get_config().get_float("log_deletion_delay")

    @property
    def log_rotation_max_bytes(self):
        """Returns the configuration value for 'log_rotation_max_bytes'."""
        return self.__get_config().get_int("log_rotation_max_bytes")

    @property
    def log_rotation_backup_count(self):
        """Returns the configuration value for 'log_rotation_backup_count'."""
        return self.__get_config().get_int("log_rotation_backup_count")

    @property
    def copy_staleness_threshold(self):
        """Returns the configuration value for 'copy_staleness_threshold'."""
        return self.__get_config().get_float("copy_staleness_threshold")

    @property
    def debug_init(self):
        """Returns the configuration value for 'debug_init'."""
        return self.__get_config().get_bool("debug_init")

    @property
    def pidfile_advanced_reuse_guard(self):
        """Returns the configuration value for 'pidfile_advanced_reuse_guard'."""
        return self.__get_config().get_bool("pidfile_advanced_reuse_guard")

    @property
    def verify_server_certificate(self):
        """Returns the configuration value for 'verify_server_certificate'."""
        return self.__get_config().get_bool("verify_server_certificate")

    @property
    def pipeline_threshold(self):
        """Returns the percentage an add events request must be of the maximum allowed request size to
        trigger pipelining the next add events request.
        """
        return self.__get_config().get_float("pipeline_threshold")

    @property
    def strip_domain_from_default_server_host(self):
        """Returns whether or not we should remove the domain name from the default server host that is used to
        identify the source of the logs from this agent.  For example, if the hostname is `foo.scalyr.com`, setting
        this field to `true` will result in `foo` being used as the reported `serverHost` name.

        This only applies if you do not set an explicit `serverHost` attribute in the server attributes.
        """
        return self.__get_config().get_bool("strip_domain_from_default_server_host")

    @property
    def healthy_max_time_since_last_copy_attempt(self):
        """Returns the max amount of time since the last copy attempt to consider the agent 'healthy' for
        the purpose of a health check using `status -v` or `-H`. This copy attempt need not be successful, since this is
        just to check that the agent is healthy and should not reflect server side errors.
        """
        return self.__get_config().get_float("healthy_max_time_since_last_copy_attempt")

    # Windows specific options below

    @property
    def win32_max_open_fds(self):
        """
        Returns value of the win32_max_open_fds config option which is Windows specific.
        """
        return self.__get_config().get_int("win32_max_open_fds")

    @property
    def worker_configs(self):
        return self.__worker_configs

    @property
    def sanitized_worker_configs(self):
        """
        Special version of "worker_configs" attribute which removes / masks actual API tokens
        in the returned output.
        """
        worker_configs = copy.deepcopy(self.__worker_configs)

        result = []
        for worker_config in worker_configs:
            # TODO: Should we still log last 3-4 characters of the key to make troubleshooting
            # easier?
            worker_config["api_key"] = MASKED_CONFIG_ITEM_VALUE
            result.append(dict(worker_config))

        return result

    def get_number_of_configured_sessions_and_api_keys(self):
        # type: () -> Tuple[str, int, int]
        """
        Return total number of configured sessions from all workers and a total number of unique API keys those
        workers are configured with.

        It returns a tuple of (worker_type, sessions_count, unique API keys count). Value for
        worker_type is "threaded" and "multiprocess."

        If multiple sessions / workers functionality is not enabled (*, 1, 1) is returned.
        """
        sessions_count = 0
        api_keys_set = set([])
        for worker_config in self.__worker_configs:
            api_keys_set.add(worker_config["api_key"])
            sessions_count += worker_config["sessions"]

        api_keys_count = len(api_keys_set)
        del api_keys_set

        if self.use_multiprocess_workers:
            worker_type = "multiprocess"
        else:
            worker_type = "threaded"

        return worker_type, sessions_count, api_keys_count

    @property
    def use_multiprocess_workers(self):
        """
        Return whether or not copying manager workers are in the multiprocessing mode.
        """
        return self.__get_config().get_bool("use_multiprocess_workers")

    @property
    def default_sessions_per_worker(self):
        """
        The default number of sessions which should be created for each worker if no value is explicitly set
        """
        return self.__get_config().get_int("default_sessions_per_worker")

    @property
    def default_worker_session_status_message_interval(self):
        return self.__get_config().get_float(
            "default_worker_session_status_message_interval"
        )

    @property
    def enable_worker_session_process_metrics_gather(self):
        """
        If it True and multi-process workers are used, then the instance of the linux process monitor
        is created for each worker session process.
        """
        return self.__get_config().get_bool("enable_worker_process_metrics_gather")

    @property
    def enable_copy_truncate_log_rotation_support(self):
        """
        Return whether copy truncate log rotation support is enabled.
        """
        return self.__get_config().get_bool("enable_copy_truncate_log_rotation_support")

    def equivalent(self, other, exclude_debug_level=False):
        """Returns true if other contains the same configuration information as this object.

        This is different than an '_eq_' method because this comparison ignores some of the fields
        such as what times the files were read at.  Also, it compares the final results of the configuration,
        after defaults have been applied.

        @param exclude_debug_level: If True, will also ignore the values for 'debug_level' when doing comparison.
        """
        if self.__last_error != other.__last_error:
            return False

        original_debug_level = None
        try:
            # If we are ignoring debug level, then we do a little hack here where we just put the value for
            # this config into other's config.. and then just put the original value back after we've done the
            # comparison.
            if exclude_debug_level:
                original_debug_level = other.__config.get("debug_level")
                other.__config.put("debug_level", self.__config.get("debug_level"))

            if self.__config != other.__config:
                return False
            return True
        finally:
            if original_debug_level is not None:
                other.__config.put("debug_level", original_debug_level)

    @staticmethod
    def get_extra_config_dir(extra_config_dir):
        """
        Returns the value for the additional config directory - either from the value passed
        in, or from the environment variable `SCALYR_EXTRA_CONFIG_DIR`.

        @param extra_config_dir: the additinal configuration directory.  If this value is
            None, then the environment variable `SCALYR_EXTRA_CONFIG_DIR` is read for the result
        """
        result = extra_config_dir
        if extra_config_dir is None:
            result = compat.os_getenv_unicode("SCALYR_EXTRA_CONFIG_DIR")
        return result

    @staticmethod
    def default_ca_cert_path():
        """Returns the default configuration file path for the agent."""
        # TODO:  Support more platforms.
        return Configuration.__resolve_to_install_location("certs", "ca_certs.crt")

    @property
    def intermediate_certs_path(self):
        """Returns the intermediate certs path."""
        return Configuration.__resolve_to_install_location(
            "certs", "intermediate_certs.pem"
        )

    @staticmethod
    def __resolve_to_install_location(*paths):
        """Returns the absolute path created by joining the specified intermediate paths to
        the install location for this package.

        @param paths: The file components of the desired path. There can be multiple, starting with the outer directory
            first and finishing with the last file.
        """
        result = get_install_root()
        for path in paths:
            result = os.path.join(result, path)
        return result

    def __get_parent_directory(self, file_path):
        """Returns the directory containing the specified file.

        @param file_path: The absolute file path.

        @return: The absolute path for the parent directory."""
        return os.path.dirname(file_path)

    def __resolve_absolute_path(self, file_path, working_directory):
        """Returns the full path for the specified file.

        If the specified file path is relative, then working_directory is used to resolve the relative path.
        This function does not do any existence checks on either file_path or working_directory.

        @param file_path: The path of the file.
        @param working_directory: The directory to use to resolve relative file paths.

        @return: The absolute path for the specified file.
        """
        if os.path.isabs(file_path):
            return file_path

        return os.path.join(working_directory, file_path)

    def __list_files(self, directory_path):
        """Returns a list of the files ending in .json for the specified directory.

        This only returns files in the directory.  Also, if the directory does not exist
        or cannot be read, an empty list is returned.

        @param directory_path: The path of the directory.

        @return: If the directory exists and can be read, the list of files ending in .json (not directories).
        """
        result = []
        if directory_path is None:
            return result
        if not os.path.isdir(directory_path):
            return result
        if not os.access(directory_path, os.R_OK):
            return result

        for f in sorted(os.listdir(directory_path)):
            if f.endswith(".json"):
                full_path = os.path.join(directory_path, f)
                if os.path.isfile(full_path):
                    result.append(full_path)
        return result

    def __add_elements_from_array(
        self, field, source_json, destination_json, deprecated_names=None
    ):
        """Appends any elements in the JsonArray in source_json to destination_json.

        @param field: The name of the field containing the JsonArray.
        @param source_json: The JsonObject containing the JsonArray from which to retrieve elements.
        @param destination_json: The JsonObject to which the elements should be added (in the JsonArray named field.
        @param deprecated_names: List of synonym names for the *field* that were used in previous version but now
        are deprecated. If the current *field* is not presented, then we also look for the deprecated names for
        backward compatibility.
        """
        destination_array = destination_json.get_json_array(field, none_if_missing=True)
        if destination_array is None and deprecated_names is not None:
            for name in deprecated_names:
                destination_array = destination_json.get_json_array(
                    name, none_if_missing=True
                )

        for element in source_json.get_json_array(field):
            destination_array.add(element)

    def __set_api_key(self, config, api_key):
        """
        Sets the api_key of the config, and throws errors if there are any problems
        """
        if api_key:
            config.put("api_key", api_key)

        if "api_key" not in config:
            raise BadConfiguration(
                'The configuration file is missing the required field "api_key" that '
                "sets the authentication key to use when writing logs to Scalyr.  Please update "
                "the config file with a Write Logs key from https://www.scalyr.com/keys",
                "api_key",
                "missingApiKey",
            )

        if config.get_string("api_key") == "":
            raise BadConfiguration(
                "The configuration file contains an empty string for the required field "
                '"api_key" that sets the authentication key to use when writing logs to Scalyr. '
                "Please update the config file with a Write Logs key from https://www.scalyr.com/keys",
                "api_key",
                "emptyApiKey",
            )

    def __check_field(
        self,
        field,
        config,
        file_path,
        previous_value=None,
        previous_config_file=None,
        error_code=None,
    ):
        """
        Checks to see if the config contains a value for `field` , and if so verifies that it is a valid string.

        @param field:  The name of the field to check.
        @param config:  The contents of the config.
        @param file_path:  The file path to the config.
        @param previous_value:  If this field has been already defined in another config, the value it was given.
        @param previous_config_file:  If not None, the path to a config file that has already set this field.  If this
            is not None and this config does define the field, a `BadConfiguration` exception is raised.
        @param error_code:  The error code to return if it is detected the field has been set in multiple config files.
        @return the field's value and file_path if the field is found, else return None and None

        """

        description = 'configuration file "%s"' % file_path

        if field in config:
            self.__verify_required_string(config, field, description)
            result_key = config.get_string(field)
            result_file = file_path

            if previous_config_file is not None:
                raise BadConfiguration(
                    'The configuration file "%s" contains an "%s" value, but that field has already been set in '
                    '"%s".  Please ensure that the "%s" value is set only once'
                    % (file_path, field, previous_config_file, field),
                    field,
                    error_code,
                )

            return result_key, result_file
        return previous_value, previous_config_file

    def __verify_main_config(self, config, file_path):
        self.__verify_main_config_and_apply_defaults(
            config, file_path, apply_defaults=False
        )

    def __verify_main_config_and_apply_defaults(
        self, config, file_path, apply_defaults=True
    ):
        """Verifies the contents of the configuration object and updates missing fields with defaults.

        This will verify and possibly update all the fields in the configuration file except for
        the 'logs' and 'monitors' json arrays.  If any of the fields do not meet their type requirement,
        an exception will be raised.  If any of the fields are not present, then config will be updated with
        the appropriate default value.

        @param config: The main JsonObject configuration object.
        @param file_path: The file that was read to retrieve the config object. This is used in error reporting.
        @param apply_defaults: If true, apply default values for any missing fields.  If false do not set values
            for any fields missing from the config.
        """
        description = 'configuration file "%s"' % file_path

        self.__verify_or_set_optional_string(
            config, "api_key", "", description, apply_defaults, env_aware=True
        )
        self.__verify_or_set_optional_bool(
            config, "allow_http", False, description, apply_defaults, env_aware=True
        )
        self.__verify_or_set_optional_bool(
            config,
            "check_remote_if_no_tty",
            False,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_string(
            config,
            "compression_type",
            "deflate",
            description,
            apply_defaults,
            env_aware=True,
            valid_values=scalyr_util.SUPPORTED_COMPRESSION_ALGORITHMS,
        )
        self.__verify_compression_type(self.compression_type)

        # NOTE: If not explicitly specified by the user, we use compression algorithm specific
        # default value
        default_compression_level = scalyr_util.COMPRESSION_TYPE_TO_DEFAULT_LEVEL[
            self.compression_type
        ]
        self.__verify_or_set_optional_int(
            config,
            "compression_level",
            default_compression_level,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_compression_level(self.compression_level)

        self.__verify_or_set_optional_attributes(
            config,
            "server_attributes",
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_string(
            config,
            "agent_log_path",
            self.__default_paths.agent_log_path,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_string(
            config,
            "agent_data_path",
            self.__default_paths.agent_data_path,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_string(
            config,
            "additional_monitor_module_paths",
            "",
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_string(
            config,
            "config_directory",
            "agent.d",
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_string(
            config,
            "json_library",
            "auto",
            "JSON serialization and deserializarion library to use. Valid options are auto, json, ujson and orjson",
            apply_defaults,
            env_aware=True,
            valid_values=["auto", "json", "ujson", "orjson"],
        )
        self.__verify_or_set_optional_bool(
            config,
            "implicit_agent_log_collection",
            True,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_bool(
            config,
            "implicit_metric_monitor",
            True,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_bool(
            config,
            "implicit_agent_process_metrics_monitor",
            True,
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_bool(
            config,
            "use_unsafe_debugging",
            False,
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_int(
            config,
            "copying_thread_profile_interval",
            0,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_string(
            config,
            "copying_thread_profile_output_path",
            "/tmp/copying_thread_profiles_",
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_float(
            config,
            "global_monitor_sample_interval",
            30.0,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_bool(
            config,
            "global_monitor_sample_interval_enable_jitter",
            True,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_int(
            config,
            "close_old_files_duration_in_seconds",
            60 * 60 * 1,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_int(
            config,
            "full_checkpoint_interval_in_seconds",
            60,
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_string(
            config,
            "max_send_rate_enforcement",
            "unlimited",
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_bool(
            config,
            "disable_max_send_rate_enforcement_overrides",
            False,
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_int(
            config,
            "max_allowed_request_size",
            1 * 1024 * 1024,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_int(
            config,
            "min_allowed_request_size",
            100 * 1024,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_float(
            config,
            "min_request_spacing_interval",
            1.0,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_float(
            config,
            "max_request_spacing_interval",
            5.0,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_float(
            config,
            "max_error_request_spacing_interval",
            30.0,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_int(
            config,
            "minimum_scan_interval",
            None,
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_int(
            config,
            "low_water_bytes_sent",
            20 * 1024,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_float(
            config,
            "low_water_request_spacing_adjustment",
            1.5,
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_int(
            config,
            "high_water_bytes_sent",
            100 * 1024,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_float(
            config,
            "high_water_request_spacing_adjustment",
            0.6,
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_float(
            config,
            "failure_request_spacing_adjustment",
            1.5,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_float(
            config,
            "request_too_large_adjustment",
            0.5,
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_float(
            config,
            "max_new_log_detection_time",
            60.0,
            description,
            apply_defaults,
            env_aware=True,
        )

        # These parameters are used in log_processing.py to govern how logs are copied.

        # The maximum allowed size for a line when reading from a log file.
        # We do not strictly enforce this -- some lines returned by LogFileIterator may be
        # longer than this due to some edge cases.
        self.__verify_or_set_optional_int(
            config, "max_line_size", 49900, description, apply_defaults, env_aware=True
        )

        # The number of seconds we are willing to wait when encountering a log line at the end of a log file that does
        # not currently end in a new line (referred to as a partial line).  It could be that the full line just hasn't
        # made it all the way to disk yet.  After this time though, we will just return the bytes as a line
        self.__verify_or_set_optional_float(
            config,
            "line_completion_wait_time",
            5,
            description,
            apply_defaults,
            env_aware=True,
        )

        # The maximum negative offset relative to the end of a previously unseen log the log file
        # iterator is allowed to become.  If bytes are not being read quickly enough, then
        # the iterator will automatically advance so that it is no more than this length
        # to the end of the file.  This is essentially the maximum bytes a new log file
        # is allowed to be caught up when used in copying logs to Scalyr.
        self.__verify_or_set_optional_int(
            config,
            "max_log_offset_size",
            5 * 1024 * 1024,
            description,
            apply_defaults,
            env_aware=True,
        )

        # The maximum negative offset relative to the end of an existing log the log file
        # iterator is allowed to become.  If bytes are not being read quickly enough, then
        # the iterator will automatically advance so that it is no more than this length
        # to the end of the file.  This is essentially the maximum bytes an existing log file
        # is allowed to be caught up when used in copying logs to Scalyr.
        self.__verify_or_set_optional_int(
            config,
            "max_existing_log_offset_size",
            100 * 1024 * 1024,
            description,
            apply_defaults,
            env_aware=True,
        )

        # The maximum sequence number for a given sequence
        # The sequence number is typically the total number of bytes read from a given file
        # (across restarts and log rotations), and it resets to zero (and begins a new sequence)
        # for each file once the current sequence_number exceeds this value
        # defaults to 1 TB
        self.__verify_or_set_optional_int(
            config,
            "max_sequence_number",
            1024 ** 4,
            description,
            apply_defaults,
            env_aware=True,
        )

        # The number of bytes to read from a file at a time into the buffer.  This must
        # always be greater than the MAX_LINE_SIZE
        self.__verify_or_set_optional_int(
            config,
            "read_page_size",
            64 * 1024,
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_int(
            config,
            "internal_parse_max_line_size",
            config.get_int("read_page_size", 64 * 1024),
            description,
            apply_defaults,
            env_aware=True,
        )

        # The minimum time we wait for a log file to reappear on a file system after it has been removed before
        # we consider it deleted.
        self.__verify_or_set_optional_float(
            config,
            "log_deletion_delay",
            10 * 60,
            description,
            apply_defaults,
            env_aware=True,
        )

        # How many log rotations to do
        self.__verify_or_set_optional_int(
            config,
            "log_rotation_backup_count",
            2,
            description,
            apply_defaults,
            env_aware=True,
        )

        # The size of each log rotation file
        self.__verify_or_set_optional_int(
            config,
            "log_rotation_max_bytes",
            20 * 1024 * 1024,
            description,
            apply_defaults,
            env_aware=True,
        )

        # The percentage of the maximum message size a message (max_allowed_request_size) has to be to trigger
        # pipelining the next add events request.  This intentionally set to 110% to prevent it from being used unless
        # explicitly requested.
        self.__verify_or_set_optional_float(
            config,
            "pipeline_threshold",
            1.1,
            description,
            apply_defaults,
            env_aware=True,
        )

        # If we have noticed that new bytes have appeared in a file but we do not read them before this threshold
        # is exceeded, then we consider those bytes to be stale and just skip to reading from the end to get the
        # freshest bytes.
        self.__verify_or_set_optional_float(
            config,
            "copy_staleness_threshold",
            15 * 60,
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_bool(
            config, "debug_init", False, description, apply_defaults, env_aware=True
        )

        self.__verify_or_set_optional_bool(
            config,
            "pidfile_advanced_reuse_guard",
            False,
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_bool(
            config,
            "strip_domain_from_default_server_host",
            False,
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_float(
            config,
            "healthy_max_time_since_last_copy_attempt",
            60.0,
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_int(
            config,
            "win32_max_open_fds",
            # We default it to 512 which is also the default value for Python processes on Windows.
            # Max is 2048.
            512,
            description,
            apply_defaults,
            env_aware=True,
            min_value=512,
            max_value=2048,
        )

        self.__verify_or_set_optional_int(
            config, "debug_level", 0, description, apply_defaults, env_aware=True
        )
        debug_level = config.get_int("debug_level", apply_defaults)
        if debug_level < 0 or debug_level > 5:
            raise BadConfiguration(
                "The debug level must be between 0 and 5 inclusive",
                "debug_level",
                "badDebugLevel",
            )

        self.__verify_or_set_optional_string(
            config,
            "stdout_severity",
            "NOTSET",
            description,
            apply_defaults,
            env_aware=True,
        )
        stdout_severity = config.get_string("stdout_severity", default_value="NOTSET")
        if not hasattr(logging, stdout_severity.upper()):
            raise BadConfiguration(
                "The stdout severity must be a valid logging level name",
                "stdout_severity",
                "badStdoutSeverity",
            )

        self.__verify_or_set_optional_float(
            config,
            "request_deadline",
            60.0,
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_string(
            config,
            "ca_cert_path",
            Configuration.default_ca_cert_path(),
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_string(
            config,
            "new_ca_cert_path",
            Configuration.default_ca_cert_path(),
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_bool(
            config,
            "use_new_ingestion",
            False,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_string(
            config,
            "new_ingestion_bootstrap_address",
            "127.0.0.1:4772",
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_bool(
            config,
            "new_ingestion_use_tls",
            False,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_bool(
            config,
            "use_requests_lib",
            False,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_bool(
            config, "use_tlslite", False, description, apply_defaults, env_aware=True
        )
        self.__verify_or_set_optional_bool(
            config,
            "verify_server_certificate",
            True,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_string(
            config, "http_proxy", None, description, apply_defaults, env_aware=True
        )
        self.__verify_or_set_optional_string(
            config, "https_proxy", None, description, apply_defaults, env_aware=True
        )
        self.__verify_or_set_optional_array_of_strings(
            config,
            "k8s_ignore_namespaces",
            Configuration.DEFAULT_K8S_IGNORE_NAMESPACES,
            description,
            apply_defaults,
            separators=[None, ","],
            env_aware=True,
        )
        self.__verify_or_set_optional_array_of_strings(
            config,
            "k8s_include_namespaces",
            Configuration.DEFAULT_K8S_INCLUDE_NAMESPACES,
            description,
            apply_defaults,
            separators=[None, ","],
            env_aware=True,
        )
        self.__verify_or_set_optional_string(
            config,
            "k8s_api_url",
            "https://kubernetes.default",
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_bool(
            config,
            "k8s_verify_api_queries",
            True,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_bool(
            config,
            "k8s_verify_kubelet_queries",
            True,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_string(
            config,
            "k8s_kubelet_ca_cert",
            "/run/secrets/kubernetes.io/serviceaccount/ca.crt",
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_int(
            config,
            "k8s_cache_query_timeout_secs",
            20,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_int(
            config,
            "k8s_cache_expiry_secs",
            30,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_int(
            config,
            "k8s_cache_expiry_fuzz_secs",
            0,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_int(
            config,
            "k8s_cache_start_fuzz_secs",
            0,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_int(
            config,
            "k8s_cache_purge_secs",
            300,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_string(
            config,
            "k8s_service_account_cert",
            "/run/secrets/kubernetes.io/serviceaccount/ca.crt",
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_string(
            config,
            "k8s_service_account_token",
            "/var/run/secrets/kubernetes.io/serviceaccount/token",
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_string(
            config,
            "k8s_service_account_namespace",
            "/var/run/secrets/kubernetes.io/serviceaccount/namespace",
            description,
            apply_defaults,
            env_aware=True,
        )

        # Whether to log api responses to agent_debug.log
        self.__verify_or_set_optional_bool(
            config,
            "k8s_log_api_responses",
            False,
            description,
            apply_defaults,
            env_aware=True,
        )

        # If set to True, do not log successes (response code 2xx)
        self.__verify_or_set_optional_bool(
            config,
            "k8s_log_api_exclude_200s",
            False,
            description,
            apply_defaults,
            env_aware=True,
        )
        # Minimum response length of api responses to be logged.  Responses smaller than this limit are not logged.
        self.__verify_or_set_optional_int(
            config,
            "k8s_log_api_min_response_len",
            0,
            description,
            apply_defaults,
            env_aware=True,
        )
        # Minimum latency of responses to be logged.  Responses faster than this limit are not logged.
        self.__verify_or_set_optional_float(
            config,
            "k8s_log_api_min_latency",
            0.0,
            description,
            apply_defaults,
            env_aware=True,
        )
        # If positive, api calls with the same path will be rate-limited to a message every interval seconds
        self.__verify_or_set_optional_int(
            config,
            "k8s_log_api_ratelimit_interval",
            0,
            description,
            apply_defaults,
            env_aware=True,
        )

        # TODO-163 : make other settings more aggressive

        # Optional (defaults to 3). The number of times the warmer will retry a query to warm a pod before giving up and
        # classifying it as a Temporary Error
        self.__verify_or_set_optional_int(
            config,
            "k8s_controlled_warmer_max_query_retries",
            3,
            description,
            apply_defaults,
            env_aware=True,
        )
        # Optional (defaults to 5). The maximum number of Temporary Errors that may occur when warming a pod's entry,
        # before the warmer blacklists it.
        self.__verify_or_set_optional_int(
            config,
            "k8s_controlled_warmer_max_attempts",
            5,
            description,
            apply_defaults,
            env_aware=True,
        )
        # Optional (defaults to 300). When a pod is blacklisted, how many secs it must wait until it is
        # tried again for warming.
        self.__verify_or_set_optional_int(
            config,
            "k8s_controlled_warmer_blacklist_time",
            300,
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_bool(
            config,
            "k8s_events_disable",
            False,
            description,
            apply_defaults,
            env_aware=True,
        )

        # Agent-wide k8s rate limiter settings
        self.__verify_or_set_optional_string(
            config,
            "k8s_ratelimit_cluster_num_agents",
            1,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_float(
            config,
            "k8s_ratelimit_cluster_rps_init",
            1000.0,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_float(
            config,
            "k8s_ratelimit_cluster_rps_min",
            1.0,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_float(
            config,
            "k8s_ratelimit_cluster_rps_max",
            1e9,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_int(
            config,
            "k8s_ratelimit_consecutive_increase_threshold",
            5,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_string(
            config,
            "k8s_ratelimit_strategy",
            BlockingRateLimiter.STRATEGY_MULTIPLY,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_float(
            config,
            "k8s_ratelimit_increase_factor",
            2.0,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_float(
            config,
            "k8s_ratelimit_backoff_factor",
            0.5,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_int(
            config,
            "k8s_ratelimit_max_concurrency",
            1,
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_bool(
            config,
            "disable_send_requests",
            False,
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_bool(
            config,
            "enforce_monotonic_timestamps",
            False,
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_bool(
            config,
            "include_raw_timestamp_field",
            True,
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_bool(
            config,
            "enable_profiling",
            False,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_int(
            config,
            "max_profile_interval_minutes",
            60,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_int(
            config,
            "profile_duration_minutes",
            2,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_string(
            config,
            "profile_clock",
            "random",
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_string(
            config,
            "profile_log_name",
            "agent.callgrind",
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_string(
            config,
            "memory_profile_log_name",
            "agent.meminfo",
            description,
            apply_defaults,
            env_aware=True,
        )

        # AGENT-263: controls sending in the new format or not as a safety in case it is broken somewhere in the chain
        # TODO: Remove this in a future release once we are more certain that it works
        self.__verify_or_set_optional_bool(
            config,
            "disable_logfile_addevents_format",
            False,
            description,
            apply_defaults,
            env_aware=True,
        )

        # Debug leak flags
        self.__verify_or_set_optional_bool(
            config, "disable_leak_monitor_threads", False, description, apply_defaults
        )
        self.__verify_or_set_optional_bool(
            config, "disable_leak_monitors_creation", False, description, apply_defaults
        )
        self.__verify_or_set_optional_bool(
            config, "disable_leak_new_file_matches", False, description, apply_defaults
        )
        self.__verify_or_set_optional_bool(
            config,
            "disable_leak_scan_for_new_bytes",
            False,
            description,
            apply_defaults,
        )
        self.__verify_or_set_optional_bool(
            config,
            "disable_leak_processing_new_bytes",
            False,
            description,
            apply_defaults,
        )
        self.__verify_or_set_optional_bool(
            config, "disable_leak_copying_thread", False, description, apply_defaults
        )
        self.__verify_or_set_optional_bool(
            config, "disable_leak_overall_stats", False, description, apply_defaults
        )
        self.__verify_or_set_optional_bool(
            config, "disable_leak_bandwidth_stats", False, description, apply_defaults
        )
        self.__verify_or_set_optional_bool(
            config,
            "disable_copy_manager_stats",
            False,
            description,
            apply_defaults,
        )
        self.__verify_or_set_optional_bool(
            config,
            "disable_leak_update_debug_log_level",
            False,
            description,
            apply_defaults,
        )
        self.__verify_or_set_optional_bool(
            config, "enable_gc_stats", False, description, apply_defaults
        )
        self.__verify_or_set_optional_int(
            config, "disable_leak_all_config_updates", None, description, apply_defaults
        )
        self.__verify_or_set_optional_int(
            config, "disable_leak_verify_config", None, description, apply_defaults
        )
        self.__verify_or_set_optional_int(
            config,
            "disable_leak_config_equivalence_check",
            None,
            description,
            apply_defaults,
        )
        self.__verify_or_set_optional_int(
            config,
            "disable_leak_verify_can_write_to_logs",
            None,
            description,
            apply_defaults,
        )
        self.__verify_or_set_optional_int(
            config, "disable_leak_config_reload", None, description, apply_defaults
        )

        self.__verify_or_set_optional_float(
            config,
            "config_change_check_interval",
            30,
            description,
            apply_defaults,
            env_aware=True,
        )
        # How often to capture and log overall agent stats (in seconds).
        # NOTE: This values must be >= config_change_check_interval.
        self.__verify_or_set_optional_float(
            config,
            "overall_stats_log_interval",
            600,
            description,
            apply_defaults,
            env_aware=True,
        )
        # How often to capture and log copying manager agent stats (in seconds).
        # NOTE: This values must be >= config_change_check_interval.
        self.__verify_or_set_optional_float(
            config,
            "copying_manager_stats_log_interval",
            300,
            description,
            apply_defaults,
            env_aware=True,
        )
        # How often to capture and log bandwidth related stats (in seconds).
        # NOTE: This values must be >= config_change_check_interval.
        self.__verify_or_set_optional_float(
            config,
            "bandwidth_stats_log_interval",
            60,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_int(
            config,
            "user_agent_refresh_interval",
            60,
            description,
            apply_defaults,
            env_aware=True,
        )
        self.__verify_or_set_optional_int(
            config,
            "garbage_collect_interval",
            300,
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_int(
            config,
            "disable_leak_verify_config_create_monitors_manager",
            None,
            description,
            apply_defaults,
        )
        self.__verify_or_set_optional_int(
            config,
            "disable_leak_verify_config_create_copying_manager",
            None,
            description,
            apply_defaults,
        )
        self.__verify_or_set_optional_bool(
            config,
            "disable_leak_verify_config_cache_config",
            False,
            description,
            apply_defaults,
        )

        # if true, the copying manager creates each session of its workers in a separate process.
        self.__verify_or_set_optional_bool(
            config,
            "use_multiprocess_workers",
            False,
            description,
            apply_defaults,
            env_aware=True,
            deprecated_names=["use_multiprocess_copying_workers"],
        )

        # the default number of sessions per worker.
        self.__verify_or_set_optional_int(
            config,
            "default_sessions_per_worker",
            1,
            description,
            apply_defaults,
            env_aware=True,
            min_value=1,
            deprecated_names=["default_workers_per_api_key"],
        )

        self.__verify_or_set_optional_float(
            config,
            "default_worker_session_status_message_interval",
            600.0,
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_bool(
            config,
            "enable_worker_process_metrics_gather",
            False,
            description,
            apply_defaults,
            env_aware=True,
        )

        self.__verify_or_set_optional_bool(
            config,
            "enable_copy_truncate_log_rotation_support",
            True,
            description,
            apply_defaults,
        )

        # windows does not support copying manager backed with multiprocessing workers.
        if config.get_bool("use_multiprocess_workers", none_if_missing=True):
            if platform.system() == "Windows":
                raise BadConfiguration(
                    "The 'use_multiprocess_workers' option is not supported on windows machines.",
                    "use_multiprocess_workers",
                    error_code="invalidValue",
                )
            elif sys.version_info < (2, 7):
                raise BadConfiguration(
                    "The 'use_multiprocess_workers' option is supported only for Python version higher than 2.6.",
                    "use_multiprocess_workers",
                    error_code="invalidValue",
                )

    def __verify_compression_type(self, compression_type):
        """
        Verify that the library for the specified compression type (algorithm) is available.
        """
        library_name = scalyr_util.COMPRESSION_TYPE_TO_PYTHON_LIBRARY.get(
            compression_type, "unknown"
        )

        try:
            _, _ = scalyr_util.get_compress_and_decompress_func(compression_type)
        except (ImportError, ValueError) as e:
            msg = (
                'Failed to set compression type to "%s". Make sure that the corresponding Python '
                "library is available. You can install it using this command:\n\npip install %s\n\n "
                "Original error: %s" % (compression_type, library_name, str(e))
            )
            raise BadConfiguration(msg, "compression_type", "invalidCompressionType")

        if compression_type == "none":
            self.__logger.warn(
                "No compression will be used for outgoing requests. In most scenarios this will "
                "result in larger data egress traffic which may incur additional charges on your "
                "side (depending on your infrastructure provider, location, pricing model, etc.).",
                limit_once_per_x_secs=86400,
                limit_key="compression_type_none",
            )

    def __verify_compression_level(self, compression_level):
        """
        Verify that the provided compression level is valid for the configured compression type.

        If it's not, we use a default value for that compression algorithm. Keep in mind that this
        behavior is there for backward compatibility reasons, otherwise it would be better to just
        throw in such scenario
        """
        compression_type = self.compression_type

        valid_level_min, valid_level_max = scalyr_util.COMPRESSION_TYPE_TO_VALID_LEVELS[
            compression_type
        ]

        if compression_level < valid_level_min or compression_level > valid_level_max:
            self.__config.put(
                "compression_level",
                scalyr_util.COMPRESSION_TYPE_TO_DEFAULT_LEVEL[compression_type],
            )

    def __get_config_val(self, config_object, param_name, param_type):
        """
        Get parameter with a given type from the config object.
        @param config_object: The JsonObject config containing the field as a key
        @param param_name: Parameter name
        @param param_type: Parameter type
        :return:
        """
        if param_type == int:
            config_val = config_object.get_int(param_name, none_if_missing=True)
        elif param_type == bool:
            config_val = config_object.get_bool(param_name, none_if_missing=True)
        elif param_type == float:
            config_val = config_object.get_float(param_name, none_if_missing=True)
        elif param_type == six.text_type:
            config_val = config_object.get_string(param_name, none_if_missing=True)
        elif param_type == JsonObject:
            config_val = config_object.get_json_object(param_name, none_if_missing=True)
        elif param_type == JsonArray:
            config_val = config_object.get_json_array(param_name, none_if_missing=True)
        elif param_type in (ArrayOfStrings, SpaceAndCommaSeparatedArrayOfStrings):
            # ArrayOfStrings are extracted from config file as JsonArray
            # (but extracted from the environment different from JsonArray)
            config_val = config_object.get_json_array(param_name, none_if_missing=True)
        else:
            raise TypeError(
                "Unsupported environment variable conversion type %s (param name = %s)"
                % (param_type, param_name)
            )

        return config_val

    def __get_config_or_environment_val(
        self,
        config_object,
        param_name,
        param_type,
        env_aware,
        custom_env_name,
        deprecated_names=None,
    ):
        """Returns a type-converted config param value or if not found, a matching environment value.

        If the environment value is returned, it is also written into the config_object.

        Currently only handles the following types (str, int, bool, float, JsonObject, JsonArray).
        Also validates that environment variables can be correctly converted into the primitive type.

        Both upper-case and lower-case versions of the environment variable will be checked.

        @param config_object: The JsonObject config containing the field as a key
        @param param_name: Parameter name
        @param param_type: Parameter type
        @param env_aware: If True and not defined in config file, look for presence of environment variable.
        @param custom_env_name: If provided, will use this name to lookup the environment variable.  Otherwise, use
            scalyr_<field> as the environment variable name. Both upper and lower case versions are tried.
            Note: A non-empty value also automatically implies env_aware as True, regardless of it's value.
        @param deprecated_names: List of synonym names for the *param_name* that were used in previous version but now
        are deprecated. If the current *param_name* is not presented, then we also look for the deprecated names for
        backward compatibility.

        @return A python object representing the config param (or environment) value or None
        @raises
            JsonConversionException: if the config value or env value cannot be correctly converted.
            TypeError: if the param_type is not supported.
        """

        config_val = self.__get_config_val(config_object, param_name, param_type)

        # the config param is not presented by its current name, look for a deprecated name.
        if config_val is None and deprecated_names is not None:
            for name in deprecated_names:
                config_val = self.__get_config_val(config_object, name, param_type)
                if config_val is not None:
                    config_object.put(param_name, config_val)
                    del config_object[name]
                    if self.__logger and self.__log_warnings:
                        self.__logger.warning(
                            "The configuration option {0} is deprecated, use {1} instead.".format(
                                name, param_name
                            ),
                            limit_once_per_x_secs=86400,
                            limit_key="deprecatedConfigOption",
                        )
                    break

        if not env_aware:
            if not custom_env_name:
                return config_val

        self._environment_aware_map[param_name] = custom_env_name or (
            "SCALYR_%s" % param_name.upper()
        )

        env_val = get_config_from_env(
            param_name,
            custom_env_name=custom_env_name,
            convert_to=param_type,
            logger=self.__logger,
            param_val=config_val,
        )

        # the config param environment variable is not presented by its current name, look for a deprecated name.
        if env_val is None and deprecated_names is not None:
            for name in deprecated_names:
                env_val = get_config_from_env(
                    name,
                    convert_to=param_type,
                    logger=self.__logger,
                    param_val=config_val,
                )
                if env_val is not None:
                    break

        # Not set in environment
        if env_val is None:
            return config_val

        # Config file value wins if set
        if config_val is not None:
            return config_val

        config_object.update({param_name: env_val})
        return env_val

    def __verify_logs_and_monitors_configs_and_apply_defaults(self, config, file_path):
        """Verifies the contents of the 'logs' and 'monitors' fields and updates missing fields with defaults.

        This will verify and possible update the json arrays holding the 'logs' and 'monitor's configuration.
        If any of the fields in those arrays or their contained elements do not meet their type requirement,
        an exception will be raised.  If any of the fields are not present, then config will be updated with
        the appropriate default values.

        @param config: The main JsonObject configuration object.
        @param file_path: The file that was read to retrieve the config object. This is used in error reporting.
        """
        description = 'in configuration file "%s"' % file_path
        self.__verify_or_set_optional_array(config, "logs", description)
        self.__verify_or_set_optional_array(config, "journald_logs", description)
        self.__verify_or_set_optional_array(config, "k8s_logs", description)
        self.__verify_or_set_optional_array(config, "monitors", description)
        self.__verify_or_set_optional_array(
            config, "workers", description, deprecated_names=["api_keys"]
        )

        i = 0
        for log_entry in config.get_json_array("logs"):
            self.__verify_log_entry_and_set_defaults(
                log_entry, config_file_path=file_path, entry_index=i
            )
            i += 1

        i = 0
        for log_entry in config.get_json_array("journald_logs"):
            bad_config = False
            try:
                self.__verify_log_entry_with_key_and_set_defaults(
                    log_entry,
                    key="journald_unit",
                    config_file_path=file_path,
                    entry_index=i,
                    logs_field="journald_logs",
                )
            except BadConfiguration as e:
                if self.__logger and self.__log_warnings:
                    self.__logger.warn(
                        "Failed to parse journald_logs.journald_unit config "
                        "option, falling back to journald_logs.journald_globs: %s"
                        % str(e)
                    )
                bad_config = True

            if bad_config:
                self.__verify_log_entry_with_key_and_set_defaults(
                    log_entry,
                    key="journald_globs",
                    config_file_path=file_path,
                    entry_index=i,
                    key_type="object",
                    logs_field="journald_logs",
                )

            i += 1

        i = 0
        for log_entry in config.get_json_array("k8s_logs"):
            self.__verify_k8s_log_entry_and_set_defaults(
                log_entry,
                config_file_path=file_path,
                entry_index=i,
            )
            i += 1

        i = 0
        for monitor_entry in config.get_json_array("monitors"):
            self.__verify_monitor_entry_and_set_defaults(
                monitor_entry, file_path=file_path, entry_index=i
            )
            i += 1

    def __verify_k8s_log_entry_and_set_defaults(
        self,
        log_entry,
        description=None,
        config_file_path=None,
        entry_index=None,
    ):
        """Verifies that the configuration for the specified k8s log entry.

        A "k8s_log" entry can have one of multiple keys defined `k8s_pod_glob`, `k8s_namespace_glob`,
        or `k8s_container_glob` which is a string containing a glob pattern to match against.

        By default each of these values is `*` which matches against everything.  Users can
        set these fields to limit the log configuration to specific pods, namespaces and containers.

        Only the first matching config will be applied to any give log.  Users should make sure to
        place more specific matching rules before more general ones.

        Also verify the rest of the log config meets the required log config criteria and sets any defaults.

        Raises an exception if it does not.

        @param log_entry: The JsonObject holding the configuration for a log.
        @param description: A human-readable description of where the log entry came from to use in error messages. If
            none is given, then both file_path and entry_index must be set.
        @param config_file_path: The path for the file from where the configuration was read. Used to generate the
            description if none was given.
        @param entry_index: The index of the entry in the 'logs' json array. Used to generate the description if none
            was given.
        """

        self.__verify_or_set_optional_string(
            log_entry, "k8s_pod_glob", "*", description
        )
        self.__verify_or_set_optional_string(
            log_entry, "k8s_namespace_glob", "*", description
        )
        self.__verify_or_set_optional_string(
            log_entry, "k8s_container_glob", "*", description
        )

        self.__verify_log_entry_with_key_and_set_defaults(
            log_entry,
            None,
            description=description,
            config_file_path=config_file_path,
            entry_index=entry_index,
            # k8s log config defaults are applied later when adding containers to the copying manager
            # so don't set them here
            apply_defaults=False,
            logs_field="k8s_logs",
        )

    def __verify_log_entry_and_set_defaults(
        self, log_entry, description=None, config_file_path=None, entry_index=None
    ):
        """Verifies that the configuration for the specified log has a key called 'path' and meets all
        the required criteria and sets any defaults.

        Raises an exception if it does not.

        @param log_entry: The JsonObject holding the configuration for a log.
        @param description: A human-readable description of where the log entry came from to use in error messages. If
            none is given, then both file_path and entry_index must be set.
        @param config_file_path: The path for the file from where the configuration was read. Used to generate the
            description if none was given.
        @param entry_index: The index of the entry in the 'logs' json array. Used to generate the description if none
            was given.
        """
        # Make sure the log_entry has a path and the path is absolute.
        path = log_entry.get_string("path", none_if_missing=True)
        if path and not os.path.isabs(path):
            log_entry.put("path", os.path.join(self.agent_log_path, path))
        self.__verify_log_entry_with_key_and_set_defaults(
            log_entry,
            "path",
            description=description,
            config_file_path=config_file_path,
            entry_index=entry_index,
        )

        # set default worker if it is not specified.
        self.__verify_or_set_optional_string(
            log_entry,
            "worker_id",
            "default",
            description,
        )

    def __verify_log_entry_with_key_and_set_defaults(
        self,
        log_entry,
        key=None,
        description=None,
        config_file_path=None,
        entry_index=None,
        apply_defaults=True,
        logs_field="logs",
        key_type="string",
    ):
        """Verifies that the configuration for the specified log meets all the required criteria and sets any defaults.

        Raises an exception if it does not.

        @param log_entry: The JsonObject holding the configuration for a log.
        @param key: A key that must exist in the log entry.  The key is used to identify logs e.g. by path, container name etc
            If `None` then no checking is done
        @param description: A human-readable description of where the log entry came from to use in error messages. If
            none is given, then both file_path and entry_index must be set.
        @param config_file_path: The path for the file from where the configuration was read. Used to generate the
            description if none was given.
        @param entry_index: The index of the entry in the 'logs' json array. Used to generate the description if none
            was given.
        @param apply_defaults: If true, apply default values for any missing fields.  If false do not set values
            for any fields missing from the config.
        @param logs_field: The name of the field used for log configs
        @param key_type: The type of key - defaults to string, but can also be `object` if the value is supposed to
            be a json object
        """
        no_description_given = description is None
        if no_description_given:
            description = (
                'the entry with index=%i in the "%s" array in configuration file "%s"'
                % (entry_index, logs_field, config_file_path)
            )
        log = None
        if key is not None:
            if key_type == "object":
                self.__verify_required_attributes(log_entry, key, description)
                log = key
            else:
                # Verify it has a `key` entry that is a string.
                self.__verify_required_string(log_entry, key, description)
                log = log_entry.get_string(key)

        if log is not None and no_description_given:
            description = (
                'the entry for "%s" in the "%s" array in configuration file "%s"'
                % (log, logs_field, config_file_path)
            )

        self.__verify_or_set_optional_array_of_strings(
            log_entry,
            "exclude",
            [],
            description,
            apply_defaults=apply_defaults,
        )

        # If a parser was specified, make sure it is a string.
        if "parser" in log_entry:
            self.__verify_or_set_optional_string(
                log_entry,
                "parser",
                "ignored",
                description,
                apply_defaults=apply_defaults,
            )

        self.__verify_or_set_optional_attributes(log_entry, "attributes", description)

        self.__verify_or_set_optional_array(log_entry, "lineGroupers", description)
        i = 0
        for element in log_entry.get_json_array("lineGroupers"):
            element_description = (
                'the entry with index=%i in the "lineGroupers" array in ' % i
            )
            element_description += description

            self.__verify_required_string(element, "start", element_description)
            self.__verify_contains_exactly_one_string_out_of(
                element,
                ["continueThrough", "continuePast", "haltBefore", "haltWith"],
                description,
            )
            i += 1

        self.__verify_or_set_optional_bool(
            log_entry,
            "copy_from_start",
            False,
            description,
            apply_defaults=apply_defaults,
        )
        self.__verify_or_set_optional_bool(
            log_entry, "parse_lines_as_json", None, description, apply_defaults=False
        )
        self.__verify_or_set_optional_string(
            log_entry,
            "parse_format",
            "raw",
            description,
            apply_defaults=apply_defaults,
        )
        self.__verify_or_set_optional_string(
            log_entry,
            "json_message_field",
            "log",
            description,
            apply_defaults=apply_defaults,
        )
        self.__verify_or_set_optional_string(
            log_entry,
            "json_timestamp_field",
            "time",
            description,
            apply_defaults=apply_defaults,
        )

        self.__verify_or_set_optional_bool(
            log_entry,
            "ignore_stale_files",
            False,
            description,
            apply_defaults=apply_defaults,
        )
        self.__verify_or_set_optional_float(
            log_entry,
            "staleness_threshold_secs",
            5 * 60,
            description,
            apply_defaults=apply_defaults,
        )

        self.__verify_or_set_optional_int(
            log_entry,
            "minimum_scan_interval",
            None,
            description,
            apply_defaults=apply_defaults,
        )

        # Verify that if it has a sampling_rules array, then it is an array of json objects.
        self.__verify_or_set_optional_array(log_entry, "sampling_rules", description)
        i = 0
        for element in log_entry.get_json_array("sampling_rules"):
            element_description = (
                'the entry with index=%i in the "sampling_rules" array in ' % i
            )
            element_description += description
            self.__verify_required_regexp(
                element, "match_expression", element_description
            )
            self.__verify_required_percentage(
                element, "sampling_rate", element_description
            )
            i += 1

        # Verify that if it has a redaction_rules array, then it is an array of json objects.
        self.__verify_or_set_optional_array(log_entry, "redaction_rules", description)
        i = 0
        for element in log_entry.get_json_array("redaction_rules"):
            element_description = (
                'the entry with index=%i in the "redaction_rules" array in ' % i
            )
            element_description += description

            self.__verify_required_regexp(
                element, "match_expression", element_description
            )
            self.__verify_or_set_optional_string(
                element, "replacement", "", element_description
            )
            i += 1

        # We support the parser definition being at the top-level of the log config object, but we really need to
        # put it in the attributes.
        if "parser" in log_entry:
            # noinspection PyTypeChecker
            log_entry["attributes"]["parser"] = log_entry["parser"]

    def __verify_monitor_entry_and_set_defaults(
        self, monitor_entry, context_description=None, file_path=None, entry_index=None
    ):
        """Verifies that the config for the specified monitor meets all the required criteria and sets any defaults.

        Raises an exception if it does not.

        @param monitor_entry: The JsonObject holding the configuration for a monitor.
        @param file_path: The path for the file from where the configuration was read. Used to report errors to user.
        @param entry_index: The index of the entry in the 'monitors' json array. Used to report errors to user.
        """
        # Verify that it has a module name
        if context_description is None:
            description = (
                'the entry with index=%i in the "monitors" array in configuration file "%s"'
                % (entry_index, file_path)
            )
        else:
            description = context_description

        self.__verify_required_string(monitor_entry, "module", description)

        module_name = monitor_entry.get_string("module")

        if context_description is None:
            description = (
                'the entry for module "%s" in the "monitors" array in configuration file "%s"'
                % (module_name, file_path)
            )
        else:
            description = context_description

        # Verify that if it has a log_name field, it is a string.
        self.__verify_or_set_optional_string(
            monitor_entry, "log_path", module_name + ".log", description
        )

    def __verify_workers_entry_and_set_defaults(self, worker_entry, entry_index=None):
        """
        Verify the copying manager workers entry. and set defaults.
        """

        description = "the #%s entry of the 'workers' list."

        # the 'id' field is required, raise an error if it is not specified.
        self.__verify_required_string(worker_entry, "id", description)

        # the 'api_key' field is required, raise an error if it is not specified,
        # but we make an exception for the "default" worker.
        # The worker entry with "default" id may not have a "api_key" field and it will be the same as main api_key.
        worker_id = worker_entry.get("id")
        if worker_id == "default":
            api_key = worker_entry.get("api_key", none_if_missing=True)
            if api_key is not None and api_key != self.api_key:
                raise BadConfiguration(
                    "The API key of the default worker has to match the main API key of the configuration",
                    "workers",
                    "wrongDefaultWorker",
                )
            self.__verify_or_set_optional_string(
                worker_entry, "api_key", self.api_key, description % entry_index
            )
        else:

            # validate the worker id. It should consist only from this set of characters.
            allowed_worker_id_characters_pattern = "a-zA-Z0-9_"
            if re.search(
                r"[^{0}]+".format(allowed_worker_id_characters_pattern), worker_id
            ):
                raise BadConfiguration(
                    "The worker id '{0}' contains an invalid character. Please use only '{1}'".format(
                        worker_id, allowed_worker_id_characters_pattern
                    ),
                    "workers",
                    "invalidWorkerId",
                )
            self.__verify_required_string(
                worker_entry, "api_key", description % entry_index
            )

        sessions_number = self.__config.get_int("default_sessions_per_worker")
        self.__verify_or_set_optional_int(
            worker_entry,
            "sessions",
            sessions_number,
            description,
            min_value=1,
            deprecated_names=["workers"],
        )

    def __merge_server_attributes(self, fragment_file_path, config_fragment, config):
        """Merges the contents of the server attribute read from a configuration fragment to the main config object.

        @param fragment_file_path: The path of the file from which the fragment was read. Used for error messages.
        @param config_fragment: The JsonObject in the fragment file containing the 'server_attributes' field.
        @param config: The main config object also containing a server_attributes field. The contents of the one from
            config_fragment will be merged into this one.
        """
        self.__verify_or_set_optional_attributes(
            config_fragment,
            "server_attributes",
            'the configuration fragment at "%s"' % fragment_file_path,
        )
        source = config_fragment["server_attributes"]
        destination = config["server_attributes"]
        for k in source:
            destination[k] = source[k]

    def __verify_required_string(self, config_object, field, config_description):
        """Verifies that config_object has the required field and it can be converted to a string.

        Raises an exception otherwise.

        @param config_object: The JsonObject containing the configuration information.
        @param field: The name of the field to check in config_object.
        @param config_description: A description of where the configuration object was sourced from to be used in the
            error reporting to the user.
        """
        try:
            config_object.get_string(field)
        except JsonConversionException:
            raise BadConfiguration(
                'The field "%s" is not a string.  Error is in %s'
                % (field, config_description),
                field,
                "notString",
            )
        except JsonMissingFieldException:
            raise BadConfiguration(
                'The required field "%s" is missing.  Error is in %s'
                % (field, config_description),
                field,
                "missingRequired",
            )

    def __verify_contains_exactly_one_string_out_of(
        self, config_object, fields, config_description
    ):
        """Verifies that config_object has exactly one of the named fields and it can be converted to a string.

        Raises an exception otherwise.

        @param config_object: The JsonObject containing the configuration information.
        @param fields: A list of field names to check in the config_object.
        @param config_description: A description of where the configuration object was sourced from to be used in the
            error reporting to the user.
        @return: The name of the found key, or None
        """
        count = 0
        result = None
        for field in fields:
            try:
                value = config_object.get_string(field, none_if_missing=True)
                if value is not None:
                    result = field
                    count += 1
            except JsonConversionException:
                raise BadConfiguration(
                    'The field "%s" is not a string.  Error is in %s'
                    % (field, config_description),
                    field,
                    "notString",
                )
        if count == 0:
            raise BadConfiguration(
                'A required field is missing.  Object must contain one of "%s".  Error is in %s'
                % (six.text_type(fields), config_description),
                field,
                "missingRequired",
            )
        elif count > 1:
            raise BadConfiguration(
                'A required field has too many options.  Object must contain only one of "%s".  Error is in %s'
                % (six.text_type(fields), config_description),
                field,
                "missingRequired",
            )
        return result

    def __verify_or_set_optional_string(
        self,
        config_object,
        field,
        default_value,
        config_description,
        apply_defaults=True,
        env_aware=False,
        env_name=None,
        valid_values=None,
        deprecated_names=None,
    ):
        """Verifies that the specified field in config_object is a string if present, otherwise sets default.

        Raises an exception if the existing field cannot be converted to a string.

        @param config_object: The JsonObject containing the configuration information.
        @param field: The name of the field to check in config_object.
        @param default_value: The value to set in config_object for field if it currently has no value.
        @param config_description: A description of where the configuration object was sourced from to be used in the
            error reporting to the user.
        @param apply_defaults: If true, apply default values for any missing fields.  If false do not set values
            for any fields missing from the config.
        @param env_aware: If True and not defined in config file, look for presence of environment variable.
        @param env_name: If provided, will use this name to lookup the environment variable.  Otherwise, use
            scalyr_<field> as the environment variable name.
        @param valid_values: Optional list with valid values for this string.
        @param deprecated_names: List of synonym names for the *field* that were used in previous version but now
        are deprecated. If the current *field* is not presented, then we also look for the deprecated names for
        backward compatibility.
        """
        try:
            value = self.__get_config_or_environment_val(
                config_object,
                field,
                six.text_type,
                env_aware,
                env_name,
                deprecated_names=deprecated_names,
            )

            if value is None:
                if apply_defaults:
                    config_object.put(field, default_value)
                return

        except JsonConversionException:
            raise BadConfiguration(
                'The value for field "%s" is not a string.  Error is in %s'
                % (field, config_description),
                field,
                "notString",
            )

        if value is not None and valid_values and value not in valid_values:
            raise BadConfiguration(
                'Got invalid value "%s" for field "%s". Valid values are: %s'
                % (value, field, ", ".join(valid_values)),
                field,
                "invalidValue",
            )

    def __verify_or_set_optional_int(
        self,
        config_object,
        field,
        default_value,
        config_description,
        apply_defaults=True,
        env_aware=False,
        env_name=None,
        min_value=None,
        max_value=None,
        deprecated_names=None,
    ):
        """Verifies that the specified field in config_object can be converted to an int if present, otherwise
        sets default.

        Raises an exception if the existing field cannot be converted to an int.

        @param config_object: The JsonObject containing the configuration information.
        @param field: The name of the field to check in config_object.
        @param default_value: The value to set in config_object for field if it currently has no value.
        @param config_description: A description of where the configuration object was sourced from to be used in the
            error reporting to the user.
        @param apply_defaults: If true, apply default values for any missing fields.  If false do not set values
            for any fields missing from the config.
        @param env_aware: If True and not defined in config file, look for presence of environment variable.
        @param env_name: If provided, will use this name to lookup the environment variable.  Otherwise, use
            scalyr_<field> as the environment variable name.
        @param min_value: Optional minimum value for this configuration value.
        @param max_value: Optional maximum value for this configuration value.
        @param deprecated_names: List of synonym names for the *field* that were used in previous version but now
        are deprecated. If the current *field* is not presented, then we also look for the deprecated names for
        backward compatibility.
        """
        try:
            value = self.__get_config_or_environment_val(
                config_object,
                field,
                int,
                env_aware,
                env_name,
                deprecated_names=deprecated_names,
            )

            if value is None:
                if apply_defaults:
                    config_object.put(field, default_value)
                return

        except JsonConversionException:
            raise BadConfiguration(
                'The value for field "%s" is not an int.  Error is in %s'
                % (field, config_description),
                field,
                "notInt",
            )

        if value is not None and min_value is not None and value < min_value:
            raise BadConfiguration(
                'Got invalid value "%s" for field "%s". Value must be greater than or equal to %s'
                % (value, field, min_value),
                field,
                "invalidValue",
            )

        if value is not None and max_value is not None and value > max_value:
            raise BadConfiguration(
                'Got invalid value "%s" for field "%s". Value must be less than or equal to %s'
                % (value, field, max_value),
                field,
                "invalidValue",
            )

    def __verify_or_set_optional_float(
        self,
        config_object,
        field,
        default_value,
        config_description,
        apply_defaults=True,
        env_aware=False,
        env_name=None,
        deprecated_names=None,
    ):
        """Verifies that the specified field in config_object can be converted to a float if present, otherwise
        sets default.

        Raises an exception if the existing field cannot be converted to a float.

        @param config_object: The JsonObject containing the configuration information.
        @param field: The name of the field to check in config_object.
        @param default_value: The value to set in config_object for field if it currently has no value.
        @param config_description: A description of where the configuration object was sourced from to be used in the
            error reporting to the user.
        @param apply_defaults: If true, apply default values for any missing fields.  If false do not set values
            for any fields missing from the config.
        @param env_aware: If True and not defined in config file, look for presence of environment variable.
        @param env_name: If provided, will use this name to lookup the environment variable.  Otherwise, use
            scalyr_<field> as the environment variable name.
        @param deprecated_names: List of synonym names for the *field* that were used in previous version but now
        are deprecated. If the current *field* is not presented, then we also look for the deprecated names for
        backward compatibility.
        """
        try:
            value = self.__get_config_or_environment_val(
                config_object,
                field,
                float,
                env_aware,
                env_name,
                deprecated_names=deprecated_names,
            )

            if value is None:
                if apply_defaults:
                    config_object.put(field, default_value)
                return

        except JsonConversionException:
            raise BadConfiguration(
                'The value for field "%s" is not an float.  Error is in %s'
                % (field, config_description),
                field,
                "notFloat",
            )

    def __verify_or_set_optional_attributes(
        self,
        config_object,
        field,
        config_description,
        apply_defaults=True,
        env_aware=False,
        env_name=None,
        deprecated_names=None,
    ):
        """Verifies that the specified field in config_object is a json object if present, otherwise sets to empty
        object.

        Raises an exception if the existing field is not a json object or if any of its values cannot be converted
        to a string.

        @param config_object: The JsonObject containing the configuration information.
        @param field: The name of the field to check in config_object.
        @param config_description: A description of where the configuration object was sourced from to be used in the
            error reporting to the user.
        @param apply_defaults: If true, apply default values for any missing fields.  If false do not set values
            for any fields missing from the config.
        @param env_aware: If True and not defined in config file, look for presence of environment variable.
        @param env_name: If provided, will use this name to lookup the environment variable.  Otherwise, use
            scalyr_<field> as the environment variable name.
        @param deprecated_names: List of synonym names for the *field* that were used in previous version but now
        are deprecated. If the current *field* is not presented, then we also look for the deprecated names for
        backward compatibility.
        """
        try:
            json_object = self.__get_config_or_environment_val(
                config_object,
                field,
                JsonObject,
                env_aware,
                env_name,
                deprecated_names=deprecated_names,
            )

            if json_object is None:
                if apply_defaults:
                    config_object.put(field, JsonObject())
                return

            for key in json_object.keys():
                try:
                    json_object.get_string(key)
                except JsonConversionException:
                    raise BadConfiguration(
                        'The value for field "%s" in the json object for "%s" is not a '
                        "string.  Error is in %s" % (key, field, config_description),
                        field,
                        "notString",
                    )

        except JsonConversionException:
            raise BadConfiguration(
                'The value for the field "%s" is not a json object.  '
                "Error is in %s" % (field, config_description),
                field,
                "notJsonObject",
            )

    def __verify_or_set_optional_bool(
        self,
        config_object,
        field,
        default_value,
        config_description,
        apply_defaults=True,
        env_aware=False,
        env_name=None,
        deprecated_names=None,
    ):
        """Verifies that the specified field in config_object is a boolean if present, otherwise sets default.

        Raises an exception if the existing field cannot be converted to a boolean.

        @param config_object: The JsonObject containing the configuration information.
        @param field: The name of the field to check in config_object.
        @param default_value: The value to set in config_object for field if it currently has no value.
        @param config_description: A description of where the configuration object was sourced from to be used in the
            error reporting to the user.
        @param apply_defaults: If true, apply default values for any missing fields.  If false do not set values
            for any fields missing from the config.
        @param env_aware: If True and not defined in config file, look for presence of environment variable.
        @param env_name: If provided, will use this name to lookup the environment variable.  Otherwise, use
            scalyr_<field> as the environment variable name.
        @param deprecated_names: List of synonym names for the *field* that were used in previous version but now
        are deprecated. If the current *field* is not presented, then we also look for the deprecated names for
        backward compatibility.
        """
        try:
            value = self.__get_config_or_environment_val(
                config_object,
                field,
                bool,
                env_aware,
                env_name,
                deprecated_names=deprecated_names,
            )

            if value is None:
                if apply_defaults:
                    config_object.put(field, default_value)
                return

        except JsonConversionException:
            raise BadConfiguration(
                'The value for the required field "%s" is not a boolean.  '
                "Error is in %s" % (field, config_description),
                field,
                "notBoolean",
            )

    def __verify_or_set_optional_array(
        self,
        config_object,
        field,
        config_description,
        apply_defaults=True,
        env_aware=False,
        env_name=None,
        deprecated_names=None,
    ):
        """Verifies that the specified field in config_object is an array of json objects if present, otherwise sets
        to empty array.

        Raises an exception if the existing field is not a json array or if any of its elements are not json objects.

        @param config_object: The JsonObject containing the configuration information.
        @param field: The name of the field to check in config_object.
        @param config_description: A description of where the configuration object was sourced from to be used in the
            error reporting to the user.
        @param apply_defaults: If true, apply default values for any missing fields.  If false do not set values
            for any fields missing from the config.
        @param env_aware: If True and not defined in config file, look for presence of environment variable.
        @param env_name: If provided, will use this name to lookup the environment variable.  Otherwise, use
            scalyr_<field> as the environment variable name.
        @param deprecated_names: List of synonym names for the *field* that were used in previous version but now
        are deprecated. If the current *field* is not presented, then we also look for the deprecated names for
        backward compatibility.
        """
        try:
            json_array = self.__get_config_or_environment_val(
                config_object,
                field,
                JsonArray,
                env_aware,
                env_name,
                deprecated_names=deprecated_names,
            )

            if json_array is None:
                if apply_defaults:
                    config_object.put(field, JsonArray())
                return

            index = 0
            for x in json_array:
                if not isinstance(x, JsonObject):
                    raise BadConfiguration(
                        "The element at index=%i is not a json object as required in the array "
                        'field "%s (%s, %s)".  Error is in %s'
                        % (index, field, type(x), six.text_type(x), config_description),
                        field,
                        "notJsonObject",
                    )
                index += 1
        except JsonConversionException:
            raise BadConfiguration(
                'The value for the required field "%s" is not an array.  '
                "Error is in %s" % (field, config_description),
                field,
                "notJsonArray",
            )

    def __verify_or_set_optional_array_of_strings(
        self,
        config_object,
        field,
        default_value,
        config_description,
        apply_defaults=True,
        separators=[","],
        env_aware=False,
        env_name=None,
        deprecated_names=None,
    ):
        """Verifies that the specified field in config_object is an array of strings if present, otherwise sets
        to empty array.

        Raises an exception if the existing field is not a json array or if any of its elements are not strings/unicode.

        @param config_object: The JsonObject containing the configuration information.
        @param field: The name of the field to check in config_object.
        @param default_value: Default values (array of strings)
        @param config_description: A description of where the configuration object was sourced from to be used in the
            error reporting to the user.
        @param apply_defaults: If true, apply default values for any missing fields.  If false do not set values
            for any fields missing from the config.
        @param separators: list of allowed separators (An entry of None represents "any whitespace")
        @param env_aware: If True and not defined in config file, look for presence of environment variable.
        @param env_name: If provided, will use this name to lookup the environment variable.  Otherwise, use
            scalyr_<field> as the environment variable name.
        @param deprecated_names: List of synonym names for the *field* that were used in previous version but now
        are deprecated. If the current *field* is not presented, then we also look for the deprecated names for
        backward compatibility.
        """
        # 2->TODO Python3 can not sort None values
        separators.sort(key=lambda s: s if s is not None else "")
        # For legacy reasons, must support space-separated array of strings
        cls = ArrayOfStrings
        if separators == [None, ","]:
            cls = SpaceAndCommaSeparatedArrayOfStrings
        try:
            array_of_strings = self.__get_config_or_environment_val(
                config_object,
                field,
                cls,
                env_aware,
                env_name,
                deprecated_names=deprecated_names,
            )

            if array_of_strings is None:
                if apply_defaults:
                    config_object.put(field, cls(values=default_value))
                return

            index = 0
            for x in array_of_strings:
                if not isinstance(x, six.string_types):
                    raise BadConfiguration(
                        "The element at index=%i is not a string or unicode object as required in the array "
                        'field "%s".  Error is in %s'
                        % (index, field, config_description),
                        field,
                        "notStringOrUnicode",
                    )
                index += 1
        except JsonConversionException:
            raise BadConfiguration(
                'The value for the required field "%s" is not an array.  '
                "Error is in %s" % (field, config_description),
                field,
                "notJsonArray",
            )

    def __verify_required_attributes(
        self,
        config_object,
        field,
        config_description,
    ):
        """Verifies that the specified field in config_object is a json object if present, otherwise sets to empty
        object.

        Raises an exception if the existing field is not a json object or if any of its values cannot be converted
        to a string.

        @param config_object: The JsonObject containing the configuration information.
        @param field: The name of the field to check in config_object.
        @param config_description: A description of where the configuration object was sourced from to be used in the
            error reporting to the user.
        """
        try:
            value = config_object.get_json_object(field, none_if_missing=True) or {}

            for key in value.keys():
                try:
                    value.get_string(key)
                except JsonConversionException:
                    raise BadConfiguration(
                        'The value for field "%s" in the json object for "%s" is not a '
                        "string.  Error is in %s" % (key, field, config_description),
                        field,
                        "notString",
                    )

        except JsonConversionException:
            raise BadConfiguration(
                'The value for the field "%s" is not a json object.  '
                "Error is in %s" % (field, config_description),
                field,
                "notJsonObject",
            )

    def __verify_required_regexp(self, config_object, field, config_description):
        """Verifies that config_object has the specified field and it can be parsed as a regular expression, otherwise
        raises an exception.

        @param config_object: The JsonObject containing the configuration information.
        @param field: The name of the field to check in config_object.
        @param config_description: A description of where the configuration object was sourced from to be used in the
            error reporting to the user.
        """

        try:
            value = config_object.get_string(field, none_if_missing=True)

            if value is not None:
                re.compile(value)
                return
        except Exception:
            raise BadConfiguration(
                'The value for required field "%s" has a value that cannot be parsed as '
                "string regular expression (using python syntax).  "
                "Error is in %s" % (field, config_description),
                field,
                "notRegexp",
            )

        raise BadConfiguration(
            'The required regular expression field "%s" is missing.  Error is in %s'
            % (field, config_description),
            field,
            "missingRequired",
        )

    def __verify_required_percentage(self, config_object, field, config_description):
        """Verifies that config_object has the specified field and it can be it is a number between 0 and 1, otherwise
        raises an exception.

        @param config_object: The JsonObject containing the configuration information.
        @param field: The name of the field to check in config_object.
        @param config_description: A description of where the configuration object was sourced from to be used in the
            error reporting to the user.
        """
        try:
            value = config_object.get_float(field, none_if_missing=True)

            if value is None:
                raise BadConfiguration(
                    'The required percentage field "%s" is missing.  Error is in %s'
                    % (field, config_description),
                    field,
                    "missingRequired",
                )
            elif value < 0 or value > 1:
                raise BadConfiguration(
                    'The required percentage field "%s" has a value "%s" that is not a number '
                    "between 0 and 1 inclusive.  Error is in %s"
                    % (field, value, config_description),
                    field,
                    "notPercentage",
                )

        except JsonConversionException:
            raise BadConfiguration(
                'The required field "%s" has a value that cannot be parsed as a number between 0 '
                "and 1 inclusive.  Error is in %s" % (field, config_description),
                field,
                "notNumber",
            )

    def __get_config(self):
        if self.__last_error is not None:
            raise BadConfiguration(self.__last_error, "fake", "fake")
        return self.__config

    def __perform_substitutions(self, source_config):
        """Rewrites the content of the source_config to reflect the values in the `import_vars` array.

        @param source_config:  The configuration to rewrite, represented as key/value pairs.
        @type source_config: JsonObject
        """
        substitutions = import_shell_variables(source_config=source_config)
        if len(substitutions) > 0:
            perform_object_substitution(
                object_value=source_config, substitutions=substitutions
            )

    def __getstate__(self):
        """
        Remove unpicklable fields from the configuration instance.
        The configuration object need to be picklable because its instances may be passed
        to the multi-process copying manager worker sessions.
        """
        state = self.__dict__.copy()
        state.pop("_Configuration__logger", None)
        return state


"""
Utility functions related to shell variable handling and substition.

NOTE: Those functions are intentionally not defined inside "__perform_substitutions" to avoid memory
leaks.
"""


def import_shell_variables(source_config):
    """Creates a dict mapping variables listed in the `import_vars` field of `source_config` to their
    values from the environment.
    """
    result = dict()
    if "import_vars" in source_config:
        for entry in source_config.get_json_array("import_vars"):
            # Allow for an entry of the form { var: "foo", default: "bar"}
            if isinstance(entry, JsonObject):
                var_name = entry["var"]
                default_value = entry["default"]
            else:
                var_name = entry
                default_value = ""

            # 2->TODO in python2 os.environ returns 'str' type. Convert it to unicode.
            var_value = os_environ_unicode.get(var_name)
            if var_value:
                result[var_name] = var_value
            else:
                result[var_name] = default_value
    return result


def perform_generic_substitution(value, substitutions):
    """Takes a given JSON value and performs the appropriate substitution.

    This method will return a non-None value if the value has to be replaced with the returned value.
    Otherwise, this will attempt to perform in-place substitutions.

    For str, unicode, it substitutes the variables and returns the result.  For
    container objects, it does the recursive substitution.

    @param value: The JSON value
    @type value: Any valid element of a JsonObject
    @return: The value that should replace the original, if any.  If no replacement is necessary, returns None
    """
    result = None
    value_type = type(value)

    if value_type is six.text_type and "$" in value:
        result = perform_str_substitution(value, substitutions=substitutions)
    elif isinstance(value, JsonObject):
        perform_object_substitution(value, substitutions=substitutions)
    elif isinstance(value, JsonArray):
        perform_array_substitution(value, substitutions=substitutions)
    return result


def perform_object_substitution(object_value, substitutions):
    """Performs the in-place substitution for a JsonObject.

    @param object_value: The object to perform substitutions on.
    @type object_value: JsonObject
    """
    # We collect the new values and apply them later to avoid messing up the iteration.
    new_values = {}
    for (key, value) in six.iteritems(object_value):
        replace_value = perform_generic_substitution(value, substitutions=substitutions)
        if replace_value is not None:
            new_values[key] = replace_value

    for (key, value) in six.iteritems(new_values):
        object_value[key] = value


def perform_str_substitution(str_value, substitutions):
    """Performs substitutions on the given string.

    @param str_value: The input string.
    @type str_value: str or unicode
    @return: The resulting value after substitution.
    @rtype: str or unicode
    """
    result = str_value
    for (var_name, value) in six.iteritems(substitutions):
        result = result.replace("$%s" % var_name, value)
    return result


def perform_array_substitution(array_value, substitutions):
    """Perform substitutions on the JsonArray.

    @param array_value: The array
    @type array_value: JsonArray
    """
    for i in range(len(array_value)):
        replace_value = perform_generic_substitution(
            array_value[i], substitutions=substitutions
        )
        if replace_value is not None:
            array_value[i] = replace_value
