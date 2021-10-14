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
# author: Steven Czerwinski <czerwin@scalyr.com>
from __future__ import unicode_literals
from __future__ import absolute_import
from __future__ import print_function

from scalyr_agent import scalyr_logging

__author__ = "czerwin@scalyr.com"

import os
import re
import sys
import tempfile
from io import open
import platform
import json

import mock
import pytest

from scalyr_agent.configuration import Configuration, BadConfiguration
from scalyr_agent.config_util import (
    parse_array_of_strings,
    convert_config_param,
    get_config_from_env,
)
from scalyr_agent.json_lib import JsonObject, JsonArray
from scalyr_agent.json_lib.objects import (
    ArrayOfStrings,
    SpaceAndCommaSeparatedArrayOfStrings,
)
from scalyr_agent.platform_controller import DefaultPaths

from scalyr_agent.test_base import ScalyrTestCase
from scalyr_agent.test_base import skipIf

from scalyr_agent.builtin_monitors.journald_utils import (
    LogConfigManager,
    JournaldLogFormatter,
)
from scalyr_agent.util import JsonReadFileException
import scalyr_agent.util as scalyr_util
from scalyr_agent.compat import os_environ_unicode

import scalyr_agent.configuration

import six
from six.moves import range
from mock import patch, Mock


class TestConfigurationBase(ScalyrTestCase):
    def setUp(self):
        super(TestConfigurationBase, self).setUp()
        self.original_os_env = dict(
            [(k, v) for k, v in six.iteritems(os_environ_unicode)]
        )
        self._config_dir = tempfile.mkdtemp()
        self._config_file = os.path.join(self._config_dir, "agent.json")
        self._config_fragments_dir = os.path.join(self._config_dir, "agent.d")
        os.makedirs(self._config_fragments_dir)
        self._extra_config_fragments_dir = tempfile.mkdtemp() + "extra"
        os.makedirs(self._extra_config_fragments_dir)
        for key in os_environ_unicode.keys():
            if "scalyr" in key.lower():
                del os.environ[key]

        self._original_win32_file = scalyr_agent.configuration.win32file

        # Patch it so tests pass on Windows
        scalyr_agent.configuration.win32file = None

    def tearDown(self):
        """Restore the pre-test os environment"""
        os.environ.clear()
        os.environ.update(self.original_os_env)

        scalyr_agent.configuration.win32file = self._original_win32_file

    def __convert_separators(self, contents):
        """Recursively converts all path values for fields in a JsonObject that end in 'path'.

        If this is a JsonArray, iterators over the elements.
        @param contents: The contents to convert in a valid Json atom (JsonObject, JsonArray, or primitive)
        @return: The passed in object.
        """
        contents_type = type(contents)
        if contents_type is dict or contents_type is JsonObject:
            for key in contents:
                value = contents[key]
                value_type = type(value)
                if key.endswith("path") and (value_type is six.text_type):
                    contents[key] = self.convert_path(contents[key])
                elif value_type in (dict, JsonObject, list, JsonArray):
                    self.__convert_separators(value)
        elif contents_type is list or contents_type is JsonArray:
            for i in range(len(contents)):
                self.__convert_separators(contents[i])
        return contents

    def _write_file_with_separator_conversion(self, contents):
        contents = scalyr_util.json_encode(
            self.__convert_separators(
                scalyr_util.json_scalyr_config_decode(contents)
            ).to_dict()
        )

        fp = open(self._config_file, "w")
        fp.write(contents)
        fp.close()

    def _write_config_fragment_file_with_separator_conversion(
        self, file_path, contents, config_dir=None
    ):
        if config_dir is None:
            config_dir = self._config_fragments_dir

        contents = scalyr_util.json_encode(
            self.__convert_separators(
                scalyr_util.json_scalyr_config_decode(contents)
            ).to_dict()
        )

        full_path = os.path.join(config_dir, file_path)

        with open(full_path, "w") as fp:
            fp.write(contents)

    def _write_raw_config_fragment_file(self, file_path, contents, config_dir=None):
        if config_dir is None:
            config_dir = self._config_fragments_dir

        full_path = os.path.join(config_dir, file_path)

        with open(full_path, "w") as fp:
            fp.write(contents)

    class LogObject(object):
        def __init__(self, config):
            self.config = config
            self.log_path = config["path"]

    class MonitorObject(object):
        def __init__(self, config):
            self.module_name = config["module"]
            self.config = config
            self.log_config = {"path": self.module_name.split(".")[-1] + ".log"}

    def _create_test_configuration_instance(self, logger=None, extra_config_dir=None):
        """Creates an instance of a Configuration file for testing.

        @return:  The test instance
        @rtype: Configuration
        """
        logger = logger or mock.Mock()

        default_paths = DefaultPaths(
            self.convert_path("/var/log/scalyr-agent-2"),
            self.convert_path("/etc/scalyr-agent-2/agent.json"),
            self.convert_path("/var/lib/scalyr-agent-2"),
        )

        if os.path.isfile(self._config_file):
            os.chmod(self._config_file, int("640", 8))

        return Configuration(
            self._config_file, default_paths, logger, extra_config_dir=extra_config_dir
        )

    # noinspection PyPep8Naming
    def assertPathEquals(self, actual_path, expected_path):
        """Similar to `assertEquals` but the expected path is converted to the underlying system's dir separators
        before comparison.

        @param actual_path:  The actual path.  This should already be using the correct separator characters.
        @param expected_path:  The expected path.  This should use `/`'s as the separator character.  It will be
            converted to this system's actual separators.

        @type actual_path: six.text_type
        @type expected_path: six.text_type
        """
        self.assertEquals(actual_path, self.convert_path(expected_path))

    def make_path(self, parent_directory, path):
        """Returns the full path created by joining path to parent_directory.

        This method is a convenience function because it allows path to use forward slashes
        to separate path components rather than the platform's separator character.

        @param parent_directory: The parent directory. This argument must use the system's separator character. This may
            be None if path is relative to the current working directory.
        @param path: The path to add to parent_directory. This should use forward slashes as the separator character,
            regardless of the platform's character.

        @return:  The path created by joining the two with using the system's separator character.
        """
        if parent_directory is None and os.path.sep == "/":
            return path

        if parent_directory is None:
            result = ""
        elif path.startswith("/"):
            result = ""
        else:
            result = parent_directory

        for path_part in path.split("/"):
            if len(path_part) > 0:
                result = os.path.join(result, path_part)

        if os.path.sep == "\\" and not result.startswith("C:\\"):
            result = "C:\\%s" % result

        return result

    def convert_path(self, path):
        """Converts the forward slashes in path to the platform's separator and returns the value.

        @param path: The path to convert. This should use forward slashes as the separator character, regardless of the
            platform's character.

        @return: The path created by converting the forward slashes to the platform's separator.
        """
        return self.make_path(None, path)


