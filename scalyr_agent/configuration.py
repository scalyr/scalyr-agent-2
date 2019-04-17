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

__author__ = 'czerwin@scalyr.com'

import os
import re
import socket
import time
import urlparse

import scalyr_agent.util as scalyr_util

from scalyr_agent.json_lib import JsonConversionException, JsonMissingFieldException
from scalyr_agent.json_lib.objects import JsonObject, JsonArray, ArrayOfStrings
from scalyr_agent.util import JsonReadFileException
from scalyr_agent.config_util import BadConfiguration, get_config_from_env

from __scalyr__ import get_install_root


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
    """
    def __init__(self, file_path, default_paths, logger):
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
        # The monitor configuration objects from the configuration file.  This does not include monitors that
        # are created by default by the platform.
        self.__monitor_configs = []

        # The DefaultPaths object that specifies the default paths for things like the data and log directory
        # based on platform.
        self.__default_paths = default_paths

        # FIX THESE:
        # Add documentation, verify, etc.
        self.max_retry_time = 15 * 60
        self.max_allowed_checkpoint_age = 15 * 60

        self.__logger = logger

    def parse(self):
        self.__read_time = time.time()

        try:
            try:
                # First read the file.  This makes sure it exists and can be parsed.
                self.__config = scalyr_util.read_file_as_json(self.__file_path)

                # What implicit entries do we need to add?  metric monitor, agent.log, and then logs from all monitors.
            except JsonReadFileException, e:
                raise BadConfiguration(str(e), None, 'fileParseError')

            # Import any requested variables from the shell and use them for substitutions.
            self.__perform_substitutions(self.__config)

            # get initial list of already seen config keys (we need to do this before
            # defaults have been applied)
            already_seen = {}
            for k in self.__config.keys():
                already_seen[k] = self.__file_path

            self.__verify_main_config_and_apply_defaults(self.__config, self.__file_path)
            api_key, api_config_file = self.__check_field('api_key', self.__config, self.__file_path)
            scalyr_server, scalyr_server_config_file = self.__check_field('scalyr_server', self.__config,
                                                                          self.__file_path)
            self.__verify_logs_and_monitors_configs_and_apply_defaults(self.__config, self.__file_path)

            # these variables are allowed to appear in multiple files
            allowed_multiple_keys = ('import_vars', 'logs', 'monitors', 'server_attributes')

            # Now, look for any additional configuration in the config fragment directory.
            for fp in self.__list_files(self.config_directory):
                self.__additional_paths.append(fp)
                content = scalyr_util.read_file_as_json(fp)
                for k in content.keys():
                    if k not in allowed_multiple_keys:
                        if k in already_seen:
                            self.__last_error = BadConfiguration(
                                'Configuration fragment file "%s" redefines the config key "%s", first seen in "%s". '
                                'The only config items that can be defined in multiple config files are: %s.'
                                % (fp, k, already_seen[k], allowed_multiple_keys), k, 'multipleKeys')
                            raise self.__last_error
                        else:
                            already_seen[k] = fp

                self.__perform_substitutions(content)
                self.__verify_main_config(content, self.__file_path)
                self.__verify_logs_and_monitors_configs_and_apply_defaults(content, fp)

                for (key, value) in content.iteritems():
                    if key not in allowed_multiple_keys:
                        self.__config.put(key, value)

                self.__add_elements_from_array('logs', content, self.__config)
                self.__add_elements_from_array('monitors', content, self.__config)
                self.__merge_server_attributes(fp, content, self.__config)

            self.__set_api_key(self.__config, api_key)
            if scalyr_server is not None:
                self.__config.put('scalyr_server', scalyr_server)
            self.__verify_or_set_optional_string(self.__config, 'scalyr_server', 'https://agent.scalyr.com',
                                                 'configuration file %s' % self.__file_path,
                                                 env_name='SCALYR_SERVER')

            self.__config['raw_scalyr_server'] = self.__config['scalyr_server']

            # force https unless otherwise instructed not to
            if not self.__config['allow_http']:
                server = self.__config['scalyr_server'].strip()
                https_server = server

                parts = urlparse.urlparse( server )
                if not parts.scheme:
                    https_server = 'https://' + server
                elif parts.scheme == 'http':
                    https_server = re.sub( "^http://", "https://", server )

                if https_server != server:
                    self.__config['scalyr_server'] = https_server

            # Add in 'serverHost' to server_attributes if it is not set.  We must do this after merging any
            # server attributes from the config fragments.
            if 'serverHost' not in self.server_attributes:
                self.__config['server_attributes']['serverHost'] = self.__get_default_hostname()

            # Add in implicit entry to collect the log generated by this agent.
            agent_log = None
            if self.implicit_agent_log_collection:
                config = JsonObject(path='agent.log', parser='scalyrAgentLog')
                self.__verify_log_entry_and_set_defaults(config, description='implicit rule')
                agent_log = config

            self.__log_configs = list(self.__config.get_json_array('logs'))
            if agent_log is not None:
                self.__log_configs.append(agent_log)

            self.__monitor_configs = list(self.__config.get_json_array('monitors'))

        except BadConfiguration, e:
            self.__last_error = e
            raise e

    def __get_default_hostname(self):
        """Returns the default hostname for this host.
        @return: The default hostname for this host.
        @rtype: str
        """
        result = socket.gethostname()
        if result is not None and self.strip_domain_from_default_server_host:
            result = result.split('.')[0]
        return result

    def parse_log_config(self, log_config, default_parser=None, context_description='uncategorized log entry'):
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
            self.__verify_or_set_optional_string(log_config, 'parser', default_parser, context_description)
        self.__verify_log_entry_and_set_defaults(log_config, description=context_description)

        return log_config

    def parse_monitor_config(self, monitor_config, context_description='uncategorized monitor entry'):
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

        self.__verify_monitor_entry_and_set_defaults(monitor_config, context_description=context_description)

        return monitor_config

    # k8s cache options
    @property
    def k8s_ignore_namespaces(self):
        return self.__get_config().get_string('k8s_ignore_namespaces')

    @property
    def k8s_api_url(self):
        return self.__get_config().get_string('k8s_api_url')

    @property
    def k8s_verify_api_queries(self):
        return self.__get_config().get_bool('k8s_verify_api_queries')

    @property
    def k8s_cache_expiry_secs(self):
        return self.__get_config().get_int('k8s_cache_expiry_secs')

    @property
    def k8s_cache_purge_secs(self):
        return self.__get_config().get_int('k8s_cache_purge_secs')

    @property
    def disable_send_requests(self):
        return self.__get_config().get_bool('disable_send_requests')

    # Debug leak flags
    @property
    def disable_monitor_threads(self):
        return self.__get_config().get_bool('disable_leak_monitor_threads')

    @property
    def disable_monitors_creation(self):
        return self.__get_config().get_bool('disable_leak_monitors_creation')

    @property
    def disable_new_file_matches(self):
        return self.__get_config().get_bool('disable_leak_new_file_matches')

    @property
    def disable_scan_for_new_bytes(self):
        return self.__get_config().get_bool('disable_leak_scan_for_new_bytes')

    @property
    def disable_processing_new_bytes(self):
        return self.__get_config().get_bool('disable_leak_processing_new_bytes')

    @property
    def disable_copying_thread(self):
        return self.__get_config().get_bool('disable_leak_copying_thread')

    @property
    def disable_overall_stats(self):
        return self.__get_config().get_bool('disable_leak_overall_stats')

    @property
    def disable_bandwidth_stats(self):
        return self.__get_config().get_bool('disable_leak_bandwidth_stats')

    @property
    def disable_update_debug_log_level(self):
        return self.__get_config().get_bool('disable_leak_update_debug_log_level')

    @property
    def disable_all_config_updates(self):
        return self.__get_config().get_int('disable_leak_all_config_updates', none_if_missing=True)

    @property
    def disable_verify_config(self):
        return self.__get_config().get_int('disable_leak_verify_config', none_if_missing=True)

    @property
    def disable_config_equivalence_check(self):
        return self.__get_config().get_int('disable_leak_config_equivalence_check', none_if_missing=True)

    @property
    def disable_verify_can_write_to_logs(self):
        return self.__get_config().get_int('disable_leak_verify_can_write_to_logs', none_if_missing=True)

    @property
    def disable_config_reload(self):
        return self.__get_config().get_int('disable_leak_config_reload', none_if_missing=True)

    @property
    def config_change_check_interval(self):
        return self.__get_config().get_float('config_change_check_interval')

    @property
    def user_agent_refresh_interval(self):
        return self.__get_config().get_float('user_agent_refresh_interval')

    @property
    def garbage_collect_interval(self):
        return self.__get_config().get_int('garbage_collect_interval')

    @property
    def disable_verify_config_create_monitors_manager(self):
        return self.__get_config().get_int('disable_leak_verify_config_create_monitors_manager', none_if_missing=True)

    @property
    def disable_verify_config_create_copying_manager(self):
        return self.__get_config().get_int('disable_leak_verify_config_create_copying_manager', none_if_missing=True)

    @property
    def disable_verify_config_cache_config(self):
        return self.__get_config().get_bool('disable_leak_verify_config_cache_config')

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
    def monitor_configs(self):
        """Returns the list of configuration entries for all monitores specified in the configuration file.

        Note, this does not include default monitors for the platform.  It is only monitors explicitly listed in the
        configuration file.

        @rtype list<JsonObject>"""
        return self.__monitor_configs

    @property
    def agent_data_path(self):
        """Returns the configuration value for 'agent_data_path'."""
        return self.__get_config().get_string('agent_data_path')

    @property
    def agent_log_path(self):
        """Returns the configuration value for 'agent_log_path'."""
        return self.__get_config().get_string('agent_log_path')

    @property
    def additional_monitor_module_paths(self):
        """Returns the configuration value for 'additional_monitor_module_paths'."""
        return self.__get_config().get_string('additional_monitor_module_paths')

    @property
    def api_key(self):
        """Returns the configuration value for 'api_key'."""
        return self.__get_config().get_string('api_key')

    @property
    def scalyr_server(self):
        """Returns the configuration value for 'scalyr_server'."""
        return self.__get_config().get_string('scalyr_server')

    @property
    def raw_scalyr_server(self):
        """Returns the configuration value for 'raw_scalyr_server'."""
        return self.__get_config().get_string('raw_scalyr_server')

    @property
    def check_remote_if_no_tty(self):
        """Returns the configuration value for `check_remote_if_no_tty`"""
        return self.__get_config().get_bool('check_remote_if_no_tty')

    @property
    def server_attributes(self):
        """Returns the configuration value for 'server_attributes'."""
        return self.__get_config().get_json_object('server_attributes')

    @property
    def implicit_agent_log_collection(self):
        """Returns the configuration value for 'implicit_agent_log_collection'."""
        return self.__get_config().get_bool('implicit_agent_log_collection')

    @property
    def implicit_metric_monitor(self):
        """Returns the configuration value for 'implicit_metric_monitor'."""
        return self.__get_config().get_bool('implicit_metric_monitor')

    @property
    def implicit_agent_process_metrics_monitor(self):
        """Returns the configuration value for 'implicit_agent_process_metrics_monitor'."""
        return self.__get_config().get_bool('implicit_agent_process_metrics_monitor')

    @property
    def use_unsafe_debugging(self):
        """Returns the configuration value for 'unsafe_debugging'.

        Note, this should be used with extreme care.  It allows arbitrary commands to be executed by any local
        user on the system as the user running the agent."""
        return self.__get_config().get_bool('use_unsafe_debugging')

    @property
    def copying_thread_profile_interval(self):
        """Returns the interval (in seconds) between outputs of the profiling for the copying thread.
        This should be zero unless you are profiling the copying thread.
        """
        return self.__get_config().get_int('copying_thread_profile_interval')

    @property
    def copying_thread_profile_output_path(self):
        """Returns the path prefix for writing all profiling dumps for the copying thread, when
        ``copying_thread_profile_interval`` is greater than zero.
        @return:
        @rtype:
        """
        return self.__get_config().get_string('copying_thread_profile_output_path')

    @property
    def config_directory(self):
        """Returns the configuration value for 'config_directory', resolved to full path if necessary."""
        config_directory = self.__get_config().get_string('config_directory')

        # The configuration directory's path is relative to the the directory this configuration
        # file is stored in.
        return self.__resolve_absolute_path(config_directory, self.__get_parent_directory(self.__file_path))

    @property
    def config_directory_raw(self):
        """Returns the configuration value for 'config_directory', as recorded in the configuration file."""
        return self.__get_config().get_string('config_directory')

    @property
    def max_allowed_request_size(self):
        """Returns the configuration value for 'max_allowed_request_size'."""
        return self.__get_config().get_int('max_allowed_request_size')

    @property
    def min_allowed_request_size(self):
        """Returns the configuration value for 'min_allowed_request_size'."""
        return self.__get_config().get_int('min_allowed_request_size')

    @property
    def min_request_spacing_interval(self):
        """Returns the configuration value for 'min_request_spacing_interval'."""
        return self.__get_config().get_float('min_request_spacing_interval')

    @property
    def max_request_spacing_interval(self):
        """Returns the configuration value for 'max_request_spacing_interval'."""
        return self.__get_config().get_float('max_request_spacing_interval')

    @property
    def max_error_request_spacing_interval(self):
        """Returns the configuration value for 'max_error_request_spacing_interval'."""
        return self.__get_config().get_float('max_error_request_spacing_interval')

    @property
    def low_water_bytes_sent(self):
        """Returns the configuration value for 'low_water_bytes_sent'."""
        return self.__get_config().get_int('low_water_bytes_sent')

    @property
    def low_water_request_spacing_adjustment(self):
        """Returns the configuration value for 'low_water_request_spacing_adjustment'."""
        return self.__get_config().get_float('low_water_request_spacing_adjustment')

    @property
    def high_water_bytes_sent(self):
        """Returns the configuration value for 'high_water_bytes_sent'."""
        return self.__get_config().get_int('high_water_bytes_sent')

    @property
    def high_water_request_spacing_adjustment(self):
        """Returns the configuration value for 'high_water_request_spacing_adjustment'."""
        return self.__get_config().get_float('high_water_request_spacing_adjustment')

    @property
    def max_new_log_detection_time(self):
        """Returns the configuration value for 'max_new_log_detection_time'."""
        return self.__get_config().get_float('max_new_log_detection_time')

    @property
    def failure_request_spacing_adjustment(self):
        """Returns the configuration value for 'failure_request_spacing_adjustment'."""
        return self.__get_config().get_float('failure_request_spacing_adjustment')

    @property
    def request_too_large_adjustment(self):
        """Returns the configuration value for 'request_too_large_adjustment'."""
        return self.__get_config().get_float('request_too_large_adjustment')

    @property
    def request_deadline(self):
        """Returns the configuration value for 'request_deadline'."""
        return self.__get_config().get_float('request_deadline')

    @property
    def debug_level(self):
        """Returns the configuration value for 'debug_level'."""
        return self.__get_config().get_int('debug_level')

    @property
    def ca_cert_path(self):
        """Returns the configuration value for 'ca_cert_path'."""
        return self.__get_config().get_string('ca_cert_path')

    @property
    def compression_type(self):
        """Returns the configuration value for 'compression_type'."""
        return self.__get_config().get_string('compression_type', none_if_missing=True)

    @property
    def compression_level(self):
        """Returns the configuration value for 'compression_level'."""
        return self.__get_config().get_int('compression_level', default_value=9)

    @property
    def use_requests_lib(self):
        """Returns the configuration value for 'use_requests_lib'."""
        return self.__get_config().get_bool('use_requests_lib')

    @property
    def network_proxies(self):
        """Returns the proxy map created by the 'https_proxy' and 'http_proxy' configuration variables, or
        None if neither of those is set.
        """
        https_proxy = self.__get_config().get_string('https_proxy', none_if_missing=True)
        http_proxy = self.__get_config().get_string('http_proxy', none_if_missing=True)
        if https_proxy is None and http_proxy is None:
            return None
        result = {}
        if https_proxy is not None:
            result['https'] = https_proxy
        if http_proxy is not None:
            result['http'] = http_proxy
        return result

    @property
    def global_monitor_sample_interval(self):
        """Returns the configuration value for 'global_monitor_sample_interval'."""
        return self.__get_config().get_float('global_monitor_sample_interval')

    @property
    def full_checkpoint_interval(self):
        """Returns the configuration value for 'full_checkpoint_interval_in_seconds'."""
        return self.__get_config().get_int('full_checkpoint_interval_in_seconds' )

    @property
    def minimum_scan_interval(self):
        """Returns the configuration value for 'minimum_scan_interval'."""
        return self.__get_config().get_int('minimum_scan_interval', none_if_missing=True )

    @property
    def close_old_files_duration_in_seconds(self):
        """Returns the configuration value for 'close_old_files_duration_in_seconds'."""
        return self.__get_config().get_int('close_old_files_duration_in_seconds')

    @property
    def max_line_size(self):
        """Returns the configuration value for 'max_line_size'."""
        return self.__get_config().get_int('max_line_size')

    @property
    def line_completion_wait_time(self):
        """Returns the configuration value for 'line_completion_wait_time'."""
        return self.__get_config().get_float('line_completion_wait_time')

    @property
    def max_log_offset_size(self):
        """Returns the configuration value for 'max_log_offset_size'."""
        return self.__get_config().get_int('max_log_offset_size')

    @property
    def max_existing_log_offset_size(self):
        """Returns the configuration value for 'max_existing_log_offset_size'."""
        return self.__get_config().get_int('max_existing_log_offset_size')

    @property
    def max_sequence_number(self):
        """Returns the maximum sequence number"""
        return self.__get_config().get_int('max_sequence_number')

    @property
    def read_page_size(self):
        """Returns the configuration value for 'read_page_size'."""
        return self.__get_config().get_int('read_page_size')

    @property
    def log_deletion_delay(self):
        """Returns the configuration value for 'log_deletion_delay'."""
        return self.__get_config().get_float('log_deletion_delay')

    @property
    def log_rotation_max_bytes(self):
        """Returns the configuration value for 'log_rotation_max_bytes'."""
        return self.__get_config().get_int('log_rotation_max_bytes')

    @property
    def log_rotation_backup_count(self):
        """Returns the configuration value for 'log_rotation_backup_count'."""
        return self.__get_config().get_int('log_rotation_backup_count')

    @property
    def copy_staleness_threshold(self):
        """Returns the configuration value for 'copy_staleness_threshold'."""
        return self.__get_config().get_float('copy_staleness_threshold')

    @property
    def debug_init(self):
        """Returns the configuration value for 'debug_init'."""
        return self.__get_config().get_bool('debug_init')

    @property
    def pidfile_advanced_reuse_guard(self):
        """Returns the configuration value for 'pidfile_advanced_reuse_guard'."""
        return self.__get_config().get_bool('pidfile_advanced_reuse_guard')

    @property
    def verify_server_certificate(self):
        """Returns the configuration value for 'verify_server_certificate'."""
        return self.__get_config().get_bool('verify_server_certificate')

    @property
    def pipeline_threshold(self):
        """Returns the percentage an add events request must be of the maximum allowed request size to
        trigger pipelining the next add events request.
        """
        return self.__get_config().get_float('pipeline_threshold')

    @property
    def strip_domain_from_default_server_host(self):
        """Returns whether or not we should remove the domain name from the default server host that is used to
        identify the source of the logs from this agent.  For example, if the hostname is `foo.scalyr.com`, setting
        this field to `true` will result in `foo` being used as the reported `serverHost` name.

        This only applies if you do not set an explicit `serverHost` attribute in the server attributes.
        """
        return self.__get_config().get_bool('strip_domain_from_default_server_host')

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
                original_debug_level = other.__config.get('debug_level')
                other.__config.put('debug_level', self.__config.get('debug_level'))

            if self.__config != other.__config:
                return False
            return True
        finally:
            if original_debug_level is not None:
                other.__config.put('debug_level', original_debug_level)

    @staticmethod
    def default_ca_cert_path():
        """Returns the default configuration file path for the agent."""
        # TODO:  Support more platforms.
        return Configuration.__resolve_to_install_location('certs', 'ca_certs.crt')

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
        if not os.path.isdir(directory_path):
            return result
        if not os.access(directory_path, os.R_OK):
            return result

        for f in sorted(os.listdir(directory_path)):
            if f.endswith('.json'):
                full_path = os.path.join(directory_path, f)
                if os.path.isfile(full_path):
                    result.append(full_path)
        return result

    def __add_elements_from_array(self, field, source_json, destination_json):
        """Appends any elements in the JsonArray in source_json to destination_json.

        @param field: The name of the field containing the JsonArray.
        @param source_json: The JsonObject containing the JsonArray from which to retrieve elements.
        @param destination_json: The JsonObject to which the elements should be added (in the JsonArray named field.
        """
        destination_array = destination_json.get_json_array(field)
        for element in source_json.get_json_array(field):
            destination_array.add(element)

    def __set_api_key( self, config, api_key ):
        """
        Sets the api_key of the config, and throws errors if there are any problems
        """
        if api_key:
            config.put( 'api_key', api_key )

        if not 'api_key' in config:
            raise BadConfiguration('The configuration file is missing the required field "api_key" that '
                                   'sets the authentication key to use when writing logs to Scalyr.  Please update '
                                   'the config file with a Write Logs key from https://www.scalyr.com/keys',
                                   'api_key', 'missingApiKey')

        if config.get_string('api_key') == '':
            raise BadConfiguration('The configuration file contains an empty string for the required field '
                                   '"api_key" that sets the authentication key to use when writing logs to Scalyr. '
                                   'Please update the config file with a Write Logs key from https://www.scalyr.com/keys',
                                   'api_key', 'emptyApiKey')

    def __check_field(self, field, config, file_path, previous_value=None, previous_config_file=None, error_code=None):
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
                    '"%s".  Please ensure that the "%s" value is set only once' % (file_path, field,
                                                                                   previous_config_file, field),
                    field, error_code)

            return result_key, result_file
        return previous_value, previous_config_file

    def __verify_main_config(self, config, file_path):
        self.__verify_main_config_and_apply_defaults( config, file_path, apply_defaults=False)

    def __verify_main_config_and_apply_defaults(self, config, file_path, apply_defaults=True):
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

        self.__verify_or_set_optional_string(config, 'api_key', '', description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_bool(config, 'allow_http', False, description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_bool(config, 'check_remote_if_no_tty', True, description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_attributes(config, 'server_attributes', description, apply_defaults)
        self.__verify_or_set_optional_string(config, 'agent_log_path', self.__default_paths.agent_log_path,
                                             description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_string(config, 'agent_data_path',  self.__default_paths.agent_data_path,
                                             description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_string(config, 'additional_monitor_module_paths', '', description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_string(config, 'config_directory', 'agent.d', description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_bool(config, 'implicit_agent_log_collection', True, description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_bool(config, 'implicit_metric_monitor', True, description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_bool(config, 'implicit_agent_process_metrics_monitor', True, description, apply_defaults, env_aware=True)

        self.__verify_or_set_optional_bool(config, 'use_unsafe_debugging', False, description, apply_defaults, env_aware=True)

        self.__verify_or_set_optional_int(config, 'copying_thread_profile_interval', 0, description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_string(config, 'copying_thread_profile_output_path',
                                             '/tmp/copying_thread_profiles_', description, apply_defaults, env_aware=True)

        self.__verify_or_set_optional_float(config, 'global_monitor_sample_interval', 30.0, description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_int(config, 'close_old_files_duration_in_seconds', 60*60*1, description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_int(config, 'full_checkpoint_interval_in_seconds', 60, description, apply_defaults, env_aware=True)

        self.__verify_or_set_optional_int(config, 'max_allowed_request_size', 1*1024*1024, description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_int(config, 'min_allowed_request_size', 100*1024, description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_float(config, 'min_request_spacing_interval', 1.0, description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_float(config, 'max_request_spacing_interval', 5.0, description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_float(config, 'max_error_request_spacing_interval', 30.0, description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_int(config, 'minimum_scan_interval', None, description, apply_defaults, env_aware=True)

        self.__verify_or_set_optional_int(config, 'low_water_bytes_sent', 20*1024, description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_float(config, 'low_water_request_spacing_adjustment', 1.5, description, apply_defaults, env_aware=True)

        self.__verify_or_set_optional_int(config, 'high_water_bytes_sent', 100*1024, description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_float(config, 'high_water_request_spacing_adjustment', 0.6, description, apply_defaults, env_aware=True)

        self.__verify_or_set_optional_float(config, 'failure_request_spacing_adjustment', 1.5, description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_float(config, 'request_too_large_adjustment', 0.5, description, apply_defaults, env_aware=True)

        self.__verify_or_set_optional_float(config, 'max_new_log_detection_time', 60.0, description, apply_defaults, env_aware=True)

        # These parameters are used in log_processing.py to govern how logs are copied.

        # The maximum allowed size for a line when reading from a log file.
        # We do not strictly enforce this -- some lines returned by LogFileIterator may be
        # longer than this due to some edge cases.
        self.__verify_or_set_optional_int(config, 'max_line_size', 9900, description, apply_defaults, env_aware=True)

        # The number of seconds we are willing to wait when encountering a log line at the end of a log file that does
        # not currently end in a new line (referred to as a partial line).  It could be that the full line just hasn't
        # made it all the way to disk yet.  After this time though, we will just return the bytes as a line
        self.__verify_or_set_optional_float(config, 'line_completion_wait_time', 5, description, apply_defaults, env_aware=True)

        # The maximum negative offset relative to the end of a previously unseen log the log file
        # iterator is allowed to become.  If bytes are not being read quickly enough, then
        # the iterator will automatically advance so that it is no more than this length
        # to the end of the file.  This is essentially the maximum bytes a new log file
        # is allowed to be caught up when used in copying logs to Scalyr.
        self.__verify_or_set_optional_int(config, 'max_log_offset_size', 5 * 1024 * 1024, description, apply_defaults, env_aware=True)


        # The maximum negative offset relative to the end of an existing log the log file
        # iterator is allowed to become.  If bytes are not being read quickly enough, then
        # the iterator will automatically advance so that it is no more than this length
        # to the end of the file.  This is essentially the maximum bytes an existing log file
        # is allowed to be caught up when used in copying logs to Scalyr.
        self.__verify_or_set_optional_int(config, 'max_existing_log_offset_size', 100 * 1024 * 1024, description, apply_defaults, env_aware=True)

        # The maximum sequence number for a given sequence
        # The sequence number is typically the total number of bytes read from a given file
        # (across restarts and log rotations), and it resets to zero (and begins a new sequence)
        # for each file once the current sequence_number exceeds this value
        # defaults to 1 TB
        self.__verify_or_set_optional_int(config, 'max_sequence_number', 1024**4, description, apply_defaults, env_aware=True)

        # The number of bytes to read from a file at a time into the buffer.  This must
        # always be greater than the MAX_LINE_SIZE
        self.__verify_or_set_optional_int(config, 'read_page_size', 64 * 1024, description, apply_defaults, env_aware=True)

        # The minimum time we wait for a log file to reappear on a file system after it has been removed before
        # we consider it deleted.
        self.__verify_or_set_optional_float(config, 'log_deletion_delay', 10 * 60, description, apply_defaults, env_aware=True)

        # How many log rotations to do
        self.__verify_or_set_optional_int(config, 'log_rotation_backup_count', 2, description, apply_defaults, env_aware=True)

        # The size of each log rotation file
        self.__verify_or_set_optional_int(config, 'log_rotation_max_bytes', 20 * 1024 * 1024, description, apply_defaults, env_aware=True)

        # The percentage of the maximum message size a message (max_allowed_request_size) has to be to trigger
        # pipelining the next add events request.  This intentionally set to 110% to prevent it from being used unless
        # explicitly requested.
        self.__verify_or_set_optional_float(config, 'pipeline_threshold', 1.1, description, apply_defaults, env_aware=True)

        # If we have noticed that new bytes have appeared in a file but we do not read them before this threshold
        # is exceeded, then we consider those bytes to be stale and just skip to reading from the end to get the
        # freshest bytes.
        self.__verify_or_set_optional_float(config, 'copy_staleness_threshold', 15 * 60, description, apply_defaults, env_aware=True)

        self.__verify_or_set_optional_bool(config, 'debug_init', False, description, apply_defaults, env_aware=True)

        self.__verify_or_set_optional_bool(config, 'pidfile_advanced_reuse_guard', False, description, apply_defaults, env_aware=True)

        self.__verify_or_set_optional_bool(config, 'strip_domain_from_default_server_host', False, description, apply_defaults, env_aware=True)

        self.__verify_or_set_optional_int(config, 'debug_level', 0, description, apply_defaults, env_aware=True)
        debug_level = config.get_int('debug_level', apply_defaults)
        if debug_level < 0 or debug_level > 5:
            raise BadConfiguration('The debug level must be between 0 and 5 inclusive', 'debug_level', 'badDebugLevel')
        self.__verify_or_set_optional_float(config, 'request_deadline', 60.0, description, apply_defaults, env_aware=True)

        self.__verify_or_set_optional_string(config, 'ca_cert_path', Configuration.default_ca_cert_path(),
                                             description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_bool(config, 'use_requests_lib', False, description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_bool(config, 'verify_server_certificate', True, description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_string(config, 'http_proxy', None, description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_string(config, 'https_proxy', None, description, apply_defaults, env_aware=True)


        self.__verify_or_set_optional_string(config, 'k8s_ignore_namespaces', 'kube-system', description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_string(config, 'k8s_api_url', 'https://kubernetes.default', description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_bool(config, 'k8s_verify_api_queries', True, description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_int(config, 'k8s_cache_expiry_secs', 30, description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_int(config, 'k8s_cache_purge_secs', 300, description, apply_defaults, env_aware=True)

        self.__verify_or_set_optional_bool(config, 'disable_send_requests', False, description, apply_defaults, env_aware=True)

        #Debug leak flags
        self.__verify_or_set_optional_bool(config, 'disable_leak_monitor_threads', False, description, apply_defaults)
        self.__verify_or_set_optional_bool(config, 'disable_leak_monitors_creation', False, description, apply_defaults)
        self.__verify_or_set_optional_bool(config, 'disable_leak_new_file_matches', False, description, apply_defaults)
        self.__verify_or_set_optional_bool(config, 'disable_leak_scan_for_new_bytes', False, description, apply_defaults)
        self.__verify_or_set_optional_bool(config, 'disable_leak_processing_new_bytes', False, description, apply_defaults)
        self.__verify_or_set_optional_bool(config, 'disable_leak_copying_thread', False, description, apply_defaults)
        self.__verify_or_set_optional_bool(config, 'disable_leak_overall_stats', False, description, apply_defaults)
        self.__verify_or_set_optional_bool(config, 'disable_leak_bandwidth_stats', False, description, apply_defaults)
        self.__verify_or_set_optional_bool(config, 'disable_leak_update_debug_log_level', False, description, apply_defaults)

        self.__verify_or_set_optional_int(config, 'disable_leak_all_config_updates', None, description, apply_defaults)
        self.__verify_or_set_optional_int(config, 'disable_leak_verify_config', None, description, apply_defaults)
        self.__verify_or_set_optional_int(config, 'disable_leak_config_equivalence_check', None, description, apply_defaults)
        self.__verify_or_set_optional_int(config, 'disable_leak_verify_can_write_to_logs', None, description, apply_defaults)
        self.__verify_or_set_optional_int(config, 'disable_leak_config_reload', None, description, apply_defaults)

        self.__verify_or_set_optional_float(config, 'config_change_check_interval', 30, description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_int(config, 'user_agent_refresh_interval', 60, description, apply_defaults, env_aware=True)
        self.__verify_or_set_optional_int(config, 'garbage_collect_interval', 300, description, apply_defaults, env_aware=True)

        self.__verify_or_set_optional_int(config, 'disable_leak_verify_config_create_monitors_manager', None, description, apply_defaults)
        self.__verify_or_set_optional_int(config, 'disable_leak_verify_config_create_copying_manager', None, description, apply_defaults)
        self.__verify_or_set_optional_bool(config, 'disable_leak_verify_config_cache_config', False, description, apply_defaults)

    def __get_config_or_environment_val(self, config_object, param_name, param_type, env_aware, custom_env_name):
        """Returns a type-converted config param value or if not found, a matching environment value.

        If the environment value is returned, it is also written into the config_object.

        Currently only handles the following types (str, int, bool, float, JsonObject, JsonArray).
        Also validates that environment variables can be correctly converted into the primitive type.

        Both upper-case and lower-case versions of the environment variable will be checked.

        @param config_object: The JsonObject config containing the field as a key
        @param param_name: Parameter name
        @param param_type: Parameter primitive type
        @param env_aware: If True and not defined in config file, look for presence of environment variable.
        @param custom_env_name: If provided, will use this name to lookup the environment variable.  Otherwise, use
            scalyr_<field> as the environment variable name. Both upper and lower case versions are tried.
            Note: A non-empty value also automatically implies env_aware as True, regardless of it's value.

        @return A python object representing the config param (or environment) value or None
        @raises
            JsonConversionException: if the config value or env value cannot be correctly converted.
            TypeError: if the param_type is not supported.
        """
        if param_type == int:
            config_val = config_object.get_int(param_name, none_if_missing=True)
        elif param_type == bool:
            config_val = config_object.get_bool(param_name, none_if_missing=True)
        elif param_type == float:
            config_val = config_object.get_float(param_name, none_if_missing=True)
        elif param_type == str:
            config_val = config_object.get_string(param_name, none_if_missing=True)
        elif param_type == JsonObject:
            config_val = config_object.get_json_object(param_name, none_if_missing=True)
        elif param_type == JsonArray:
            config_val = config_object.get_json_array(param_name, none_if_missing=True)
        elif param_type == ArrayOfStrings:
            # ArrayOfStrings are extracted from config file as JsonArray
            # (but extracted from the environment different from JsonArray)
            config_val = config_object.get_json_array(param_name, none_if_missing=True)
        else:
            raise TypeError('Unsupported environment variable conversion type %s (param name = %s)'
                            % (param_type, param_name))

        if not env_aware:
            if not custom_env_name:
                return config_val

        self._environment_aware_map[param_name] = custom_env_name or ('SCALYR_%s' % param_name.upper())

        env_val = get_config_from_env(
            param_name,
            custom_env_name=custom_env_name,
            convert_to=param_type,
            logger=self.__logger,
            param_val=config_val,
        )

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
        self.__verify_or_set_optional_array(config, 'logs', description)
        self.__verify_or_set_optional_array(config, 'monitors', description)

        i = 0
        for log_entry in config.get_json_array('logs'):
            self.__verify_log_entry_and_set_defaults(log_entry, config_file_path=file_path, entry_index=i)
            i += 1

        i = 0
        for monitor_entry in config.get_json_array('monitors'):
            self.__verify_monitor_entry_and_set_defaults(monitor_entry, file_path=file_path, entry_index=i)
            i += 1

    def __verify_log_entry_and_set_defaults(self, log_entry, description=None, config_file_path=None, entry_index=None):
        """Verifies that the configuration for the specified log meets all the required criteria and sets any defaults.

        Raises an exception if it does not.

        @param log_entry: The JsonObject holding the configuration for a log.
        @param description: A human-readable description of where the log entry came from to use in error messages. If
            none is given, then both file_path and entry_index must be set.
        @param config_file_path: The path for the file from where the configuration was read. Used to generate the
            description if none was given.
        @param entry_index: The index of the entry in the 'logs' json array. Used to generate the description if none
            was given.
        """
        # Verify it has a path entry that is a string.
        no_description_given = description is None
        if no_description_given:
            description = 'the entry with index=%i in the "logs" array in configuration file "%s"' % (entry_index,
                                                                                                      config_file_path)
        self.__verify_required_string(log_entry, 'path', description)
        # Make sure the path is absolute.
        path = log_entry.get_string('path')
        if not os.path.isabs(path):
            log_entry.put('path', os.path.join(self.agent_log_path, path))

        if no_description_given:
            description = 'the entry for "%s" in the "logs" array in configuration file "%s"' % (path, config_file_path)

        self.__verify_or_set_optional_array_of_strings( log_entry, 'exclude', description )

        # If a parser was specified, make sure it is a string.
        if 'parser' in log_entry:
            self.__verify_or_set_optional_string(log_entry, 'parser', 'ignored', description)

        self.__verify_or_set_optional_attributes(log_entry, 'attributes', description)

        self.__verify_or_set_optional_array( log_entry, 'lineGroupers', description )
        i = 0
        for element in log_entry.get_json_array('lineGroupers'):
            element_description = 'the entry with index=%i in the "lineGroupers" array in ' % i
            element_description += description

            self.__verify_required_string(element, 'start', element_description)
            self.__verify_contains_exactly_one_string_out_of( element, [ 'continueThrough', 'continuePast', 'haltBefore', 'haltWith' ], description )
            i += 1

        self.__verify_or_set_optional_bool(log_entry, 'copy_from_start', False, description)
        self.__verify_or_set_optional_bool(log_entry, 'parse_lines_as_json', False, description)
        self.__verify_or_set_optional_string(log_entry, 'json_message_field', 'log', description)
        self.__verify_or_set_optional_string(log_entry, 'json_timestamp_field', 'time', description)

        self.__verify_or_set_optional_bool(log_entry, 'ignore_stale_files', False, description)
        self.__verify_or_set_optional_float(log_entry, 'staleness_threshold_secs', 5*60, description)

        self.__verify_or_set_optional_int(log_entry, 'minimum_scan_interval', None, description)

        # Verify that if it has a sampling_rules array, then it is an array of json objects.
        self.__verify_or_set_optional_array(log_entry, 'sampling_rules', description)
        i = 0
        for element in log_entry.get_json_array('sampling_rules'):
            element_description = 'the entry with index=%i in the "sampling_rules" array in ' % i
            element_description += description
            self.__verify_required_regexp(element, 'match_expression', element_description)
            self.__verify_required_percentage(element, 'sampling_rate', element_description)
            i += 1

        # Verify that if it has a redaction_rules array, then it is an array of json objects.
        self.__verify_or_set_optional_array(log_entry, 'redaction_rules', description)
        i = 0
        for element in log_entry.get_json_array('redaction_rules'):
            element_description = 'the entry with index=%i in the "redaction_rules" array in ' % i
            element_description += description

            self.__verify_required_regexp(element, 'match_expression', element_description)
            self.__verify_or_set_optional_string(element, 'replacement', '', element_description)
            i += 1

        # We support the parser definition being at the top-level of the log config object, but we really need to
        # put it in the attributes.
        if 'parser' in log_entry:
            # noinspection PyTypeChecker
            log_entry['attributes']['parser'] = log_entry['parser']

    def __verify_monitor_entry_and_set_defaults(self, monitor_entry, context_description=None,
                                                file_path=None, entry_index=None):
        """Verifies that the config for the specified monitor meets all the required criteria and sets any defaults.

        Raises an exception if it does not.

        @param monitor_entry: The JsonObject holding the configuration for a monitor.
        @param file_path: The path for the file from where the configuration was read. Used to report errors to user.
        @param entry_index: The index of the entry in the 'monitors' json array. Used to report errors to user.
        """
        # Verify that it has a module name
        if context_description is None:
            description = 'the entry with index=%i in the "monitors" array in configuration file "%s"' % (entry_index,
                                                                                                          file_path)
        else:
            description = context_description

        self.__verify_required_string(monitor_entry, 'module', description)

        module_name = monitor_entry.get_string('module')

        if context_description is None:
            description = 'the entry for module "%s" in the "monitors" array in configuration file "%s"' % (module_name,
                                                                                                            file_path)
        else:
            description = context_description

        # Verify that if it has a log_name field, it is a string.
        self.__verify_or_set_optional_string(monitor_entry, 'log_path', module_name + '.log', description)

    def __merge_server_attributes(self, fragment_file_path, config_fragment, config):
        """Merges the contents of the server attribute read from a configuration fragment to the main config object.

        @param fragment_file_path: The path of the file from which the fragment was read. Used for error messages.
        @param config_fragment: The JsonObject in the fragment file containing the 'server_attributes' field.
        @param config: The main config object also containing a server_attributes field. The contents of the one from
            config_fragment will be merged into this one.
        """
        self.__verify_or_set_optional_attributes(config_fragment, 'server_attributes',
                                                 'the configuration fragment at "%s"' % fragment_file_path)
        source = config_fragment['server_attributes']
        destination = config['server_attributes']
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
            raise BadConfiguration('The field "%s" is not a string.  Error is in %s' % (field, config_description),
                                   field, 'notString')
        except JsonMissingFieldException:
            raise BadConfiguration('The required field "%s" is missing.  Error is in %s' % (field, config_description),
                                   field, 'missingRequired')

    def __verify_contains_exactly_one_string_out_of(self, config_object, fields, config_description):
        """Verifies that config_object has exactly one of the named fields and it can be converted to a string.

        Raises an exception otherwise.

        @param config_object: The JsonObject containing the configuration information.
        @param fields: A list of field names to check in the config_object.
        @param config_description: A description of where the configuration object was sourced from to be used in the
            error reporting to the user.
        """
        count = 0
        for field in fields:
            try:
                value = config_object.get_string(field, none_if_missing=True)
                if value is not None:
                    count += 1
            except JsonConversionException:
                raise BadConfiguration('The field "%s" is not a string.  Error is in %s' % (field, config_description),
                                       field, 'notString')
        if count == 0:
            raise BadConfiguration('A required field is missing.  Object must contain one of "%s".  Error is in %s' % (str(fields), config_description),
                                   field, 'missingRequired')
        elif count > 1:
            raise BadConfiguration('A required field has too many options.  Object must contain only one of "%s".  Error is in %s' % (str(fields), config_description),
                                   field, 'missingRequired')

    def __verify_or_set_optional_string(self, config_object, field, default_value, config_description,
                                        apply_defaults=True, env_aware=False, env_name=None):
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
        """
        try:
            value = self.__get_config_or_environment_val(config_object, field, str, env_aware, env_name)

            if value is None:
                if apply_defaults:
                    config_object.put(field, default_value)
                return

        except JsonConversionException:
            raise BadConfiguration('The value for field "%s" is not a string.  Error is in %s' % (field,
                                                                                                  config_description),
                                   field, 'notString')

    def __verify_or_set_optional_int(self, config_object, field, default_value, config_description,
                                     apply_defaults=True, env_aware=False, env_name=None):
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
        """
        try:
            value = self.__get_config_or_environment_val(config_object, field, int, env_aware, env_name)

            if value is None:
                if apply_defaults:
                    config_object.put(field, default_value)
                return

        except JsonConversionException:
            raise BadConfiguration('The value for field "%s" is not an int.  Error is in %s' % (field,
                                                                                                config_description),
                                   field, 'notInt')

    def __verify_or_set_optional_float(self, config_object, field, default_value, config_description,
                                       apply_defaults=True, env_aware=False, env_name=None):
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
        """
        try:
            value = self.__get_config_or_environment_val(config_object, field, float, env_aware, env_name)

            if value is None:
                if apply_defaults:
                    config_object.put(field, default_value)
                return

        except JsonConversionException:
            raise BadConfiguration('The value for field "%s" is not an float.  Error is in %s' % (field,
                                                                                                  config_description),
                                   field, 'notFloat')

    def __verify_or_set_optional_attributes(self, config_object, field, config_description, apply_defaults=True,
                                            env_aware=False, env_name=None):
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
        """
        try:
            json_object = self.__get_config_or_environment_val(config_object, field, JsonObject, env_aware, env_name)

            if json_object is None:
                if apply_defaults:
                    config_object.put(field, JsonObject())
                return

            for key in json_object.keys():
                try:
                    json_object.get_string(key)
                except JsonConversionException:
                    raise BadConfiguration('The value for field "%s" in the json object for "%s" is not a '
                                           'string.  Error is in %s' % (key, field, config_description),
                                           field, 'notString')

        except JsonConversionException:
            raise BadConfiguration('The value for the field "%s" is not a json object.  '
                                   'Error is in %s' % (field, config_description), field, 'notJsonObject')

    def __verify_or_set_optional_bool(self, config_object, field, default_value, config_description,
                                      apply_defaults=True, env_aware=False, env_name=None):
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
        """
        try:
            value = self.__get_config_or_environment_val(config_object, field, bool, env_aware, env_name)

            if value is None:
                if apply_defaults:
                    config_object.put(field, default_value)
                return

        except JsonConversionException:
            raise BadConfiguration('The value for the required field "%s" is not a boolean.  '
                                   'Error is in %s' % (field, config_description), field, 'notBoolean')

    def __verify_or_set_optional_array(self, config_object, field, config_description, apply_defaults=True,
                                       env_aware=False, env_name=None):
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
        """
        try:
            json_array = self.__get_config_or_environment_val(config_object, field, JsonArray, env_aware, env_name)

            if json_array is None:
                if apply_defaults:
                    config_object.put(field, JsonArray())
                return

            index = 0
            for x in json_array:
                if not isinstance(x, JsonObject):
                    raise BadConfiguration('The element at index=%i is not a json object as required in the array '
                                           'field "%s (%s, %s)".  Error is in %s' % (index, field, type(x), str(x), config_description),
                                           field, 'notJsonObject')
                index += 1
        except JsonConversionException:
            raise BadConfiguration('The value for the required field "%s" is not an array.  '
                                   'Error is in %s' % (field, config_description), field, 'notJsonArray')

    def __verify_or_set_optional_array_of_strings(self, config_object, field, config_description, apply_defaults=True,
                                                  env_aware=False, env_name=None):
        """Verifies that the specified field in config_object is an array of strings if present, otherwise sets
        to empty array.

        Raises an exception if the existing field is not a json array or if any of its elements are not strings/unicode.

        @param config_object: The JsonObject containing the configuration information.
        @param field: The name of the field to check in config_object.
        @param config_description: A description of where the configuration object was sourced from to be used in the
            error reporting to the user.
        @param apply_defaults: If true, apply default values for any missing fields.  If false do not set values
            for any fields missing from the config.
        @param env_aware: If True and not defined in config file, look for presence of environment variable.
        @param env_name: If provided, will use this name to lookup the environment variable.  Otherwise, use
            scalyr_<field> as the environment variable name.
        """
        try:
            array_of_strings = self.__get_config_or_environment_val(config_object, field, ArrayOfStrings,
                                                                    env_aware, env_name)

            if array_of_strings is None:
                if apply_defaults:
                    config_object.put(field, ArrayOfStrings())
                return

            index = 0
            for x in array_of_strings:
                if not isinstance(x, basestring):
                    raise BadConfiguration('The element at index=%i is not a string or unicode object as required in the array '
                                           'field "%s".  Error is in %s' % (index, field, config_description),
                                           field, 'notStringOrUnicode')
                index += 1
        except JsonConversionException:
            raise BadConfiguration('The value for the required field "%s" is not an array.  '
                                   'Error is in %s' % (field, config_description), field, 'notJsonArray')

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
        except:
            raise BadConfiguration('The value for required field "%s" has a value that cannot be parsed as '
                                   'string regular expression (using python syntax).  '
                                   'Error is in %s' % (field, config_description), field, 'notRegexp')

        raise BadConfiguration('The required regular expression field "%s" is missing.  Error is in %s'
                               % (field, config_description), field, 'missingRequired')

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
                raise BadConfiguration('The required percentage field "%s" is missing.  Error is in %s'
                                       % (field, config_description), field, 'missingRequired')
            elif value < 0 or value > 1:
                raise BadConfiguration('The required percentage field "%s" has a value "%s" that is not a number '
                                       'between 0 and 1 inclusive.  Error is in %s' % (field, value,
                                                                                       config_description),
                                       field, 'notPercentage')

        except JsonConversionException:
            raise BadConfiguration('The required field "%s" has a value that cannot be parsed as a number between 0 '
                                   'and 1 inclusive.  Error is in %s' % (field, config_description),
                                   field, 'notNumber')

    def __get_config(self):
        if self.__last_error is not None:
            raise BadConfiguration(self.__last_error, 'fake', 'fake')
        return self.__config

    def __perform_substitutions(self, source_config):
        """Rewrites the content of the source_config to reflect the values in the `import_vars` array.

        @param source_config:  The configuration to rewrite, represented as key/value pairs.
        @type source_config: JsonObject
        """

        def import_shell_variables():
            """Creates a dict mapping variables listed in the `import_vars` field of `source_config` to their
            values from the environment.
            """
            result = dict()
            if 'import_vars' in source_config:
                for entry in source_config.get_json_array('import_vars'):
                    # Allow for an entry of the form { var: "foo", default: "bar"}
                    if isinstance(entry, JsonObject):
                        var_name = entry['var']
                        default_value = entry['default']
                    else:
                        var_name = entry
                        default_value = ''

                    if var_name in os.environ and len(os.environ[var_name]) > 0:
                        result[var_name] = os.environ[var_name]
                    else:
                        result[var_name] = default_value
            return result

        def perform_generic_substitution(value):
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

            if (value_type is str or value_type is unicode) and '$' in value:
                result = perform_str_substitution(value)
            elif isinstance(value, JsonObject):
                perform_object_substitution(value)
            elif isinstance(value, JsonArray):
                perform_array_substitution(value)
            return result

        def perform_object_substitution(object_value):
            """Performs the in-place substitution for a JsonObject.

            @param object_value: The object to perform substitutions on.
            @type object_value: JsonObject
            """
            # We collect the new values and apply them later to avoid messing up the iteration.
            new_values = {}
            for (key, value) in object_value.iteritems():
                replace_value = perform_generic_substitution(value)
                if replace_value is not None:
                    new_values[key] = replace_value

            for (key, value) in new_values.iteritems():
                object_value[key] = value

        def perform_str_substitution(str_value):
            """Performs substitutions on the given string.

            @param str_value: The input string.
            @type str_value: str or unicode
            @return: The resulting value after substitution.
            @rtype: str or unicode
            """
            result = str_value
            for (var_name, value) in substitutions.iteritems():
                result = result.replace('$%s' % var_name, value)
            return result

        def perform_array_substitution(array_value):
            """Perform substitutions on the JsonArray.

            @param array_value: The array
            @type array_value: JsonArray
            """
            for i in range(len(array_value)):
                replace_value = perform_generic_substitution(array_value[i])
                if replace_value is not None:
                    array_value[i] = replace_value

        # Actually do the work.
        substitutions = import_shell_variables()
        if len(substitutions) > 0:
            perform_object_substitution(source_config)
