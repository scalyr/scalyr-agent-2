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

__author__ = "czerwin@scalyr.com"

import os
import sys
import tempfile
from io import open

import mock

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
import scalyr_agent.util as scalyr_util
from scalyr_agent.compat import os_environ_unicode

import six
from six.moves import range
from mock import patch, Mock, call


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
        for key in os_environ_unicode.keys():
            if "scalyr" in key.lower():
                del os.environ[key]

    def tearDown(self):
        """Restore the pre-test os environment"""
        os.environ.clear()
        os.environ.update(self.original_os_env)

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
        self, file_path, contents
    ):
        contents = scalyr_util.json_encode(
            self.__convert_separators(
                scalyr_util.json_scalyr_config_decode(contents)
            ).to_dict()
        )

        full_path = os.path.join(self._config_fragments_dir, file_path)
        fp = open(full_path, "w")
        fp.write(contents)
        fp.close()

    class LogObject(object):
        def __init__(self, config):
            self.config = config
            self.log_path = config["path"]

    class MonitorObject(object):
        def __init__(self, config):
            self.module_name = config["module"]
            self.config = config
            self.log_config = {"path": self.module_name.split(".")[-1] + ".log"}

    def _create_test_configuration_instance(self, logger=None):
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

        return Configuration(self._config_file, default_paths, logger)

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

        if os.path.sep == "\\":
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

        self.assertEquals(config.max_allowed_request_size, 1 * 1024 * 1024)
        self.assertEquals(config.min_allowed_request_size, 100 * 1024)

        self.assertEquals(config.min_request_spacing_interval, 1.0)
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

        self.assertEquals(config.max_line_size, 9900)
        self.assertEquals(config.max_log_offset_size, 5 * 1024 * 1024)
        self.assertEquals(config.max_existing_log_offset_size, 100 * 1024 * 1024)
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

        self.assertEquals(config.pipeline_threshold, 1.1)

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
            config.k8s_verify_kubelet_queries, True,
        )

        self.assertEquals(len(config.log_configs), 2)
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
        self.assertFalse(config.log_configs[0].get_bool("ignore_stale_files"))
        self.assertEquals(
            config.log_configs[0].get_float("staleness_threshold_secs"), 300
        )

        self.assertEquals(len(config.monitor_configs), 0)
        self.assertIsNone(config.network_proxies)

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
        self.assertEquals(len(config.log_configs), 1)

        self.assertPathEquals(
            config.log_configs[0].get_string("path"),
            "/var/log/scalyr-agent-2/agent.log",
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
            journald_logs: [ { journald_unit: ".*", parser: "journald_catchall" } ]
          }
        """
        )
        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEquals(config.api_key, "hi there")
        self.assertPathEquals(config.agent_log_path, "/var/silly1")
        self.assertPathEquals(config.agent_data_path, "/var/silly2")
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
            config.copying_thread_profile_output_path, "/tmp/some_profiles"
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

        self.assertEquals(len(config.log_configs), 2)
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

        self.assertEquals(len(config.log_configs), 2)
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

        self.assertEquals(len(config.log_configs), 4)
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

        self.assertEquals(len(config.log_configs), 2)

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
        self.assertEquals(len(config.log_configs), 1)
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

        self.assertEquals(parsed_log_config["path"], "/var/log/scalyr-agent-2/hi.log")

        parsed_log_config = config.parse_log_config(
            {"path": "/var/log/scalyr-agent-2/hi.log"}, default_parser="foo"
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
        self.assertEquals(config.agent_log_path, "/var/silly1")
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
        mock_logger.info.assert_any_call("\tmax_line_size: 9900")

    def test_print_config_when_changed(self):
        """
        Test that `print_useful_settings` only outputs changed settings when compared to another
        configuration object
        """
        self._write_file_with_separator_conversion(
            """{
            api_key: "hi there"
            }
        """
        )
        mock_logger = Mock()
        config = self._create_test_configuration_instance(logger=mock_logger)
        config.parse()

        self._write_file_with_separator_conversion(
            """{
            api_key: "hi there"
            max_line_size: 49900,
            }
        """
        )
        new_config = self._create_test_configuration_instance(logger=mock_logger)
        new_config.parse()

        new_config.print_useful_settings(other_config=config)

        calls = [
            call("Configuration settings"),
            call("\tmax_line_size: 49900"),
        ]
        mock_logger.info.assert_has_calls(calls)

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

        self.assertEquals(len(config.log_configs), 3)
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
        """"""
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
            None, get_config_from_env("server_attributes", convert_to=JsonObject),
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

        expected_path = os.path.join(self._log_dir, "journald_monitor.log",)
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

        expected_path = os.path.join(self._log_dir, "journald_monitor.log",)
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
            self._log_dir, "journald_" + six.text_type(hash("TEST")) + ".log",
        )
        with open(expected_path) as f:
            self.assertTrue("Find this string" in f.read())

        expected_path = os.path.join(self._log_dir, "journald_monitor.log",)
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
            self._log_dir, "journald_" + six.text_type(hash("test.*test")) + ".log",
        )
        with open(expected_path) as f:
            self.assertTrue("Find this string" in f.read())

        expected_path = os.path.join(self._log_dir, "journald_monitor.log",)
        with open(expected_path) as f:
            self.assertTrue("Other thing" in f.read())

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