class TestConfiguration(TestConfigurationBase):
    def test_basic_case(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            logs: [ { path:"/var/log/tomcat6/access.log"} ]
          }
        """
        )
        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEquals(config.api_key, "hi there")
        self.assertPathEquals(config.agent_log_path, "/var/log/scalyr-agent-2")
        self.assertPathEquals(config.agent_data_path, "/var/lib/scalyr-agent-2")
        self.assertEquals(config.additional_monitor_module_paths, "")
        self.assertEquals(config.config_directory, self._config_fragments_dir)
        self.assertEquals(config.implicit_metric_monitor, True)
        self.assertEquals(config.implicit_agent_log_collection, True)
        self.assertFalse(config.use_unsafe_debugging)
        self.assertEquals(config.scalyr_server, "https://agent.scalyr.com")
        self.assertEquals(len(config.server_attributes), 1)
        self.assertTrue("serverHost" in config.server_attributes)

        self.assertEquals(config.global_monitor_sample_interval, 30.0)

        self.assertEquals(config.max_send_rate_enforcement, "unlimited")
        self.assertIsNone(config.parsed_max_send_rate_enforcement)
        self.assertEquals(config.disable_max_send_rate_enforcement_overrides, False)

        self.assertEquals(config.max_allowed_request_size, 5900000)
        self.assertEquals(config.min_allowed_request_size, 100 * 1024)

        self.assertEquals(config.min_request_spacing_interval, 0.0)
        self.assertEquals(config.max_request_spacing_interval, 5.0)

        self.assertEquals(config.high_water_bytes_sent, 100 * 1024)
        self.assertEquals(config.high_water_request_spacing_adjustment, 0.6)
        self.assertEquals(config.low_water_bytes_sent, 20 * 1024)
        self.assertEquals(config.low_water_request_spacing_adjustment, 1.5)

        self.assertEquals(config.failure_request_spacing_adjustment, 1.5)
        self.assertEquals(config.request_too_large_adjustment, 0.5)
        self.assertEquals(config.debug_level, 0)
        self.assertEquals(config.stdout_severity, "NOTSET")
        self.assertEquals(config.request_deadline, 60.0)

        self.assertEquals(config.enable_gc_stats, False)

        self.assertEquals(config.max_line_size, 49900)
        self.assertEquals(config.max_log_offset_size, 200000000)
        self.assertEquals(config.max_existing_log_offset_size, 200000000)
        self.assertEquals(config.max_sequence_number, 1024 ** 4)
        self.assertEquals(config.line_completion_wait_time, 5)
        self.assertEquals(config.read_page_size, 64 * 1024)
        self.assertEquals(config.internal_parse_max_line_size, config.read_page_size)
        self.assertEquals(config.copy_staleness_threshold, 15 * 60)
        self.assertEquals(config.log_deletion_delay, 10 * 60)

        self.assertEquals(config.max_new_log_detection_time, 1 * 60)

        self.assertEquals(config.copying_thread_profile_interval, 0)
        self.assertEquals(
            config.copying_thread_profile_output_path, "/tmp/copying_thread_profiles_"
        )

        self.assertTrue(config.ca_cert_path.endswith("ca_certs.crt"))
        self.assertTrue(config.verify_server_certificate)
        self.assertFalse(config.debug_init)
        self.assertFalse(config.pidfile_advanced_reuse_guard)
        self.assertFalse(config.strip_domain_from_default_server_host)

        self.assertEquals(config.pipeline_threshold, 0)

        self.assertEquals(
            config.k8s_service_account_cert,
            "/run/secrets/kubernetes.io/serviceaccount/ca.crt",
        )
        self.assertEquals(
            config.k8s_service_account_token,
            "/var/run/secrets/kubernetes.io/serviceaccount/token",
        )
        self.assertEquals(
            config.k8s_service_account_namespace,
            "/var/run/secrets/kubernetes.io/serviceaccount/namespace",
        )
        self.assertEquals(
            config.k8s_kubelet_ca_cert,
            "/run/secrets/kubernetes.io/serviceaccount/ca.crt",
        )
        self.assertEquals(
            config.k8s_verify_kubelet_queries,
            True,
        )

        self.assertEquals(len(config.log_configs), 3)
        self.assertPathEquals(
            config.log_configs[0].get_string("path"), "/var/log/tomcat6/access.log"
        )
        self.assertEquals(
            config.log_configs[0].get_json_object("attributes"), JsonObject()
        )
        self.assertEquals(
            config.log_configs[0].get_json_array("sampling_rules"), JsonArray()
        )
        self.assertEquals(
            config.log_configs[0].get_json_array("redaction_rules"), JsonArray()
        )
        self.assertPathEquals(
            config.log_configs[1].get_string("path"),
            "/var/log/scalyr-agent-2/agent.log",
        )
        self.assertPathEquals(
            config.log_configs[2].get_string("path"),
            "/var/log/scalyr-agent-2/agent-worker-session-*.log",
        )

        self.assertFalse(config.log_configs[0].get_bool("ignore_stale_files"))
        self.assertEquals(
            config.log_configs[0].get_float("staleness_threshold_secs"), 300
        )

        self.assertEquals(len(config.monitor_configs), 0)
        self.assertIsNone(config.network_proxies)

        self.assertEqual(config.healthy_max_time_since_last_copy_attempt, 60.0)

    def test_empty_config(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there"
          }
        """
        )

        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEquals(config.api_key, "hi there")
        self.assertEquals(len(config.log_configs), 2)

        self.assertPathEquals(
            config.log_configs[0].get_string("path"),
            "/var/log/scalyr-agent-2/agent.log",
        )
        self.assertPathEquals(
            config.log_configs[1].get_string("path"),
            "/var/log/scalyr-agent-2/agent-worker-session-*.log",
        )

    def test_overriding_basic_settings(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            agent_log_path: "/var/silly1",
            agent_data_path: "/var/silly2",
            additional_monitor_module_paths: "silly3",
            config_directory: "silly4",
            implicit_metric_monitor: false,
            implicit_agent_log_collection: false,
            use_unsafe_debugging: true,
            allow_http: true,
            scalyr_server: "noland.scalyr.com",
            global_monitor_sample_interval: 60.0,
            max_send_rate_enforcement: "2 MB/s",
            disable_max_send_rate_enforcement_overrides: true,
            max_allowed_request_size: 2000000,
            min_allowed_request_size: 7000,
            min_request_spacing_interval: 2.0,
            max_request_spacing_interval: 10.0,
            high_water_bytes_sent: 50000,
            low_water_bytes_sent: 5000,
            high_water_request_spacing_adjustment: 2.0,
            low_water_request_spacing_adjustment: -1.0,
            failure_request_spacing_adjustment: 2.0,
            request_too_large_adjustment: 0.75,
            debug_level: 1,
            stdout_severity: "WARN",
            request_deadline: 30.0,
            server_attributes: { region: "us-east" },
            ca_cert_path: "/var/lib/foo.pem",
            verify_server_certificate: false,
            pipeline_threshold: 0.5,
            strip_domain_from_default_server_host: true,
            max_line_size: 1024,
            max_log_offset_size: 1048576,
            max_existing_log_offset_size: 2097152,
            max_sequence_number: 1024,
            line_completion_wait_time: 120,
            read_page_size: 3072,
            internal_parse_max_line_size: 4013,
            copy_staleness_threshold: 240,
            log_deletion_delay: 300,
            debug_init: true,
            pidfile_advanced_reuse_guard: true,

            enable_gc_stats: true,

            max_new_log_detection_time: 120,

            copying_thread_profile_interval: 2,
            copying_thread_profile_output_path: "/tmp/some_profiles",

            http_proxy: "http://foo.com",
            https_proxy: "https://bar.com",

            k8s_service_account_cert: "foo_cert",
            k8s_service_account_token: "foo_token",
            k8s_service_account_namespace: "foo_namespace",
            k8s_kubelet_ca_cert: "kubelet_cert",
            k8s_verify_kubelet_queries: false,


            logs: [ { path: "/var/log/tomcat6/access.log", ignore_stale_files: true} ],
            journald_logs: [ { journald_unit: ".*", parser: "journald_catchall" } ],

            healthy_max_time_since_last_copy_attempt: 30.0
          }
        """
        )
        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEquals(config.api_key, "hi there")
        self.assertPathEquals(config.agent_log_path, os.path.join("/var/", "silly1"))
        self.assertPathEquals(config.agent_data_path, os.path.join("/var/", "silly2"))
        self.assertEquals(config.additional_monitor_module_paths, "silly3")
        self.assertEquals(
            config.config_directory, os.path.join(self._config_dir, "silly4")
        )
        self.assertEquals(config.implicit_metric_monitor, False)
        self.assertEquals(config.implicit_agent_log_collection, False)
        self.assertTrue(config.use_unsafe_debugging)
        self.assertEquals(config.scalyr_server, "noland.scalyr.com")
        self.assertEquals(len(config.server_attributes), 2)
        self.assertEquals(config.server_attributes["region"], "us-east")

        self.assertEquals(config.global_monitor_sample_interval, 60.0)

        self.assertEquals(config.max_send_rate_enforcement, "2 MB/s")
        self.assertEquals(config.parsed_max_send_rate_enforcement, 2000000)

        self.assertEquals(config.disable_max_send_rate_enforcement_overrides, True)

        self.assertEquals(config.max_allowed_request_size, 2000000)
        self.assertEquals(config.min_allowed_request_size, 7000)

        self.assertEquals(config.min_request_spacing_interval, 2.0)
        self.assertEquals(config.max_request_spacing_interval, 10.0)

        self.assertEquals(config.high_water_bytes_sent, 50000)
        self.assertEquals(config.high_water_request_spacing_adjustment, 2.0)
        self.assertEquals(config.low_water_bytes_sent, 5000)
        self.assertEquals(config.low_water_request_spacing_adjustment, -1.0)

        self.assertEquals(config.max_line_size, 1 * 1024)
        self.assertEquals(config.max_log_offset_size, 1 * 1024 * 1024)
        self.assertEquals(config.max_existing_log_offset_size, 2 * 1024 * 1024)
        self.assertEquals(config.max_sequence_number, 1 * 1024)
        self.assertEquals(config.line_completion_wait_time, 2 * 60)
        self.assertEquals(config.read_page_size, 3 * 1024)
        self.assertEquals(config.internal_parse_max_line_size, 4013)
        self.assertEquals(config.copy_staleness_threshold, 4 * 60)
        self.assertEquals(config.log_deletion_delay, 5 * 60)

        self.assertEquals(config.enable_gc_stats, True)

        self.assertEquals(config.copying_thread_profile_interval, 2)
        self.assertEquals(
            config.copying_thread_profile_output_path,
            self.convert_path("/tmp/some_profiles"),
        )

        self.assertEquals(config.max_new_log_detection_time, 2 * 60)
        self.assertTrue(config.strip_domain_from_default_server_host)

        self.assertEquals(config.pipeline_threshold, 0.5)

        self.assertEquals(config.failure_request_spacing_adjustment, 2.0)
        self.assertEquals(config.request_too_large_adjustment, 0.75)
        self.assertEquals(config.debug_level, 1)
        self.assertEquals(config.stdout_severity, "WARN")
        self.assertEquals(config.request_deadline, 30.0)
        self.assertPathEquals(config.ca_cert_path, "/var/lib/foo.pem")
        self.assertFalse(config.verify_server_certificate)
        self.assertTrue(config.debug_init)
        self.assertTrue(config.pidfile_advanced_reuse_guard)

        self.assertEquals(config.k8s_service_account_cert, "foo_cert")
        self.assertEquals(config.k8s_service_account_token, "foo_token")
        self.assertEquals(config.k8s_service_account_namespace, "foo_namespace")
        self.assertEquals(config.k8s_kubelet_ca_cert, "kubelet_cert")
        self.assertEquals(config.k8s_verify_kubelet_queries, False)

        self.assertTrue(config.log_configs[0].get_bool("ignore_stale_files"))
        self.assertEqual(
            config.network_proxies,
            {"http": "http://foo.com", "https": "https://bar.com"},
        )

        self.assertEqual(
            config.journald_log_configs[0].get_string("parser"), "journald_catchall"
        )

        self.assertEqual(config.healthy_max_time_since_last_copy_attempt, 30.0)

    def test_missing_api_key(self):
        self._write_file_with_separator_conversion(
            """ {
            logs: [ { path:"/var/log/tomcat6/access.log"} ]
          }
        """
        )

        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_force_https_no_scheme(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            scalyr_server: "agent.scalyr.com",
          }
        """
        )
        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEqual("https://agent.scalyr.com", config.scalyr_server)

    def test_force_https_http(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            scalyr_server: "http://agent.scalyr.com",
          }
        """
        )
        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEqual("https://agent.scalyr.com", config.scalyr_server)

    def test_force_https_https(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            scalyr_server: "https://agent.scalyr.com",
          }
        """
        )
        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEqual("https://agent.scalyr.com", config.scalyr_server)

    def test_force_https_leading_whitespace(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            scalyr_server: "  http://agent.scalyr.com",
          }
        """
        )
        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEqual("https://agent.scalyr.com", config.scalyr_server)

    def test_allow_http(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            allow_http: true,
            scalyr_server: "http://agent.scalyr.com",
          }
        """
        )
        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEqual("http://agent.scalyr.com", config.scalyr_server)

    def test_non_string_value(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            agent_log_path: [ "hi" ],
          }
        """
        )
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_non_json_attributes(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            server_attributes: [ "hi" ],
          }
        """
        )
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_non_string_attribute_values(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            server_attributes: { hi: [ 1 ] },
          }
        """
        )
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_non_bool_value(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            implicit_metric_monitor: [ 1 ],
          }
        """
        )
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_no_https_proxy(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            http_proxy: "http://bar.com",
          }
        """
        )
        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEqual(config.network_proxies, {"http": "http://bar.com"})

    def test_no_http_proxy(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            https_proxy: "https://bar.com",
          }
        """
        )
        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEqual(config.network_proxies, {"https": "https://bar.com"})

    @skipIf(sys.platform.startswith("win"), "Skipping test on Windows")
    @mock.patch("scalyr_agent.util.read_config_file_as_json")
    def test_parse_incorrect_file_permissions_or_owner(
        self, mock_read_config_file_as_json
    ):
        mock_read_config_file_as_json.side_effect = JsonReadFileException(
            self._config_file, "The file is not readable"
        )
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            logs: [ { path:"/var/log/tomcat6/access.log"} ]
          }
        """
        )

        config = self._create_test_configuration_instance()

        expected_msg = r'File "%s" is not readable by the current user (.*?).' % (
            re.escape(self._config_file)
        )
        self.assertRaisesRegexp(BadConfiguration, expected_msg, config.parse)

    def test_sampling_rules(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { match_expression: "INFO", sampling_rate: 0},
                                { match_expression: ".*error.*=foo", sampling_rate: 0.2 } ],
            }]
          }
        """
        )
        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(len(config.log_configs), 3)
        sampling_rules = config.log_configs[0].get_json_array("sampling_rules")
        self.assertEquals(len(sampling_rules), 2)
        self.assertEquals(
            sampling_rules.get_json_object(0).get_string("match_expression"), "INFO"
        )
        self.assertEquals(
            sampling_rules.get_json_object(0).get_float("sampling_rate"), 0
        )
        self.assertEquals(
            sampling_rules.get_json_object(1).get_string("match_expression"),
            ".*error.*=foo",
        )
        self.assertEquals(
            sampling_rules.get_json_object(1).get_float("sampling_rate"), 0.2
        )

    def test_bad_sampling_rules(self):
        # Missing match_expression.
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { sampling_rate: 0} ]
          }] }
        """
        )
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Bad regular expression.
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { match_expression: "[a", sampling_rate: 0} ]
          }] }
        """
        )
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Missing sampling.
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { match_expression: "INFO"} ]
          }] }
        """
        )
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Not number for percentage.
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { match_expression: "INFO", sampling_rate: true} ]
          }] }
        """
        )
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Bad percentage.
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { match_expression: "INFO", sampling_rate: 2.0} ]
          }] }
        """
        )
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_redaction_rules(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              redaction_rules: [ { match_expression: "password=", replacement: "password=foo"},
                                 { match_expression: "password=.*", replacement: "password=foo"},
                                 { match_expression: "password=" },
              ],
            }]
          }
        """
        )
        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(len(config.log_configs), 3)
        redaction_rules = config.log_configs[0].get_json_array("redaction_rules")
        self.assertEquals(len(redaction_rules), 3)
        self.assertEquals(
            redaction_rules.get_json_object(0).get_string("match_expression"),
            "password=",
        )
        self.assertEquals(
            redaction_rules.get_json_object(0).get_string("replacement"), "password=foo"
        )
        self.assertEquals(
            redaction_rules.get_json_object(1).get_string("match_expression"),
            "password=.*",
        )
        self.assertEquals(
            redaction_rules.get_json_object(1).get_string("replacement"), "password=foo"
        )
        self.assertEquals(
            redaction_rules.get_json_object(2).get_string("match_expression"),
            "password=",
        )
        self.assertEquals(
            redaction_rules.get_json_object(2).get_string("replacement"), ""
        )

    def test_bad_redaction_rules(self):
        # Missing match expression.
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              redaction_rules: [ { replacement: "password=foo"} ],
            }] }
        """
        )
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Match expression is not a regexp.
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              redaction_rules: [ { match_expression: "[a" } ],
            }] }
        """
        )
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Replacement is not a string.
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              redaction_rules: [ { match_expression: "a", replacement: [ true ] } ],
            }] }
        """
        )
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_configuration_directory(self):
        self._write_file_with_separator_conversion(
            """ { api_key: "hi there"
            logs: [ { path:"/var/log/tomcat6/access.log" }],
            server_attributes: {  serverHost:"foo.com" }
          }
        """
        )

        self._write_config_fragment_file_with_separator_conversion(
            "nginx.json",
            """ {
           logs: [ { path: "/var/log/nginx/access.log" } ],
           server_attributes: { webServer:"true"}
          }
        """,
        )

        self._write_config_fragment_file_with_separator_conversion(
            "apache.json",
            """ {
           logs: [ { path: "/var/log/apache/access.log" } ]
          }
        """,
        )

        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(len(config.additional_file_paths), 2)
        additional_paths = list(config.additional_file_paths)
        additional_paths.sort()
        self.assertTrue(additional_paths[0].endswith("apache.json"))
        self.assertTrue(additional_paths[1].endswith("nginx.json"))

        self.assertEquals(len(config.log_configs), 5)
        self.assertPathEquals(
            config.log_configs[0].get_string("path"), "/var/log/tomcat6/access.log"
        )
        self.assertPathEquals(
            config.log_configs[1].get_string("path"), "/var/log/apache/access.log"
        )
        self.assertPathEquals(
            config.log_configs[2].get_string("path"), "/var/log/nginx/access.log"
        )
        self.assertEquals(
            config.log_configs[0].get_json_array("sampling_rules"), JsonArray()
        )

        self.assertEquals(config.server_attributes["webServer"], "true")
        self.assertEquals(config.server_attributes["serverHost"], "foo.com")

    def test_api_key_and_scalyr_server_defined_in_config_directory(self):
        self._write_file_with_separator_conversion(
            """ {
            logs: [ { path:"/var/log/tomcat6/access.log" }],
          }
        """
        )

        self._write_config_fragment_file_with_separator_conversion(
            "nginx.json",
            """ {
           api_key: "hi there",
           scalyr_server: "foobar",
           allow_http: true,
           logs: [ { path: "/var/log/nginx/access.log" } ],
          }
        """,
        )

        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.scalyr_server, "foobar")
        self.assertEquals(config.api_key, "hi there")

    def test_bad_fields_in_configuration_directory(self):
        self._write_file_with_separator_conversion(
            """ { api_key: "hi there"
            logs: [ { path:"/var/log/tomcat6/access.log" }]
          }
        """
        )

        self._write_config_fragment_file_with_separator_conversion(
            "nginx.json",
            """ {
           api_key: "should cause an error",
           logs: [ { path: "/var/log/nginx/access.log" } ]
          }
        """,
        )

        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_multiple_scalyr_servers_in_configuration_directory(self):
        self._write_file_with_separator_conversion(
            """ { api_key: "hi there", scalyr_server: "test1",
            logs: [ { path:"/var/log/tomcat6/access.log" }]
          }
        """
        )

        self._write_config_fragment_file_with_separator_conversion(
            "nginx.json",
            """ {
           scalyr_server: "should cause an error",
           logs: [ { path: "/var/log/nginx/access.log" } ]
          }
        """,
        )

        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_ignore_non_json_files_in_config_dir(self):
        self._write_file_with_separator_conversion(
            """ { api_key: "hi there"
            logs: [ { path:"/var/log/tomcat6/access.log" }]
          }
        """
        )

        self._write_config_fragment_file_with_separator_conversion(
            "nginx",
            """ {
           logs: [ { path: "/var/log/nginx/access.log" } ]
          }
        """,
        )

        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(len(config.log_configs), 3)

    def test_extra_config_dir_absolute(self):

        self._write_file_with_separator_conversion(""" { api_key: "main-api-key" } """)
        self._write_config_fragment_file_with_separator_conversion(
            "extra.json",
            """ {
           max_line_size: 10,
          }
        """,
            config_dir=self._extra_config_fragments_dir,
        )
        config = self._create_test_configuration_instance(
            extra_config_dir=self._extra_config_fragments_dir
        )
        config.parse()
        self.assertEquals(config.api_key, "main-api-key")
        self.assertEquals(config.max_line_size, 10)

    def test_extra_config_dir_relative(self):
        self._write_file_with_separator_conversion(""" { api_key: "main-api-key" } """)
        extra_dir = os.path.join(self._config_dir, "extra")
        os.makedirs(extra_dir)
        self._write_config_fragment_file_with_separator_conversion(
            "extra.json",
            """ {
           max_line_size: 10,
          }
        """,
            config_dir=extra_dir,
        )
        config = self._create_test_configuration_instance(extra_config_dir="extra")
        config.parse()
        self.assertEquals(config.api_key, "main-api-key")
        self.assertEquals(config.max_line_size, 10)

    def test_raw_extra_config(self):
        self._write_file_with_separator_conversion(""" { api_key: "main-api-key" } """)
        extra_dir = os.path.join(self._config_dir, "extra")
        os.makedirs(extra_dir)
        self._write_config_fragment_file_with_separator_conversion(
            "extra.json",
            """ {
           max_line_size: 10,
          }
        """,
            config_dir=extra_dir,
        )
        config = self._create_test_configuration_instance(extra_config_dir="extra")
        config.parse()
        self.assertEquals(config.extra_config_directory, extra_dir)
        self.assertEquals(config.extra_config_directory_raw, "extra")

    def test_no_raw_extra_config(self):
        self._write_file_with_separator_conversion(""" { api_key: "main-api-key" } """)
        config = self._create_test_configuration_instance()
        config.parse()
        self.assertTrue(config.extra_config_directory_raw is None)

    def test_parser_specification(self):
        self._write_file_with_separator_conversion(
            """ {
            implicit_agent_log_collection: false,
            api_key: "hi there",
            logs: [ { path: "/tmp/foo.txt",
                      parser: "foo-parser"} ]
          }
        """
        )
        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEquals(len(config.log_configs), 1)
        self.assertEquals(config.log_configs[0]["attributes"]["parser"], "foo-parser")

    def test_monitors(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            monitors: [ { module: "httpPuller"} ]
          }
        """
        )
        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(len(config.monitor_configs), 1)
        self.assertEquals(len(config.log_configs), 2)
        self.assertEquals(config.monitor_configs[0].get_string("module"), "httpPuller")
        self.assertEquals(
            config.monitor_configs[0].get_string("log_path"), "httpPuller.log"
        )

        self.assertPathEquals(
            config.log_configs[0].get_string("path"),
            "/var/log/scalyr-agent-2/agent.log",
        )

    def test_parse_log_config(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there"
          }
        """
        )
        config = self._create_test_configuration_instance()
        config.parse()

        parsed_log_config = config.parse_log_config({"path": "hi.log"})

        # TODO: Existing code doesn't correctly handle paths when mixing separators
        expected_path = self.convert_path("/var/log/scalyr-agent-2/hi.log")
        self.assertEquals(parsed_log_config["path"], expected_path)

        parsed_log_config = config.parse_log_config(
            {"path": expected_path}, default_parser="foo"
        )

        self.assertEquals(parsed_log_config["attributes"]["parser"], "foo")

    def test_parse_monitor_config(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there"
          }
        """
        )

        config = self._create_test_configuration_instance()
        config.parse()

        parsed_monitor_config = config.parse_monitor_config({"module": "foo"})

        self.assertEquals(parsed_monitor_config["module"], "foo")

    def test_equivalent_configuration(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            logs: [ { path:"/var/log/tomcat6/access.log"} ]
          }
        """
        )
        config_a = self._create_test_configuration_instance()
        config_a.parse()

        config_b = self._create_test_configuration_instance()
        config_b.parse()

        self.assertTrue(config_a.equivalent(config_b))

        # Now write a new file that is slightly different.
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            logs: [ { path:"/var/log/nginx/access.log"} ]
          }
        """
        )

        config_b = self._create_test_configuration_instance()
        config_b.parse()

        self.assertFalse(config_a.equivalent(config_b))

    def test_equivalent_configuration_ignore_debug_level(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
          }
        """
        )
        config_a = self._create_test_configuration_instance()
        config_a.parse()

        # Now write a new file that is slightly different.
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            debug_level: 1,
          }
        """
        )

        config_b = self._create_test_configuration_instance()
        config_b.parse()

        # Should be not equivalent when we aren't ignoring debug_level,
        # but equivalent when we are.
        self.assertFalse(config_a.equivalent(config_b))
        self.assertEquals(config_b.debug_level, 1)

        self.assertTrue(config_a.equivalent(config_b, exclude_debug_level=True))
        self.assertEquals(config_b.debug_level, 1)

    def test_multiple_calls_to_bad_config(self):
        self._write_file_with_separator_conversion(
            """ {
            logs: [ { path:"/var/log/tomcat6/access.log"} ]
          }
        """
        )

        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        error_seen = False
        try:
            self.assertTrue(config.agent_log_path is not None)
        except BadConfiguration:
            error_seen = True

        self.assertTrue(error_seen)

    def test_substitution(self):
        self._write_file_with_separator_conversion(
            """ {
            import_vars: [ "TEST_VAR" ],
            api_key: "hi$TEST_VAR",
          }
        """
        )
        os.environ["TEST_VAR"] = "bye"
        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, "hibye")

    def test_substitution_with_default(self):
        self._write_file_with_separator_conversion(
            """ {
            import_vars: [ {var: "UNDEFINED_VAR", default: "foo" } ],
            api_key: "hi$UNDEFINED_VAR",
          }
        """
        )

        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, "hifoo")

    def test_substitution_with_unused_default(self):
        self._write_file_with_separator_conversion(
            """ {
            import_vars: [ {var: "TEST_VAR2", default: "foo" } ],
            api_key: "hi$TEST_VAR2",
          }
        """
        )

        os.environ["TEST_VAR2"] = "bar"
        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, "hibar")

    def test_substitution_with_empty_var(self):
        self._write_file_with_separator_conversion(
            """ {
            import_vars: [ {var: "TEST_VAR2", default: "foo" } ],
            api_key: "hi$TEST_VAR2",
          }
        """
        )

        os.environ["TEST_VAR2"] = ""
        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, "hifoo")

    def test_api_key_override_no_override(self):
        self._write_file_with_separator_conversion(
            """ {
            logs: [ { path:"/var/log/tomcat6/$DIR_VAR.log" }],
            api_key: "abcd1234",
          }
        """
        )

        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, "abcd1234")

    def test_api_key_override_empty_override(self):
        self._write_file_with_separator_conversion(
            """ {
            logs: [ { path:"/var/log/tomcat6/$DIR_VAR.log" }],
            api_key: "abcd1234",
          }
        """
        )
        os.environ["scalyr_api_key"] = ""

        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, "abcd1234")

    def test_api_key_overridden_by_config_file(self):
        self._write_file_with_separator_conversion(
            """ {
            logs: [ { path:"/var/log/tomcat6/$DIR_VAR.log" }],
            api_key: "abcd1234",
          }
        """
        )
        os.environ["SCALYR_API_KEY"] = "xyz"
        mock_logger = Mock()
        config = self._create_test_configuration_instance(logger=mock_logger)
        config.parse()

        self.assertEquals(config.api_key, "abcd1234")
        mock_logger.warn.assert_called_with(
            "Conflicting values detected between global config file parameter `api_key` and the environment variable "
            "`SCALYR_API_KEY`. Ignoring environment variable.",
            limit_once_per_x_secs=300,
            limit_key="config_conflict_global_api_key_SCALYR_API_KEY",
        )
        mock_logger.debug.assert_not_called()

    def test_config_readable_by_others_warning_on_parse(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "foo",
            logs: []
          }
        """
        )
        mock_logger = Mock()
        config = self._create_test_configuration_instance(logger=mock_logger)

        mock_logger.warn.assert_not_called()

        os.chmod(self._config_file, int("644", 8))
        config.parse()

        if sys.platform.startswith("win"):
            expected_permissions = "666"
        else:
            expected_permissions = "644"

        expected_msg = (
            "Config file %s is readable or writable by others "
            "(permissions=%s). Config files can contain secrets so you are strongly "
            "encouraged to change the config file permissions so it's not "
            "readable by others." % (self._config_file, expected_permissions)
        )
        mock_logger.warn.assert_called_with(
            expected_msg,
            limit_once_per_x_secs=86400,
            limit_key="config-permissions-warn-%s" % (self._config_file),
        )

    @skipIf(platform.system() == "Windows", "Skipping tests under Windows")
    def test_k8s_logs_config_option_is_configured_but_k8s_monitor_is_not(self):
        # kubernetes_monitor is not configured
        self._write_file_with_separator_conversion(
            """ {
            api_key: "foo",
            k8s_logs: [
                { "rename_logfile": "foobar.log" }
            ]
          }
        """
        )
        mock_logger = Mock()
        config = self._create_test_configuration_instance(logger=mock_logger)

        mock_logger.warn.assert_not_called()

        config.parse()

        expected_msg = (
            '"k8s_logs" config options is defined, but Kubernetes monitor is not configured / '
            "enabled. That config option applies to Kubernetes monitor so for it to have an "
            "affect, Kubernetes monitor needs to be enabled and configured"
        )
        mock_logger.warn.assert_called_with(
            expected_msg,
            limit_once_per_x_secs=86400,
            limit_key="k8s_logs_k8s_monitor_not_enabled",
        )

        # kubernetes_monitor is configured
        self._write_file_with_separator_conversion(
            """ {
            api_key: "foo",
            k8s_logs: [
                { "rename_logfile": "foobar.log" }
            ],
            monitors: [
                {
                    "module": "scalyr_agent.builtin_monitors.kubernetes_monitor",
                }
            ]
          }
        """
        )
        mock_logger = Mock()
        config = self._create_test_configuration_instance(logger=mock_logger)

        mock_logger.warn.assert_not_called()

        config.parse()
        mock_logger.warn.assert_not_called()

        # By default option is not configured so no warning should be emitted
        self._write_file_with_separator_conversion(
            """ {
            api_key: "foo",
          }
        """
        )
        mock_logger = Mock()
        config = self._create_test_configuration_instance(logger=mock_logger)

        mock_logger.warn.assert_not_called()

        config.parse()
        mock_logger.warn.assert_not_called()

    def test_api_key_use_env(self):
        self._write_file_with_separator_conversion(
            """ {
            logs: [ { path:"/var/log/tomcat6/$DIR_VAR.log" }]
          }
        """
        )
        os.environ["SCALYR_API_KEY"] = "xyz"
        mock_logger = Mock()
        config = self._create_test_configuration_instance(logger=mock_logger)
        config._check_config_file_permissions_and_warn = lambda x: x
        config.parse()

        self.assertEquals(config.api_key, "xyz")
        mock_logger.warn.assert_not_called()
        mock_logger.debug.assert_called_with(
            "Using the api key from environment variable `SCALYR_API_KEY`",
            limit_once_per_x_secs=300,
            limit_key="api_key_from_env",
        )

    def test_duplicate_api_key(self):
        self._write_file_with_separator_conversion(
            """{
            api_key: "abcd1234",
        }
        """
        )

        self._write_config_fragment_file_with_separator_conversion(
            "apikey.json",
            """{
            api_key: "abcd1234",
        }
        """,
        )

        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_environment_aware_global_params_uppercase(self):
        self._test_environment_aware_global_params(True)

    def test_environment_aware_global_params_lowercase(self):
        self._test_environment_aware_global_params(True)

    def _test_environment_aware_global_params(self, uppercase):
        """Tests config params that have environment variable overrides as follows:

        1. Ensure params are "environment variable aware" -- meaning code exists to look for corresponding environment
            variable to override with.
        2. Generate fake environment variable values and ensure they propagate to the configuration object.
             Fake value is guaranteed different from config-file (or default) value.
        3. Repeat test for lower-case environment variables (we support both fully upper or lower case).
        """
        field_types = {}

        config_file_dict = {
            "logs": [{"path": "/var/log/tomcat6/$DIR_VAR.log"}],
            "api_key": "abcd1234",
            "use_unsafe_debugging": False,
            "json_library": "auto",
            "use_multiprocess_workers": False,
        }
        self._write_file_with_separator_conversion(
            scalyr_util.json_encode(config_file_dict)
        )

        config = self._create_test_configuration_instance()

        # Parse config files once to capture all environment-aware variables in Configuration._environment_aware_map
        config.parse()
        expected_aware_fields = config._environment_aware_map

        # Currently, all environment-aware global config params are primitives.
        # (In the future, we will need to intercept the json_array, json_object, ArrayOfString methods)
        original_verify_or_set_optional_bool = (
            config._Configuration__verify_or_set_optional_bool
        )
        original_verify_or_set_optional_int = (
            config._Configuration__verify_or_set_optional_int
        )
        original_verify_or_set_optional_float = (
            config._Configuration__verify_or_set_optional_float
        )
        original_verify_or_set_optional_string = (
            config._Configuration__verify_or_set_optional_string
        )
        original_verify_or_set_optional_array_of_strings = (
            config._Configuration__verify_or_set_optional_array_of_strings
        )
        original_verify_or_set_optional_attributes = (
            config._Configuration__verify_or_set_optional_attributes
        )

        @patch.object(config, "_Configuration__verify_or_set_optional_bool")
        @patch.object(config, "_Configuration__verify_or_set_optional_int")
        @patch.object(config, "_Configuration__verify_or_set_optional_float")
        @patch.object(config, "_Configuration__verify_or_set_optional_string")
        @patch.object(config, "_Configuration__verify_or_set_optional_array_of_strings")
        @patch.object(config, "_Configuration__verify_or_set_optional_attributes")
        def patch_and_start_test(p5, p4, p3, p2, p1, p0):
            # Decorate the Configuration.__verify_or_set_optional_xxx methods as follows:
            # 1) capture fields that are environment-aware
            # 2) allow setting of the corresponding environment variable
            def capture_aware_field(field_type):
                def wrapper(*args, **kwargs):
                    field = args[1]
                    field_types[field] = field_type
                    envar_val = function_lookup["get_environment"](field)
                    if envar_val:
                        env_name = expected_aware_fields[field]
                        if not env_name:
                            env_name = "SCALYR_%s" % field
                        if uppercase:
                            env_name = env_name.upper()
                        else:
                            env_name = env_name.lower()
                        os.environ[env_name] = envar_val

                    if field_type == bool:
                        return original_verify_or_set_optional_bool(*args, **kwargs)
                    elif field_type == int:
                        return original_verify_or_set_optional_int(*args, **kwargs)
                    elif field_type == float:
                        return original_verify_or_set_optional_float(*args, **kwargs)
                    elif field_type == six.text_type:
                        return original_verify_or_set_optional_string(*args, **kwargs)
                    elif field_type == ArrayOfStrings:
                        return original_verify_or_set_optional_array_of_strings(
                            *args, **kwargs
                        )
                    elif field_type == JsonObject:
                        return original_verify_or_set_optional_attributes(
                            *args, **kwargs
                        )

                return wrapper

            p0.side_effect = capture_aware_field(bool)
            p1.side_effect = capture_aware_field(int)
            p2.side_effect = capture_aware_field(float)
            p3.side_effect = capture_aware_field(six.text_type)
            p4.side_effect = capture_aware_field(ArrayOfStrings)
            p5.side_effect = capture_aware_field(JsonObject)

            # Build the Configuration object tree, also populating the field_types lookup in the process
            # This first iteration does not set any environment variables
            def no_set_values(field):
                return None

            function_lookup = {"get_environment": no_set_values}
            config.parse()

            # ---------------------------------------------------------------------------------------------------------
            # Ensure each field can be overridden (by faking environment variables)
            # ---------------------------------------------------------------------------------------------------------

            fake_env = {}
            config_obj = config._Configuration__get_config()

            # prepare fake environment variable values that differ from existing config object
            FAKE_INT = 1234567890
            FAKE_FLOAT = 1234567.89
            FAKE_STRING = six.text_type(FAKE_INT)
            FAKE_ARRAY_OF_STRINGS = ArrayOfStrings(["s1", "s2", "s3"])
            FAKE_OBJECT = JsonObject(**{"serverHost": "foo-bar-baz.com"})

            for field in expected_aware_fields:
                field_type = field_types[field]

                if field_type == bool:
                    # fake value should be different from config-file value
                    fake_env[field] = not config_obj.get_bool(
                        field, none_if_missing=True
                    )

                elif field_type == int:
                    # special case : debug_level cannot be arbitrary. Set it to config file value + 1
                    if field == "debug_level":
                        existing_level = config_obj.get_int(field, none_if_missing=True)
                        fake_env[field] = existing_level + 1
                    # special case for win32_max_open_fds which specified minimum and maximum values
                    elif field == "win32_max_open_fds":
                        existing_value = config_obj.get_int(field, none_if_missing=True)
                        fake_env[field] = existing_value + 1
                    elif field == "compression_level":
                        fake_env[field] = 8
                    else:
                        self.assertNotEquals(
                            FAKE_INT, config_obj.get_int(field, none_if_missing=True)
                        )
                        fake_env[field] = FAKE_INT

                elif field_type == float:
                    self.assertNotEquals(
                        FAKE_FLOAT, config_obj.get_float(field, none_if_missing=True)
                    )
                    fake_env[field] = FAKE_FLOAT

                elif field_type == six.text_type:
                    # Special cases for fields which can't contain arbitrary values
                    if field == "stdout_severity":
                        fake_env[field] = "WARN"
                    elif field == "compression_type":
                        fake_env[field] = "deflate"
                    elif field == "max_send_rate_enforcement":
                        fake_env[field] = "legacy"
                    else:
                        self.assertNotEquals(
                            FAKE_STRING,
                            config_obj.get_string(field, none_if_missing=True),
                        )
                        fake_env[field] = FAKE_STRING

                elif field_type == ArrayOfStrings:
                    self.assertNotEquals(
                        FAKE_ARRAY_OF_STRINGS,
                        config_obj.get_json_array(field, none_if_missing=True),
                    )
                    fake_env[field] = FAKE_ARRAY_OF_STRINGS
                elif field_type == JsonObject:
                    self.assertNotEquals(
                        FAKE_OBJECT,
                        config_obj.get_json_object(field, none_if_missing=True),
                    )
                    fake_env[field] = FAKE_OBJECT

            def fake_environment_value(field):
                if field not in fake_env:
                    return None
                fake_field_val = fake_env[field]
                if isinstance(fake_field_val, ArrayOfStrings):
                    separator = ","
                    # legacy whitespace separator support for 'k8s_ignore_namespaces'
                    if field == "k8s_ignore_namespaces":
                        separator = " "
                    result = six.text_type(
                        separator.join([x for x in fake_field_val])
                    ).lower()
                elif isinstance(fake_field_val, JsonObject):
                    result = (
                        six.text_type(fake_field_val)
                        .replace("'", '"')
                        .replace('u"', '"')
                    )
                else:
                    result = six.text_type(fake_field_val)
                return result

            function_lookup = {"get_environment": fake_environment_value}

            config.parse()
            self.assertGreater(len(expected_aware_fields), 1)
            for field, env_varname in expected_aware_fields.items():
                field_type = field_types[field]
                if field_type == bool:
                    value = config._Configuration__get_config().get_bool(field)
                elif field_type == int:
                    value = config._Configuration__get_config().get_int(field)
                elif field_type == float:
                    value = config._Configuration__get_config().get_float(field)
                elif field_type == six.text_type:
                    value = config._Configuration__get_config().get_string(field)
                elif field_type == ArrayOfStrings:
                    value = config._Configuration__get_config().get_json_array(field)
                elif field_type == JsonObject:
                    value = config._Configuration__get_config().get_json_object(field)

                config_file_value = config_file_dict.get(field)
                if field in config_file_dict:
                    # Config params defined in the config file must not take on the fake environment values.
                    self.assertNotEquals(value, fake_env[field])
                    self.assertEquals(value, config_file_value)
                else:
                    # But those not defined in config file will take on environment values.
                    self.assertEquals(value, fake_env[field])
                    self.assertNotEquals(value, config_file_value)

        patch_and_start_test()  # pylint: disable=no-value-for-parameter

    def test_log_excludes_from_config(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",
            logs: [
                {
                    path: "/var/log/tomcat6/access.log",
                    exclude: ["*.[0-9]*", "*.bak"]
                }
            ],
          }
        """
        )
        config = self._create_test_configuration_instance()
        config.parse()
        excludes = config.log_configs[0]["exclude"]
        self.assertEquals(type(excludes), JsonArray)
        self.assertEquals(list(excludes), ["*.[0-9]*", "*.bak"])

    def test_global_options_in_fragments(self):
        self._write_config_fragment_file_with_separator_conversion(
            "fragment.json",
            """{
            api_key: "abcdefg",
            agent_log_path: "/var/silly1",
            http_proxy: "http://foo.com",
            https_proxy: "https://bar.com",
        }
        """,
        )

        self._write_file_with_separator_conversion(
            """{
        }
        """
        )

        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, "abcdefg")
        self.assertEquals(config.agent_log_path, self.convert_path("/var/silly1"))
        self.assertEqual(
            config.network_proxies,
            {"http": "http://foo.com", "https": "https://bar.com"},
        )

    def test_global_duplicate_options_in_fragments(self):
        self._write_config_fragment_file_with_separator_conversion(
            "fragment.json",
            """{
            api_key: "abcdefg",
            agent_log_path: "/var/silly1",
            http_proxy: "http://foo.com",
            https_proxy: "https://bar.com",
        }
        """,
        )

        self._write_file_with_separator_conversion(
            """{
            agent_log_path: "/var/silly1",
        }
        """
        )

        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_json_array_substitution(self):
        self._write_file_with_separator_conversion(
            """ {
            import_vars: [ "TEST_VAR", "DIR_VAR" ],
            api_key: "hi$TEST_VAR",
            logs: [ { path:"/var/log/tomcat6/$DIR_VAR.log" }]
          }
        """
        )

        os.environ["TEST_VAR"] = "bye"
        os.environ["DIR_VAR"] = "ok"

        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, "hibye")
        self.assertPathEquals(
            config.log_configs[0].get_string("path"), "/var/log/tomcat6/ok.log"
        )

    def test_empty_substitution(self):
        self._write_file_with_separator_conversion(
            """ {
            import_vars: [ "UNDEFINED_VAR" ],
            api_key: "hi$UNDEFINED_VAR",
          }
        """
        )

        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, "hi")

    def test_print_config(self):
        """Make sure that when we print the config options that we
        don't throw any exceptions
        """
        self._write_file_with_separator_conversion("""{api_key: "hi there"}""")
        mock_logger = Mock()
        config = self._create_test_configuration_instance(logger=mock_logger)
        config.parse()
        config.print_useful_settings()
        mock_logger.info.assert_any_call("Configuration settings")
        mock_logger.info.assert_any_call("\tmax_line_size: 49900")

        # Verify actual API keys are masked
        self._write_file_with_separator_conversion(
            """{api_key: "hi there", workers: [{"sessions":2, "api_key": "foo1234", "id": "one"}, {"sessions":5, "api_key": "bar1234", "id": "two"}]}"""
        )  # NOQA
        mock_logger = Mock()
        config = self._create_test_configuration_instance(logger=mock_logger)
        config.parse()
        config.print_useful_settings()
        mock_logger.info.assert_any_call("Configuration settings")
        mock_logger.info.assert_any_call("\tmax_line_size: 49900")

        # NOTE: We can't use OrderedDict since we still support Python 2.6 which means we assert on
        # sorted string value
        expected_line = "\tsanitized_worker_configs: [{'sessions': 5, 'api_key': '********** MASKED **********', 'id': 'two'}, {'sessions': 2, 'api_key': '********** MASKED **********', 'id': 'one'}, {'sessions': 1, 'api_key': '********** MASKED **********', 'id': 'default'}]"  # NOQA
        logged_line = mock_logger.info.call_args_list[-1][0][0]
        self.assertEqual(sorted(expected_line), sorted(logged_line))

        (
            worker_type,
            sessions_count,
            api_keys_count,
        ) = config.get_number_of_configured_sessions_and_api_keys()
        self.assertEqual(worker_type, "threaded")
        self.assertEqual(sessions_count, 8)
        self.assertEqual(api_keys_count, 3)

    def test_print_config_when_changed(self):
        """
        Test that `print_useful_settings` only outputs changed settings when compared to another
        configuration object
        """
        self._write_file_with_separator_conversion(
            """{
            api_key: "hi there",
            max_line_size: 5,
            workers: [{"sessions":2, "api_key": "foo1234", "id": "one"}]}
            }
        """
        )
        mock_logger = Mock()
        config = self._create_test_configuration_instance(logger=mock_logger)
        config.parse()

        (
            worker_type,
            sessions_count,
            api_keys_count,
        ) = config.get_number_of_configured_sessions_and_api_keys()
        self.assertEqual(worker_type, "threaded")
        self.assertEqual(sessions_count, 3)
        self.assertEqual(api_keys_count, 2)

        self._write_file_with_separator_conversion(
            """{
            api_key: "hi there",
            max_line_size: 9900,
            workers: [{"sessions":10, "api_key": "foo1234", "id": "one"}]},
            }
        """
        )
        new_config = self._create_test_configuration_instance(logger=mock_logger)
        new_config.parse()

        (
            worker_type,
            sessions_count,
            api_keys_count,
        ) = new_config.get_number_of_configured_sessions_and_api_keys()
        self.assertEqual(worker_type, "threaded")
        self.assertEqual(sessions_count, 11)
        self.assertEqual(api_keys_count, 2)

        new_config.print_useful_settings(other_config=config)

        self.assertEqual(mock_logger.info.call_count, 3)
        mock_logger.info.assert_any_call("Configuration settings")
        mock_logger.info.assert_any_call("\tmax_line_size: 9900")

        # NOTE: We can't use OrderedDict since we still support Python 2.6 which means we assert on
        # sorted string value
        expected_line = "\tsanitized_worker_configs: [{'sessions': 10, 'api_key': '********** MASKED **********', 'id': 'one'}, {'sessions': 1, 'api_key': '********** MASKED **********', 'id': 'default'}]"  # NOQA
        logged_line = mock_logger.info.call_args_list[-1][0][0]
        self.assertEqual(sorted(expected_line), sorted(logged_line))

    def test_print_config_when_not_changed(self):
        """
        Test that `print_useful_settings` doesn't output anything if configuration
        options haven't changed
        """
        self._write_file_with_separator_conversion(
            """{
            api_key: "hi there",
            max_line_size: 49900
            }
        """
        )
        mock_logger = Mock()
        config = self._create_test_configuration_instance(logger=mock_logger)
        config.parse()

        other_config = self._create_test_configuration_instance(logger=mock_logger)
        other_config.parse()

        config.print_useful_settings(other_config=other_config)
        mock_logger.info.assert_not_called()

    def test_print_config_raw_config_value_debug_level_off(self):
        # default value (debug_level not explicitly specified)
        self._write_file_with_separator_conversion(
            """{
            api_key: "hi there",
            max_line_size: 49900,
            workers: [{"workers":2, "api_key": "foo1234", "id": "one"}]}
            }
        """
        )
        mock_logger = Mock()
        config = self._create_test_configuration_instance(logger=mock_logger)
        config.parse()

        other_config = self._create_test_configuration_instance(logger=mock_logger)
        other_config.parse()

        config.print_useful_settings(other_config=other_config)
        mock_logger.info.assert_not_called()

        # debug_level specifies, but the value is < 5
        for level in range(0, 4):
            self._write_file_with_separator_conversion(
                """{
                api_key: "hi there",
                max_line_size: 49900,
                debug_level: %s,
                }
            """
                % (level)
            )
            mock_logger = Mock()
            config = self._create_test_configuration_instance(logger=mock_logger)
            config.parse()

            other_config = self._create_test_configuration_instance(logger=mock_logger)
            other_config.parse()

            config.print_useful_settings(other_config=other_config)
            mock_logger.info.assert_not_called()

    def test_print_config_raw_config_value_debug_level_5(self):
        self._write_file_with_separator_conversion(
            """{
            api_key: "hi there",
            max_line_size: 49900,
            debug_level: 5,
            workers: [{"sessions":2, "api_key": "foo1234", "id": "one"}]}
            }
        """
        )

        mock_logger = Mock()
        config = self._create_test_configuration_instance(logger=mock_logger)
        config.parse()

        other_config = self._create_test_configuration_instance(logger=mock_logger)
        other_config.parse()

        self.assertEqual(mock_logger.info.call_count, 0)
        config.print_useful_settings(other_config=other_config)
        self.assertEqual(mock_logger.info.call_count, 1)

        call_msg = mock_logger.info.call_args_list[0][0][0]
        self.assertTrue("Raw config value:" in call_msg)
        self.assertTrue("*** MASKED ***" in call_msg)
        self.assertTrue('"debug_level": 5' in call_msg)
        self.assertTrue('"api_key": "********** MASKED **********"' in call_msg)
        self.assertTrue("foo1234" not in call_msg)

    def test_import_vars_in_configuration_directory(self):
        os.environ["TEST_VAR"] = "bye"
        self._write_file_with_separator_conversion(
            """ { api_key: "hi there"
            logs: [ { path:"/var/log/tomcat6/access.log" }],
            server_attributes: {  serverHost:"foo.com" }
          }
        """
        )

        self._write_config_fragment_file_with_separator_conversion(
            "nginx.json",
            """ {
           import_vars: [ "TEST_VAR" ],
           logs: [ { path: "/var/log/nginx/$TEST_VAR.log" } ],
           server_attributes: { webServer:"true"}
          }
        """,
        )

        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(len(config.additional_file_paths), 1)
        additional_paths = list(config.additional_file_paths)
        additional_paths.sort()
        self.assertTrue(additional_paths[0].endswith("nginx.json"))

        self.assertEquals(len(config.log_configs), 4)
        self.assertPathEquals(
            config.log_configs[0].get_string("path"), "/var/log/tomcat6/access.log"
        )
        self.assertPathEquals(
            config.log_configs[1].get_string("path"), "/var/log/nginx/bye.log"
        )
        self.assertEquals(
            config.log_configs[0].get_json_array("sampling_rules"), JsonArray()
        )

        self.assertEquals(config.server_attributes["webServer"], "true")
        self.assertEquals(config.server_attributes["serverHost"], "foo.com")

    @skipIf(platform.system() != "Windows", "Skipping tests on non-Windows platform")
    def test_print_config_windows(self):
        import win32file  # pylint: disable=import-error

        scalyr_agent.configuration.win32file = win32file

        mock_logger = Mock()
        maxstdio = win32file._getmaxstdio()

        self._write_file_with_separator_conversion(
            """{
            api_key: "hi there",
            }
        """
        )

        config = self._create_test_configuration_instance(logger=mock_logger)
        config.parse()
        self.assertEqual(mock_logger.info.call_count, 0)

        config.print_useful_settings()
        mock_logger.info.assert_any_call("Configuration settings")
        mock_logger.info.assert_any_call(
            "\twin32_max_open_fds(maxstdio): %s (%s)" % (maxstdio, maxstdio)
        )

        mock_logger.reset_mock()
        self.assertEqual(mock_logger.info.call_count, 0)

        # If the value has not changed, the line should not be printed
        config.print_useful_settings(other_config=config)
        self.assertEqual(mock_logger.info.call_count, 0)

    @skipIf(platform.system() == "Windows", "Skipping tests on Windows")
    @mock.patch("scalyr_agent.util.read_config_file_as_json")
    def test_parse_invalid_config_file_permissions(self, mock_read_config_file_as_json):
        # User-friendly exception should be thrown on some config permission related errors
        error_msgs = [
            "File is not readable",
            "Error reading file",
            "Failed while reading",
        ]

        for error_msg in error_msgs:
            mock_read_config_file_as_json.side_effect = Exception(error_msg)

            config = self._create_test_configuration_instance()

            expected_msg = re.compile(
                r".*not readable by the current user.*Original error.*%s.*"
                % (error_msg),
                re.DOTALL,
            )
            self.assertRaisesRegexp(BadConfiguration, expected_msg, config.parse)

    @skipIf(sys.version_info < (2, 7, 0), "Skipping tests under Python 2.6")
    def test_set_json_library_on_apply_config(self):
        current_json_lib = scalyr_util.get_json_lib()
        self.assertEqual(current_json_lib, "json")

        self._write_file_with_separator_conversion(
            """{
             api_key: "hi there",
            json_library: "json"
          }
        """
        )

        config = self._create_test_configuration_instance()
        config.parse()
        config.apply_config()

        new_json_lib = scalyr_util.get_json_lib()
        self.assertEqual(new_json_lib, "json")

        # auth should fall back to ujson again
        self._write_file_with_separator_conversion(
            """{
             api_key: "hi there",
            json_library: "ujson"
          }
        """
        )

        config = self._create_test_configuration_instance()
        config.parse()
        config.apply_config()

        new_json_lib = scalyr_util.get_json_lib()
        self.assertEqual(new_json_lib, "ujson")

    @skipIf(sys.version_info < (2, 7, 0), "Skipping tests under Python 2.6")
    def test_apply_config_without_parse(self):
        config = self._create_test_configuration_instance()
        config.apply_config()

    def test_parse_valid_compression_type(self):
        # Valid values
        for compression_type in scalyr_util.SUPPORTED_COMPRESSION_ALGORITHMS:
            self._write_file_with_separator_conversion(
                """{
                api_key: "hi there",
                compression_type: "%s",
            }
            """
                % (compression_type)
            )

            config = self._create_test_configuration_instance()
            config.parse()
            self.assertEqual(config.compression_type, compression_type)

    def test_parse_unsupported_compression_type(self):
        # Invalid value
        self._write_file_with_separator_conversion(
            """{
                api_key: "hi there",
                compression_type: "invalid",
            }
            """
        )

        config = self._create_test_configuration_instance()
        expected_msg = 'Got invalid value "invalid" for field "compression_type"'
        self.assertRaisesRegexp(BadConfiguration, expected_msg, config.parse)

    @mock.patch(
        "scalyr_agent.util.get_compress_and_decompress_func",
        mock.Mock(side_effect=ImportError("")),
    )
    def test_parse_library_for_specified_compression_type_not_available(self):
        self._write_file_with_separator_conversion(
            """{
                api_key: "hi there",
                compression_type: "deflate",
            }
            """
        )

        config = self._create_test_configuration_instance()
        expected_msg = (
            ".*Make sure that the corresponding Python library is available.*"
        )
        self.assertRaisesRegexp(BadConfiguration, expected_msg, config.parse)

    def test_parse_compression_algorithm_specific_default_value_is_used_for_level(self):
        for compression_type in scalyr_util.SUPPORTED_COMPRESSION_ALGORITHMS:
            default_level = scalyr_util.COMPRESSION_TYPE_TO_DEFAULT_LEVEL[
                compression_type
            ]

            self._write_file_with_separator_conversion(
                """{
                    api_key: "hi there",
                    compression_type: "%s",
                }
                """
                % (compression_type)
            )

            config = self._create_test_configuration_instance()
            config.parse()
            self.assertEqual(config.compression_level, default_level)

            # Explicitly provided value by the user should always have precedence
            self._write_file_with_separator_conversion(
                """{
                    api_key: "hi there",
                    compression_type: "%s",
                    "compression_level": 5,
                }
                """
                % (compression_type)
            )

            config = self._create_test_configuration_instance()
            config.parse()

            if config.compression_type == "none":
                self.assertEqual(config.compression_level, 0)
            else:
                self.assertEqual(config.compression_level, 5)

    def test_parse_compression_algorithm_invalid_compression_level(self):
        # If invalid compression level is used, we should use a default value for that particular
        # algorithm. That's in place for backward compatibility reasons.
        for compression_type in scalyr_util.SUPPORTED_COMPRESSION_ALGORITHMS:
            default_level = scalyr_util.COMPRESSION_TYPE_TO_DEFAULT_LEVEL[
                compression_type
            ]

            (
                valid_level_min,
                valid_level_max,
            ) = scalyr_util.COMPRESSION_TYPE_TO_VALID_LEVELS[compression_type]

            # Value is lower than the min value
            self._write_file_with_separator_conversion(
                """{
                    api_key: "hi there",
                    compression_type: "%s",
                    compression_level: "%s",
                }
                """
                % (compression_type, (valid_level_min - 1))
            )

            config = self._create_test_configuration_instance()
            config.parse()

            msg = "Expected %s for algorithm %s" % (default_level, compression_type)
            self.assertEqual(config.compression_level, default_level, msg)

            # Value is greater than the min value
            self._write_file_with_separator_conversion(
                """{
                    api_key: "hi there",
                    compression_type: "%s",
                    compression_level: "%s",
                }
                """
                % (compression_type, (valid_level_max + 1))
            )

            config = self._create_test_configuration_instance()
            config.parse()

            msg = "Expected %s for algorithm %s" % (default_level, compression_type)
            self.assertEqual(config.compression_level, default_level, msg)

            # Value is min value (valid since we use inclusive range)
            self._write_file_with_separator_conversion(
                """{
                    api_key: "hi there",
                    compression_type: "%s",
                    compression_level: "%s",
                }
                """
                % (compression_type, (valid_level_min))
            )

            config = self._create_test_configuration_instance()
            config.parse()

            msg = "Expected %s for algorithm %s" % (valid_level_min, compression_type)
            self.assertEqual(config.compression_level, valid_level_min, msg)

            # Value is max value (valid since we use inclusive range)
            self._write_file_with_separator_conversion(
                """{
                    api_key: "hi there",
                    compression_type: "%s",
                    compression_level: "%s",
                }
                """
                % (compression_type, (valid_level_max))
            )

            config = self._create_test_configuration_instance()
            config.parse()

            msg = "Expected %s for algorithm %s" % (valid_level_max, compression_type)
            self.assertEqual(config.compression_level, valid_level_max, msg)

    def test_deprecated_param_names(self):
        self._write_file_with_separator_conversion(
            """{
                api_key: "hi there",
                "api_keys": [
                    {
                        "api_key": "key",
                        "id": "my_key",
                        "workers": 4
                    }
                ],
                "default_workers_per_api_key": 2,
                "use_multiprocess_copying_workers": false
            }
            """
        )

        config = self._create_test_configuration_instance()
        config.parse()

        # "api_keys" should become "worker_configs"
        assert config.worker_configs == [
            # "workers" field in workers entry should become "sessions"
            JsonObject(api_key="hi there", id="default", sessions=2),
            JsonObject(api_key="key", id="my_key", sessions=4),
        ]
        # "default_workers_per_api_key" should become "default_sessions_per_worker"
        assert config.default_sessions_per_worker == 2

        # verify a false deprecated option.
        assert config.use_multiprocess_workers is False

    def test_deprecated_env_aware_params(self):
        os_environ_unicode["SCALYR_DEFAULT_WORKERS_PER_API_KEY"] = "5"

        self._write_file_with_separator_conversion(
            """{
                api_key: "hi there",
            }
            """
        )

        config = self._create_test_configuration_instance()
        config.parse()

        assert config.default_sessions_per_worker == 5

    def test_deprecated_params_in_config_fragment(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there"

            api_keys: [
                {"api_key": "key2", "id": "second_key"},
                {"api_key": "key3", "id": "third_key", "workers": 3}
            ]
          }
        """
        )

        self._write_config_fragment_file_with_separator_conversion(
            "a.json",
            """
            {
                api_keys: [
                    {"api_key": "key4", "id": "fourth_key", "workers": 3}
                ]

                logs: [
                    {"path": "some/path", "worker_id": "second_key"}
                ]
            }
            """,
        )

        config = self._create_test_configuration_instance()

        config.parse()

        # check if workers from fragment are added.

        assert list(config.worker_configs) == [
            JsonObject(
                api_key=config.api_key,
                id="default",
                sessions=config.default_sessions_per_worker,
            ),
            JsonObject(
                api_key="key2",
                id="second_key",
                sessions=config.default_sessions_per_worker,
            ),
            JsonObject(api_key="key3", id="third_key", sessions=3),
            JsonObject(api_key="key4", id="fourth_key", sessions=3),
        ]

    def test__verify_required_attributes(self):
        config = self._create_test_configuration_instance()

        # 1. Field is not a JSON object
        config_object = JsonObject({"field1": "a"})
        field = "field1"

        self.assertRaisesRegexp(
            BadConfiguration,
            "is not a json object",
            config._Configuration__verify_required_attributes,
            config_object=config_object,
            field=field,
            config_description="",
        )
        # 2. Field is not a JSON object
        config_object = JsonObject({"field1": "a"})
        field = "field2"

        config._Configuration__verify_required_attributes(
            config_object=config_object, field=field, config_description=""
        )

        # 3. Field is an object
        config_object = JsonObject({"field1": JsonObject({})})
        field = "field1"

        config._Configuration__verify_required_attributes(
            config_object=config_object, field=field, config_description=""
        )

        # 4. Field is an object, one field value can't be cast to string
        config_object = JsonObject({"field1": JsonObject({"foo": JsonArray([])})})
        field = "field1"

        self.assertRaisesRegexp(
            BadConfiguration,
            "is not a string",
            config._Configuration__verify_required_attributes,
            config_object=config_object,
            field=field,
            config_description="",
        )


class TestParseArrayOfStrings(TestConfigurationBase):
    def test_none(self):
        self.assertIsNone(parse_array_of_strings(None))

    def test_empty_string(self):
        self.assertEqual(parse_array_of_strings(""), ArrayOfStrings())

    def test_list(self):
        self.assertEqual(
            parse_array_of_strings("a, b, c"), ArrayOfStrings(["a", "b", "c"])
        )


class TestConvertConfigParam(TestConfigurationBase):
    def test_none_to_anything(self):
        """ """
        self.assertRaises(
            BadConfiguration,
            lambda: convert_config_param("dummy_field", None, six.text_type),
        )
        self.assertRaises(
            BadConfiguration, lambda: convert_config_param("dummy_field", None, bool)
        )
        self.assertRaises(
            BadConfiguration, lambda: convert_config_param("dummy_field", None, int)
        )
        self.assertRaises(
            BadConfiguration, lambda: convert_config_param("dummy_field", None, float)
        )
        self.assertRaises(
            BadConfiguration, lambda: convert_config_param("dummy_field", None, list)
        )
        self.assertRaises(
            BadConfiguration,
            lambda: convert_config_param("dummy_field", None, JsonArray),
        )
        self.assertRaises(
            BadConfiguration,
            lambda: convert_config_param("dummy_field", None, JsonObject),
        )
        self.assertRaises(
            BadConfiguration,
            lambda: convert_config_param("dummy_field", None, ArrayOfStrings),
        )

    def test_empty_string(self):
        self.assertEqual("", convert_config_param("dummy_field", "", six.text_type))
        self.assertEqual(False, convert_config_param("dummy_field", "", bool))
        self.assertRaises(
            BadConfiguration, lambda: convert_config_param("dummy_field", "", int)
        )
        self.assertRaises(
            BadConfiguration, lambda: convert_config_param("dummy_field", "", float)
        )
        self.assertEqual(
            ArrayOfStrings(), convert_config_param("dummy_field", "", ArrayOfStrings)
        )
        self.assertEqual(
            ArrayOfStrings(),
            convert_config_param(
                "dummy_field", "", SpaceAndCommaSeparatedArrayOfStrings
            ),
        )
        self.assertRaises(
            IndexError, lambda: convert_config_param("dummy_field", "", JsonArray)
        )
        self.assertRaises(
            IndexError, lambda: convert_config_param("dummy_field", "", JsonArray)
        )

    def test_convert_to_float(self):
        self.assertEqual(5.0, convert_config_param("dummy_field", "5.0", float))
        self.assertEqual(5.0, convert_config_param("dummy_field", 5.0, float))
        self.assertEqual(5.0, convert_config_param("dummy_field", 5, float))
        self.assertEqual(2.1, convert_config_param("dummy_field", "2.1", float))
        self.assertEqual(2.1, convert_config_param("dummy_field", 2.1, float))


class TestGetConfigFromEnv(TestConfigurationBase):
    def test_get_empty_array_of_string(self):
        os.environ["SCALYR_K8S_IGNORE_NAMESPACES"] = ""
        self.assertEqual(
            ArrayOfStrings(),
            get_config_from_env(
                "k8s_ignore_namespaces", convert_to=SpaceAndCommaSeparatedArrayOfStrings
            ),
        )

        os.environ["SCALYR_K8S_IGNORE_NAMESPACES"] = "a, b, c"
        self.assertEqual(
            ArrayOfStrings(["a", "b", "c"]),
            get_config_from_env(
                "k8s_ignore_namespaces", convert_to=SpaceAndCommaSeparatedArrayOfStrings
            ),
        )

        del os.environ["SCALYR_K8S_IGNORE_NAMESPACES"]
        self.assertIsNone(
            get_config_from_env(
                "k8s_ignore_namespaces", convert_to=SpaceAndCommaSeparatedArrayOfStrings
            )
        )

    def test_get_empty_string(self):
        os.environ["SCALYR_K8S_API_URL"] = ""
        self.assertEqual(
            "", get_config_from_env("k8s_api_url", convert_to=six.text_type)
        )

        del os.environ["SCALYR_K8S_API_URL"]
        self.assertIsNone(get_config_from_env("k8s_api_url", convert_to=six.text_type))

    def test_get_empty_json_object(self):
        os.environ["SCALYR_SERVER_ATTRIBUTES"] = ""
        self.assertEqual(
            JsonObject(content={}),
            get_config_from_env("server_attributes", convert_to=JsonObject),
        )

        del os.environ["SCALYR_SERVER_ATTRIBUTES"]
        self.assertEqual(
            None,
            get_config_from_env("server_attributes", convert_to=JsonObject),
        )
        os.environ["SCALYR_SERVER_ATTRIBUTES"] = '{"serverHost": "foo1.example.com"}'
        self.assertEqual(
            JsonObject(content={"serverHost": "foo1.example.com"}),
            get_config_from_env("server_attributes", convert_to=JsonObject),
        )

        os.environ[
            "SCALYR_SERVER_ATTRIBUTES"
        ] = '{"serverHost": "foo1.example.com", "tier": "foo"}'
        self.assertEqual(
            JsonObject(content={"serverHost": "foo1.example.com", "tier": "foo"}),
            get_config_from_env("server_attributes", convert_to=JsonObject),
        )

        os.environ[
            "SCALYR_SERVER_ATTRIBUTES"
        ] = '{"serverHost": "foo1.example.com", "tier": "foo", "bar": "baz"}'
        self.assertEqual(
            JsonObject(
                content={"serverHost": "foo1.example.com", "tier": "foo", "bar": "baz"}
            ),
            get_config_from_env("server_attributes", convert_to=JsonObject),
        )


class FakeLogWatcher:
    def add_log_config(self, a, b):
        pass


class TestJournaldLogConfigManager(TestConfigurationBase):
    def setUp(self):
        super(TestJournaldLogConfigManager, self).setUp()
        self._temp_dir = tempfile.mkdtemp()
        self._log_dir = os.path.join(self._temp_dir, "log")
        os.makedirs(self._log_dir)

    def get_configuration(self):
        default_paths = DefaultPaths(
            self.convert_path(self._log_dir),
            self.convert_path("/etc/scalyr-agent-2/agent.json"),
            self.convert_path("/var/lib/scalyr-agent-2"),
        )
        return Configuration(self._config_file, default_paths, None)

    def get_configuration_with_logger(self):
        default_paths = DefaultPaths(
            self.convert_path(self._log_dir),
            self.convert_path("/etc/scalyr-agent-2/agent.json"),
            self.convert_path("/var/lib/scalyr-agent-2"),
        )
        return Configuration(
            self._config_file, default_paths, scalyr_logging.AgentLogger("config_test")
        )

    def test_default_config(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi",
                journald_logs: [ ]
            }
            """
        )
        config = self.get_configuration()
        config.parse()

        lcm = LogConfigManager(config, None)
        matched_config = lcm.get_config("test")
        self.assertEqual("journald", matched_config["parser"])
        matched_config = lcm.get_config("other_test")
        self.assertEqual("journald", matched_config["parser"])

    def test_catchall_config(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi",
                journald_logs: [ { journald_unit: ".*", parser: "TestParser" } ]
            }
            """
        )
        config = self.get_configuration()
        config.parse()

        lcm = LogConfigManager(config, None)
        matched_config = lcm.get_config("test")
        self.assertEqual("TestParser", matched_config["parser"])
        matched_config = lcm.get_config("other_test")
        self.assertEqual("TestParser", matched_config["parser"])

    def test_specific_config(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi",
                journald_logs: [ { journald_unit: "test", parser: "TestParser" } ]
            }
            """
        )
        config = self.get_configuration()
        config.parse()

        lcm = LogConfigManager(config, None)
        matched_config = lcm.get_config("test")
        self.assertEqual("TestParser", matched_config["parser"])
        matched_config = lcm.get_config("other_test")
        self.assertEqual("journald", matched_config["parser"])

    def test_multiple_configs(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi",
                journald_logs: [
                    { journald_unit: "test", parser: "TestParser" },
                    { journald_unit: "confirm", parser: "ConfirmParser" }
                ]
            }
            """
        )
        config = self.get_configuration()
        config.parse()

        lcm = LogConfigManager(config, None)
        matched_config = lcm.get_config("test")
        self.assertEqual("TestParser", matched_config["parser"])
        matched_config = lcm.get_config("other_test")
        self.assertEqual("journald", matched_config["parser"])
        matched_config = lcm.get_config("confirm")
        self.assertEqual("ConfirmParser", matched_config["parser"])

    def test_regex_config(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi",
                journald_logs: [
                    { journald_unit: "test.*test", parser: "TestParser" }
                ]
            }
            """
        )
        config = self.get_configuration()
        config.parse()

        lcm = LogConfigManager(config, None)
        matched_config = lcm.get_config("testtest")
        self.assertEqual("TestParser", matched_config["parser"])
        matched_config = lcm.get_config("other_test")
        self.assertEqual("journald", matched_config["parser"])
        matched_config = lcm.get_config("test_somethingarbitrary:test")
        self.assertEqual("TestParser", matched_config["parser"])

    def test_glob_config(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi",
                journald_logs: [
                    { journald_globs: { "unit": "test*test" }, parser: "TestParser" }
                ]
            }
            """
        )
        config = self.get_configuration()
        config.parse()

        lcm = LogConfigManager(config, None)
        matched_config = lcm.get_config({"unit": "testtest"})
        self.assertEqual("TestParser", matched_config["parser"])
        matched_config = lcm.get_config({"unit": "other_test"})
        self.assertEqual("journald", matched_config["parser"])
        matched_config = lcm.get_config({"unit": "test_somethingarbitrary:test"})
        self.assertEqual("TestParser", matched_config["parser"])

    def test_multiple_glob_config(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi",
                journald_logs: [
                    { journald_globs: { "unit": "test*test", "container": "f?obar" }, parser: "TestParser" }
                ]
            }
            """
        )
        config = self.get_configuration()
        config.parse()

        lcm = LogConfigManager(config, None)
        # test matches both
        matched_config = lcm.get_config({"unit": "testtest", "container": "frobar"})
        self.assertEqual("TestParser", matched_config["parser"])

        # test when matches one glob but not the other
        matched_config = lcm.get_config({"unit": "testtest", "container": "foobaz"})
        self.assertNotEqual("TestParser", matched_config["parser"])
        self.assertEqual("journald", matched_config["parser"])

        # test when matches one glob, but other one missing
        matched_config = lcm.get_config({"unit": "test_other_test"})
        self.assertNotEqual("TestParser", matched_config["parser"])
        self.assertEqual("journald", matched_config["parser"])

        # no matches, should use default parser
        matched_config = lcm.get_config({"unit": "bar", "container": "bar"})
        self.assertEqual("journald", matched_config["parser"])

    def test_unit_regex_and_globs_both_defined(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi",
                journald_logs: [
                    { journald_globs: { "baz": "test*test", "container": "f?obar" }, parser: "TestParser", journald_unit: "scalyr" }
                ]
            }
            """
        )
        config = self.get_configuration()
        config.parse()

        # self.assertRaises( BadMonitorConfiguration,
        self.assertRaises(BadConfiguration, lambda: LogConfigManager(config, None))

    def test_big_config(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi",
                journald_logs: [
                    {
                        journald_unit: "test",
                        parser: "TestParser",
                        redaction_rules: [ { match_expression: "a", replacement: "yes" } ],
                        sampling_rules: [ { match_expression: "INFO", sampling_rate: 0.1} ],
                        attributes: {
                            webServer: "true"
                        }
                    }
                ]
            }
            """
        )
        config = self.get_configuration()
        config.parse()

        lcm = LogConfigManager(config, None)
        matched_config = lcm.get_config("test")

        # NOTE: We need to sort the values since we can't rely on dict ordering
        expected = [{"match_expression": "a", "replacement": "yes"}]
        expected[0] = sorted(expected[0].items())

        actual = list(matched_config["redaction_rules"])
        actual[0] = sorted(actual[0].items())
        self.assertEqual(expected, actual)

        expected = [{"match_expression": "INFO", "sampling_rate": 0.1}]
        expected[0] = sorted(expected[0].items())

        actual = list(matched_config["sampling_rules"])
        actual[0] = sorted(actual[0].items())
        self.assertEqual(expected, actual)
        self.assertEqual("true", matched_config["attributes"]["webServer"])

    def test_default_logger(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi",
                journald_logs: [
                ]
            }
            """
        )
        config = self.get_configuration()
        config.parse()

        lcm = LogConfigManager(config, JournaldLogFormatter())
        lcm.set_log_watcher(FakeLogWatcher())
        logger = lcm.get_logger("test")
        logger.info("Find this string")

        expected_path = os.path.join(
            self._log_dir,
            "journald_monitor.log",
        )
        with open(expected_path) as f:
            self.assertTrue("Find this string" in f.read())

    def test_modified_default_logger(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi",
                journald_logs: [ { journald_unit: ".*", parser: "TestParser" } ]
            }
            """
        )
        config = self.get_configuration()
        config.parse()

        lcm = LogConfigManager(config, JournaldLogFormatter())
        lcm.set_log_watcher(FakeLogWatcher())
        logger = lcm.get_logger("test")
        logger.info("Find this string")

        expected_path = os.path.join(
            self._log_dir,
            "journald_monitor.log",
        )
        with open(expected_path) as f:
            self.assertTrue("Find this string" in f.read())

    def test_specific_logger(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi",
                journald_logs: [ { journald_unit: "TEST", parser: "TestParser" } ]
            }
            """
        )
        config = self.get_configuration()
        config.parse()

        lcm = LogConfigManager(config, JournaldLogFormatter())
        lcm.set_log_watcher(FakeLogWatcher())
        logger = lcm.get_logger("TEST")
        logger.info("Find this string")
        logger2 = lcm.get_logger("Other")
        logger2.info("Other thing")

        expected_path = os.path.join(
            self._log_dir,
            "journald_" + six.text_type(hash("TEST")) + ".log",
        )
        with open(expected_path) as f:
            self.assertTrue("Find this string" in f.read())

        expected_path = os.path.join(
            self._log_dir,
            "journald_monitor.log",
        )
        with open(expected_path) as f:
            self.assertTrue("Other thing" in f.read())

    def test_regex_logger(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi",
                journald_logs: [ { journald_unit: "test.*test", parser: "TestParser" } ]
            }
            """
        )
        config = self.get_configuration()
        config.parse()

        lcm = LogConfigManager(config, JournaldLogFormatter())
        lcm.set_log_watcher(FakeLogWatcher())
        logger = lcm.get_logger("testestestestestest")
        logger.info("Find this string")
        logger2 = lcm.get_logger("Other")
        logger2.info("Other thing")

        expected_path = os.path.join(
            self._log_dir,
            "journald_" + six.text_type(hash("test.*test")) + ".log",
        )
        with open(expected_path) as f:
            self.assertTrue("Find this string" in f.read())

        expected_path = os.path.join(
            self._log_dir,
            "journald_monitor.log",
        )
        with open(expected_path) as f:
            self.assertTrue("Other thing" in f.read())

    def test__verify_or_set_optional_int_with_min_and_max_value(self):
        config = self._create_test_configuration_instance()

        # 1. Valid value1
        config_object = JsonObject(content={"foo": 10})
        config._Configuration__verify_or_set_optional_int(
            config_object=config_object,
            field="foo",
            default_value=None,
            config_description=None,
            min_value=10,
            max_value=100,
        )
        self.assertEqual(config_object["foo"], 10)

        config_object = JsonObject(content={"foo": 50})
        config._Configuration__verify_or_set_optional_int(
            config_object=config_object,
            field="foo",
            default_value=None,
            config_description=None,
            min_value=10,
            max_value=100,
        )
        self.assertEqual(config_object["foo"], 50)

        config_object = JsonObject(content={"foo": 100})
        config._Configuration__verify_or_set_optional_int(
            config_object=config_object,
            field="foo",
            default_value=None,
            config_description=None,
            min_value=10,
            max_value=100,
        )
        self.assertEqual(config_object["foo"], 100)

        # 2. value < min
        config_object = JsonObject(content={"foo": 9})
        expected_msg = 'Got invalid value "9" for field "foo". Value must be greater than or equal to 10'

        self.assertRaisesRegexp(
            BadConfiguration,
            expected_msg,
            config._Configuration__verify_or_set_optional_int,
            config_object=config_object,
            field="foo",
            default_value=None,
            config_description=None,
            min_value=10,
            max_value=100,
        )

        # 3. value > max
        config_object = JsonObject(content={"foo": 101})
        expected_msg = 'Got invalid value "101" for field "foo". Value must be less than or equal to 100'

        self.assertRaisesRegexp(
            BadConfiguration,
            expected_msg,
            config._Configuration__verify_or_set_optional_int,
            config_object=config_object,
            field="foo",
            default_value=None,
            config_description=None,
            min_value=10,
            max_value=100,
        )

    def test___verify_or_set_optional_string_with_valid_values(self):
        config = self._create_test_configuration_instance()

        # 1. Valid value
        config_object = JsonObject(content={"foo": "bar"})
        config._Configuration__verify_or_set_optional_string(
            config_object=config_object,
            field="foo",
            default_value=None,
            config_description=None,
            valid_values=["bar", "baz"],
        )
        self.assertEqual(config_object["foo"], "bar")

        # 2. Not a valid value
        config_object = JsonObject(content={"foo": "invalid"})
        expected_msg = (
            'Got invalid value "invalid" for field "foo". Valid values are: bar, baz'
        )

        self.assertRaisesRegexp(
            BadConfiguration,
            expected_msg,
            config._Configuration__verify_or_set_optional_string,
            config_object=config_object,
            field="foo",
            default_value=None,
            config_description=None,
            valid_values=["bar", "baz"],
        )

    def test_max_send_rate_enforcement_legacy_defaults(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi",
                max_send_rate_enforcement: "legacy"
            }
            """
        )
        config = self.get_configuration()
        config.parse()

        self.assertEquals(config.max_send_rate_enforcement, "legacy")
        self.assertIsNone(config.parsed_max_send_rate_enforcement)

        self.assertEquals(config.max_allowed_request_size, 1048576)
        self.assertEquals(config.pipeline_threshold, 1.1)
        self.assertEquals(config.min_request_spacing_interval, 1.0)
        self.assertEquals(config.max_request_spacing_interval, 5.0)
        self.assertEquals(config.max_log_offset_size, 5242880)
        self.assertEquals(config.max_existing_log_offset_size, 104857600)

    def test_disable_max_send_rate_enforcement_overrides(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi",
                disable_max_send_rate_enforcement_overrides: true
            }
            """
        )
        config = self.get_configuration()
        config.parse()

        self.assertEquals(config.max_send_rate_enforcement, "unlimited")
        self.assertIsNone(config.parsed_max_send_rate_enforcement)

        self.assertEquals(config.max_allowed_request_size, 1048576)
        self.assertEquals(config.pipeline_threshold, 1.1)
        self.assertEquals(config.min_request_spacing_interval, 1.0)
        self.assertEquals(config.max_request_spacing_interval, 5.0)
        self.assertEquals(config.max_log_offset_size, 5242880)
        self.assertEquals(config.max_existing_log_offset_size, 104857600)

    def test_max_send_rate_enforcement_overrides(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi",
                max_allowed_request_size: 1234,
                pipeline_threshold: 0.3,
                min_request_spacing_interval: 3.0,
                max_request_spacing_interval: 4.0,
                max_log_offset_size: 1234,
                max_existing_log_offset_size: 1234
            }
            """
        )
        config = self.get_configuration_with_logger()
        config.parse()

        self.assertEquals(config.max_send_rate_enforcement, "unlimited")
        self.assertIsNone(config.parsed_max_send_rate_enforcement)

        self.assertEquals(config.max_allowed_request_size, 5900000)
        self.assertEquals(config.pipeline_threshold, 0)
        self.assertEquals(config.min_request_spacing_interval, 0.0)
        self.assertEquals(config.max_request_spacing_interval, 5.0)
        self.assertEquals(config.max_log_offset_size, 200000000)
        self.assertEquals(config.max_existing_log_offset_size, 200000000)

    def test_max_send_rate_enforcement_legacy_dont_override(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi",
                max_send_rate_enforcement: "legacy",
                max_allowed_request_size: 1234,
                pipeline_threshold: 0.3,
                min_request_spacing_interval: 3.0,
                max_request_spacing_interval: 4.0,
                max_log_offset_size: 1234,
                max_existing_log_offset_size: 1234
            }
            """
        )
        config = self.get_configuration_with_logger()
        config.parse()

        self.assertEquals(config.max_send_rate_enforcement, "legacy")
        self.assertIsNone(config.parsed_max_send_rate_enforcement)

        self.assertEquals(config.max_allowed_request_size, 1234)
        self.assertEquals(config.pipeline_threshold, 0.3)
        self.assertEquals(config.min_request_spacing_interval, 3.0)
        self.assertEquals(config.max_request_spacing_interval, 4.0)
        self.assertEquals(config.max_log_offset_size, 1234)
        self.assertEquals(config.max_existing_log_offset_size, 1234)

    def test_win32_max_open_fds(self):
        # 1. default value
        self._write_file_with_separator_conversion(
            """ {
                api_key: "foo",
            }
            """
        )
        config = self.get_configuration_with_logger()
        config.parse()

        self.assertEquals(config.win32_max_open_fds, 512)

        # 2. overwritten value
        self._write_file_with_separator_conversion(
            """ {
                api_key: "foo",
                win32_max_open_fds: 1024
            }
            """
        )
        config = self.get_configuration_with_logger()
        config.parse()

        self.assertEquals(config.win32_max_open_fds, 1024)


class TestWorkersConfiguration(TestConfigurationBase):
    def test_no_workers_entry_(self):
        # The 'workers' list does not exist, a default api_key entry should be created.
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there"
          }
        """
        )
        config = self._create_test_configuration_instance()

        config.parse()

        # only defaults are created.
        assert len(config.worker_configs) == 1
        assert config.worker_configs[0] == JsonObject(
            api_key=config.api_key,
            id="default",
            sessions=config.default_sessions_per_worker,
        )

    def test_empty_workers_entry(self):
        """
        Does not make so much sense, but still a valid case to apply a default worker.
        :return:
        """
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi there"
                workers: [

                ]
              }
            """
        )

        config = self._create_test_configuration_instance()
        config.parse()

        assert len(config.worker_configs) == 1
        api_key = config.worker_configs[0]

        assert api_key == JsonObject(
            api_key=config.api_key,
            id="default",
            sessions=config.default_sessions_per_worker,
        )

        (
            worker_type,
            sessions_count,
            api_keys_count,
        ) = config.get_number_of_configured_sessions_and_api_keys()
        self.assertEqual(worker_type, "threaded")
        self.assertEqual(sessions_count, 1)
        self.assertEqual(api_keys_count, 1)

    def test_overwrite_default_workers(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "key"
                workers: [
                    {
                        "api_key": "key", id: "default", "sessions": 4
                    }
                ]
              }
            """
        )

        config = self._create_test_configuration_instance()
        config.parse()

        assert len(config.worker_configs) == 1
        assert config.worker_configs[0] == JsonObject(
            api_key=config.api_key,
            id="default",
            sessions=4,
        )

        (
            worker_type,
            sessions_count,
            api_keys_count,
        ) = config.get_number_of_configured_sessions_and_api_keys()
        self.assertEqual(worker_type, "threaded")
        self.assertEqual(sessions_count, 4)
        self.assertEqual(api_keys_count, 1)

    def test_overwrite_default_workers_without_api_key(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "key"
                workers: [
                    {
                        id: "default", "sessions": 4
                    }
                ]
              }
            """
        )

        config = self._create_test_configuration_instance()
        config.parse()

        assert len(config.worker_configs) == 1
        assert config.worker_configs[0] == JsonObject(
            api_key=config.api_key,
            id="default",
            sessions=4,
        )

        (
            worker_type,
            sessions_count,
            api_keys_count,
        ) = config.get_number_of_configured_sessions_and_api_keys()
        self.assertEqual(worker_type, "threaded")
        self.assertEqual(sessions_count, 4)
        self.assertEqual(api_keys_count, 1)

    def test_default_workers_and_second(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi there",
                workers: [
                    {
                        "api_key": "key", "id": "second"
                    }
                ]
              }
            """
        )

        config = self._create_test_configuration_instance()

        config.parse()

        assert len(config.worker_configs) == 2
        workers = list(config.worker_configs)

        assert workers[0] == JsonObject(
            api_key=config.api_key,
            id="default",
            sessions=config.default_sessions_per_worker,
        )
        assert workers[1] == JsonObject(
            api_key="key",
            id="second",
            sessions=1,
        )

    def test_second_default_api_key(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi there",
                workers: [
                    {
                        "api_key": "key", "id": "default"
                    },
                    {
                        "api_key": "key2", "id": "default"
                    }
                ]
              }
            """
        )

        config = self._create_test_configuration_instance()

        with pytest.raises(BadConfiguration) as err_info:
            config.parse()

        assert (
            "The API key of the default worker has to match the main API key of the configuration"
            in err_info.value.message
        )

    def test_worker_id_duplication(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi there",
                workers: [
                    {
                        "api_key": "key", "id": "second"
                    },
                    {
                        "api_key": "key2", "id": "second"
                    }
                ]
              }
            """
        )
        config = self._create_test_configuration_instance()

        with pytest.raises(BadConfiguration) as err_info:
            config.parse()

        assert (
            "There are multiple workers with the same 'second' id. Worker id's must remain unique."
            in err_info.value.message
        )

    def test_api_key_field_missing(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi there",
                workers: [
                    {
                        "id": "second"
                    },
                    {
                        "api_key": "key2", "id": "third"
                    }
                ]
              }
            """
        )
        config = self._create_test_configuration_instance()

        with pytest.raises(BadConfiguration) as err_info:
            config.parse()

        assert 'The required field "api_key" is missing.' in err_info.value.message

    def test_api_key_entry_id_field_missing(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi there",
                workers: [
                    {
                        "api_key": "key"
                    },
                    {
                        "api_key": "key2", "id": "third"
                    }
                ]
              }
            """
        )
        config = self._create_test_configuration_instance()

        with pytest.raises(BadConfiguration) as err_info:
            config.parse()

        assert 'The required field "id" is missing.' in err_info.value.message

    def test_log_file_bind_to_workers_entries(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi there",
                workers: [
                    {
                        api_key: "key2"
                        "sessions": 4,
                        "id": "second",
                    }
                ],
                logs: [
                    {
                        path: "/some/path.log",
                        worker_id: "second"
                    },
                    {
                        path: "/some/path2.log",
                    }
                ]
              }
            """
        )
        config = self._create_test_configuration_instance()

        config.parse()

        assert len(config.worker_configs) == 2
        assert config.worker_configs[0] == JsonObject(
            sessions=1, api_key=config.api_key, id="default"
        )
        assert config.worker_configs[1] == JsonObject(
            sessions=4,
            api_key="key2",
            id="second",
        )

        (
            worker_type,
            sessions_count,
            api_keys_count,
        ) = config.get_number_of_configured_sessions_and_api_keys()
        self.assertEqual(worker_type, "threaded")
        self.assertEqual(sessions_count, 5)
        self.assertEqual(api_keys_count, 2)

    def test_log_file_bind_to_worker_entries_with_non_existing_id(self):
        self._write_file_with_separator_conversion(
            """ {
                api_key: "hi there",
                workers: [
                    {
                        api_key: "key2"
                        "sessions": 4,
                        "id": "second"
                    }
                ],

                logs: [
                    {
                        path: "/some/path.log",
                        worker_id: "wrong worker id"
                    },
                    {
                        path: "/some/path2.log",
                    }
                ]
              }
            """
        )
        config = self._create_test_configuration_instance()

        with pytest.raises(BadConfiguration) as err_info:
            config.parse()

        assert (
            "refers to a non-existing worker with id 'wrong worker id'."
            in err_info.value.message
        )
        assert "Valid worker ids: default, second." in err_info.value.message

    def test_workers_type_default(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there"
          }
        """
        )

        config = self._create_test_configuration_instance()

        config.parse()

        assert not config.use_multiprocess_workers

    @skipIf(platform.system() == "Windows", "Skipping tests under Windows")
    @skipIf(
        sys.version_info < (2, 7), "Skipping multiprocess configuration for python 2.6"
    )
    def test_workers_type_multiprocess(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there"
            use_multiprocess_workers: true
          }
        """
        )

        config = self._create_test_configuration_instance()

        config.parse()

        assert config.use_multiprocess_workers

        (
            worker_type,
            sessions_count,
            api_keys_count,
        ) = config.get_number_of_configured_sessions_and_api_keys()
        self.assertEqual(worker_type, "multiprocess")
        self.assertEqual(sessions_count, 1)
        self.assertEqual(api_keys_count, 1)

    @skipIf(platform.system() == "Windows", "Skipping tests under Windows")
    @skipIf(
        sys.version_info < (2, 7), "Skipping multiprocess configuration for python 2.6"
    )
    def test_workers_type_multiprocess_from_env(self):
        os_environ_unicode["SCALYR_USE_MULTIPROCESS_WORKERS"] = "True"
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there"
          }
        """
        )

        config = self._create_test_configuration_instance()

        config.parse()

        assert config.use_multiprocess_workers

    @skipIf(platform.system() != "Windows", "Skipping Linux only tests on Windows")
    @skipIf(
        sys.version_info < (2, 7), "Skipping multiprocess configuration for python 2.6"
    )
    def test_workers_type_multiprocess_windows(self):
        # 'use_multiprocess_workers' option should cause error on Windows.
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there"
            use_multiprocess_workers: true
          }
        """
        )

        config = self._create_test_configuration_instance()

        with pytest.raises(BadConfiguration) as err_info:
            config.parse()

        assert (
            "The 'use_multiprocess_workers' option is not supported on windows machines."
            in err_info.value.message
        )

    def test_default_sessions_per_worker(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there",

            workers: [
                {"api_key": "another_key", "id": "second", "sessions": 3},
                {"api_key": "another_key2", "id": "third"}
            ]
          }
        """
        )

        config = self._create_test_configuration_instance()

        config.parse()

        assert len(config.worker_configs) == 3
        assert config.worker_configs[0]["api_key"] == config.api_key
        assert (
            config.worker_configs[0]["sessions"] == config.default_sessions_per_worker
        )
        assert config.worker_configs[1]["api_key"] == "another_key"
        assert config.worker_configs[1]["sessions"] == 3
        assert config.worker_configs[2]["api_key"] == "another_key2"
        assert (
            config.worker_configs[2]["sessions"] == config.default_sessions_per_worker
        )

    def test_workers_negative_sessions_number(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there"

            workers: [
                {"api_key": "another_key", "id": "second_key"},
                {"api_key": "another_key2", "id": "third_key", "sessions": -1}
            ]
          }
        """
        )

        config = self._create_test_configuration_instance()
        with pytest.raises(BadConfiguration) as err_info:
            config.parse()

        assert "Value must be greater than or equal to 1" in err_info.value.message

        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there"
            default_sessions_per_worker: -1,
            workers: [
                {"api_key": "another_key", "id": "second_key"},
                {"api_key": "another_key2", "id": "third_key"}
            ]
          }
        """
        )

        config = self._create_test_configuration_instance()
        with pytest.raises(BadConfiguration) as err_info:
            config.parse()

        assert "Value must be greater than or equal to 1" in err_info.value.message

    def test_default_sessions_per_worker_from_env(self):
        os_environ_unicode["SCALYR_DEFAULT_SESSIONS_PER_WORKER"] = "4"
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there"
            workers: [
                {"api_key": "another_key", "id": "second_key"},
            ]
          }
        """
        )
        config = self._create_test_configuration_instance()
        config.parse()

        assert config.default_sessions_per_worker == 4

        return

    def test_config_fragment(self):
        self._write_file_with_separator_conversion(
            """ {
            api_key: "hi there"

            workers: [
                {"api_key": "key2", "id": "second_key"},
                {"api_key": "key3", "id": "third_key", "sessions": 3}
            ]
          }
        """
        )

        self._write_config_fragment_file_with_separator_conversion(
            "a.json",
            """
            {
                workers: [
                    {"api_key": "key4", "id": "fourth_key", "sessions": 3}
                ]

                logs: [
                    {"path": "some/path", "worker_id": "second_key"}
                ]
            }
            """,
        )

        config = self._create_test_configuration_instance()

        config.parse()

        # check if workers from fragment are added.

        assert list(config.worker_configs) == [
            JsonObject(
                api_key=config.api_key,
                id="default",
                sessions=config.default_sessions_per_worker,
            ),
            JsonObject(
                api_key="key2",
                id="second_key",
                sessions=config.default_sessions_per_worker,
            ),
            JsonObject(api_key="key3", id="third_key", sessions=3),
            JsonObject(api_key="key4", id="fourth_key", sessions=3),
        ]

    def test_k8s_and_journald_logs_workers(self):

        journald_log1 = {
            "journald_unit": "ssh\\.service",
        }

        main_config = {
            "api_key": "hi there",
            "workers": [
                {"api_key": "key2", "id": "second_key"},
                {"api_key": "key3", "id": "third_key", "sessions": 3},
            ],
            "logs": [
                {"path": "path1"},
                {"path": "path2", "worker_id": "second_key"},
                {"path": "path3", "worker_id": "third_key"},
            ],
            "journald_logs": [
                journald_log1,
                {"journald_unit": ".*", "worker_id": "third_key"},
            ],
        }

        k8s_config1 = {"k8s_pod_glob": "*nginx*"}

        config_fragment = {
            "workers": [
                {"api_key": "key4", "id": "fourth_key"},
                {"api_key": "key5", "id": "fifth_key", "sessions": 3},
            ],
            "k8s_logs": [
                k8s_config1,
                {"k8s_pod_glob": "*apache*", "worker_id": "second_key"},
            ],
            "logs": [{"path": "path4"}, {"path": "path6", "worker_id": "second_key"}],
        }
        self._write_file_with_separator_conversion(json.dumps(main_config))
        self._write_config_fragment_file_with_separator_conversion(
            "a.json", json.dumps(config_fragment)
        )

        config = self._create_test_configuration_instance()
        config.parse()

        workers = list(config.worker_configs)

        assert len(workers) == 5

        # check workers for journald logs
        for worker in workers:
            journald_unit = worker.get("journald_unit", none_if_missing=True)
            if journald_unit:
                if journald_unit == "ssh\\.service":
                    assert worker["worker_id"] == "default"
                elif journald_unit == "journald_unit":
                    assert worker["worker_id"] == "second_key"

        # check workers for k8s logs.
        for worker in workers:
            k8s_pod_glob = worker.get("k8s_pod_glob", none_if_missing=True)
            if k8s_pod_glob:
                if k8s_pod_glob == "*nginx*":
                    assert worker["worker_id"] == "default"
                elif k8s_pod_glob == "*apache*":
                    assert worker["worker_id"] == "third_key"

        # non existing worker for l8s, should fail
        k8s_config1["worker_id"] = "not_exist"
        self._write_file_with_separator_conversion(json.dumps(main_config))
        self._write_config_fragment_file_with_separator_conversion(
            "a.json", json.dumps(config_fragment)
        )

        config = self._create_test_configuration_instance()

        with pytest.raises(BadConfiguration) as err_info:
            config.parse()

        assert (
            "refers to a non-existing worker with id 'not_exist'"
            in err_info.value.message
        )

        k8s_config1["worker_id"] = "default"

        # non existing worker for jornald, should fail
        journald_log1["worker_id"] = "not exist too."
        self._write_file_with_separator_conversion(json.dumps(main_config))
        self._write_config_fragment_file_with_separator_conversion(
            "a.json", json.dumps(config_fragment)
        )

        config = self._create_test_configuration_instance()

        with pytest.raises(BadConfiguration) as err_info:
            config.parse()

        assert (
            "refers to a non-existing worker with id 'not exist too.'"
            in err_info.value.message
        )

        journald_log1["worker_id"] = "default"
        self._write_file_with_separator_conversion(json.dumps(main_config))
        self._write_config_fragment_file_with_separator_conversion(
            "a.json", json.dumps(config_fragment)
        )

        config = self._create_test_configuration_instance()

        config.parse()

    def test_invalid_worker_id(self):
        def recreate(worker_id):
            self._write_file_with_separator_conversion(
                """ {{
                    api_key: "hi there"
                    workers: [
                        {{"api_key": "another_key", "id": "{0}"}},
                    ]
                  }}
                """.format(
                    worker_id
                )
            )
            config = self._create_test_configuration_instance()

            config.parse()

        with pytest.raises(BadConfiguration) as err_info:
            recreate("Invalid.key /")

        assert "contains an invalid character" in err_info.value.message

        with pytest.raises(BadConfiguration) as err_info:
            recreate("Invalid.key ")

        assert "contains an invalid character" in err_info.value.message

        with pytest.raises(BadConfiguration) as err_info:
            recreate("Invalid.key")

        assert "contains an invalid character" in err_info.value.message

        recreate("not_Invalid_key_anymore")

    def test_parse_config_fragment_contains_invalid_content(self):
        self._write_file_with_separator_conversion(
            """ { api_key: "hi there"
            logs: [ { path:"/var/log/tomcat6/access.log" }],
            server_attributes: {  serverHost:"foo.com" }
          }
        """
        )

        self._write_raw_config_fragment_file(
            "nginx.json", """[ { path: "/var/log/nginx/access.log" } ]"""
        )

        config = self._create_test_configuration_instance()

        expected_msg = (
            r'Invalid content inside configuration fragment file ".*nginx\.json". '
            r"Expected JsonObject \(dictionary\), got JsonArray."
        )
        self.assertRaisesRegexp(BadConfiguration, expected_msg, config.parse)
