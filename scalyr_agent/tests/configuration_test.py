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
import scalyr_agent.json_lib.objects

__author__ = 'czerwin@scalyr.com'

import os
import tempfile
from mock import patch, Mock

from scalyr_agent.configuration import Configuration, BadConfiguration
from scalyr_agent.config_util import parse_array_of_strings, convert_config_param, get_config_from_env
from scalyr_agent.json_lib import JsonObject, JsonArray
from scalyr_agent.json_lib import parse as parse_json, serialize as serialize_json
from scalyr_agent.json_lib.objects import ArrayOfStrings, SpaceAndCommaSeparatedArrayOfStrings
from scalyr_agent.platform_controller import DefaultPaths

from scalyr_agent.test_base import ScalyrTestCase


class TestConfigurationBase(ScalyrTestCase):

    def setUp(self):
        self.original_os_env = dict([(k, v) for k, v in os.environ.iteritems()])
        self._config_dir = tempfile.mkdtemp()
        self._config_file = os.path.join(self._config_dir, 'agent.json')
        self._config_fragments_dir = os.path.join(self._config_dir, 'agent.d')
        os.makedirs(self._config_fragments_dir)
        for key in os.environ.keys():
            if 'scalyr' in key.lower():
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
                if key.endswith('path') and (value_type is str or value_type is unicode):
                    contents[key] = self.convert_path(contents[key])
                elif value_type in (dict, JsonObject, list, JsonArray):
                    self.__convert_separators(value)
        elif contents_type is list or contents_type is JsonArray:
            for i in range(len(contents)):
                self.__convert_separators(contents[i])
        return contents

    def _write_file_with_separator_conversion(self, contents):
        contents = serialize_json(self.__convert_separators(parse_json(contents)))

        fp = open(self._config_file, 'w')
        fp.write(contents)
        fp.close()

    def _write_config_fragment_file_with_separator_conversion(self, file_path, contents):
        contents = serialize_json(self.__convert_separators(parse_json(contents)))

        full_path = os.path.join(self._config_fragments_dir, file_path)
        fp = open(full_path, 'w')
        fp.write(contents)
        fp.close()

    class LogObject(object):
        def __init__(self, config):
            self.config = config
            self.log_path = config['path']

    class MonitorObject(object):
        def __init__(self, config):
            self.module_name = config['module']
            self.config = config
            self.log_config = {'path': self.module_name.split('.')[-1] + '.log'}

    def _create_test_configuration_instance(self, logger=None):
        """Creates an instance of a Configuration file for testing.

        @return:  The test instance
        @rtype: Configuration
        """
        default_paths = DefaultPaths(self.convert_path('/var/log/scalyr-agent-2'),
                                     self.convert_path('/etc/scalyr-agent-2/agent.json'),
                                     self.convert_path('/var/lib/scalyr-agent-2'))

        return Configuration(self._config_file, default_paths, logger)

    # noinspection PyPep8Naming
    def assertPathEquals(self, actual_path, expected_path):
        """Similar to `assertEquals` but the expected path is converted to the underlying system's dir separators
        before comparison.

        @param actual_path:  The actual path.  This should already be using the correct separator characters.
        @param expected_path:  The expected path.  This should use `/`'s as the separator character.  It will be
            converted to this system's actual separators.

        @type actual_path: str
        @type expected_path: str
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
        if parent_directory is None and os.path.sep == '/':
            return path

        if parent_directory is None:
            result = ''
        elif path.startswith('/'):
            result = ''
        else:
            result = parent_directory

        for path_part in path.split('/'):
            if len(path_part) > 0:
                result = os.path.join(result, path_part)

        if os.path.sep == '\\':
            result = 'C:\\%s' % result
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
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ { path:"/var/log/tomcat6/access.log"} ]
          }
        """)
        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEquals(config.api_key, "hi there")
        self.assertPathEquals(config.agent_log_path, '/var/log/scalyr-agent-2')
        self.assertPathEquals(config.agent_data_path, '/var/lib/scalyr-agent-2')
        self.assertEquals(config.additional_monitor_module_paths, '')
        self.assertEquals(config.config_directory, self._config_fragments_dir)
        self.assertEquals(config.implicit_metric_monitor, True)
        self.assertEquals(config.implicit_agent_log_collection, True)
        self.assertFalse(config.use_unsafe_debugging)
        self.assertEquals(config.scalyr_server, 'https://agent.scalyr.com')
        self.assertEquals(len(config.server_attributes), 1)
        self.assertTrue('serverHost' in config.server_attributes)

        self.assertEquals(config.global_monitor_sample_interval, 30.0)

        self.assertEquals(config.max_allowed_request_size, 1*1024*1024)
        self.assertEquals(config.min_allowed_request_size, 100*1024)

        self.assertEquals(config.min_request_spacing_interval, 1.0)
        self.assertEquals(config.max_request_spacing_interval, 5.0)

        self.assertEquals(config.high_water_bytes_sent, 100*1024)
        self.assertEquals(config.high_water_request_spacing_adjustment, 0.6)
        self.assertEquals(config.low_water_bytes_sent, 20*1024)
        self.assertEquals(config.low_water_request_spacing_adjustment, 1.5)

        self.assertEquals(config.failure_request_spacing_adjustment, 1.5)
        self.assertEquals(config.request_too_large_adjustment, 0.5)
        self.assertEquals(config.debug_level, 0)
        self.assertEquals(config.request_deadline, 60.0)

        self.assertEquals(config.max_line_size, 9900)
        self.assertEquals(config.max_log_offset_size, 5 * 1024 * 1024)
        self.assertEquals(config.max_existing_log_offset_size, 100 * 1024 * 1024)
        self.assertEquals(config.max_sequence_number, 1024**4)
        self.assertEquals(config.line_completion_wait_time, 5)
        self.assertEquals(config.read_page_size, 64 * 1024)
        self.assertEquals(config.copy_staleness_threshold, 15 * 60)
        self.assertEquals(config.log_deletion_delay, 10 * 60)

        self.assertEquals(config.max_new_log_detection_time, 1 * 60)

        self.assertEquals(config.copying_thread_profile_interval, 0)
        self.assertEquals(config.copying_thread_profile_output_path, '/tmp/copying_thread_profiles_')

        self.assertTrue(config.ca_cert_path.endswith('ca_certs.crt'))
        self.assertTrue(config.verify_server_certificate)
        self.assertFalse(config.debug_init)
        self.assertFalse(config.pidfile_advanced_reuse_guard)
        self.assertFalse(config.strip_domain_from_default_server_host)

        self.assertEquals(config.pipeline_threshold, 1.1)

        self.assertEquals(len(config.log_configs), 2)
        self.assertPathEquals(config.log_configs[0].get_string('path'), '/var/log/tomcat6/access.log')
        self.assertEquals(config.log_configs[0].get_json_object('attributes'), JsonObject())
        self.assertEquals(config.log_configs[0].get_json_array('sampling_rules'), JsonArray())
        self.assertEquals(config.log_configs[0].get_json_array('redaction_rules'), JsonArray())
        self.assertPathEquals(config.log_configs[1].get_string('path'), '/var/log/scalyr-agent-2/agent.log')
        self.assertFalse(config.log_configs[0].get_bool('ignore_stale_files'))
        self.assertEquals(config.log_configs[0].get_float('staleness_threshold_secs'), 300)

        self.assertEquals(len(config.monitor_configs), 0)
        self.assertIsNone(config.network_proxies)

    def test_empty_config(self):
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there"
          }
        """)

        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEquals(config.api_key, "hi there")
        self.assertEquals(len(config.log_configs), 1)

        self.assertPathEquals(config.log_configs[0].get_string('path'), '/var/log/scalyr-agent-2/agent.log')

    def test_overriding_basic_settings(self):
        self._write_file_with_separator_conversion(""" {
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
            copy_staleness_threshold: 240,
            log_deletion_delay: 300,
            debug_init: true,
            pidfile_advanced_reuse_guard: true,

            max_new_log_detection_time: 120,

            copying_thread_profile_interval: 2,
            copying_thread_profile_output_path: "/tmp/some_profiles",

            http_proxy: "http://foo.com",
            https_proxy: "https://bar.com",

            logs: [ { path: "/var/log/tomcat6/access.log", ignore_stale_files: true} ]
          }
        """)
        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEquals(config.api_key, "hi there")
        self.assertPathEquals(config.agent_log_path, '/var/silly1')
        self.assertPathEquals(config.agent_data_path, '/var/silly2')
        self.assertEquals(config.additional_monitor_module_paths, 'silly3')
        self.assertEquals(config.config_directory, os.path.join(self._config_dir, 'silly4'))
        self.assertEquals(config.implicit_metric_monitor, False)
        self.assertEquals(config.implicit_agent_log_collection, False)
        self.assertTrue(config.use_unsafe_debugging)
        self.assertEquals(config.scalyr_server, 'noland.scalyr.com')
        self.assertEquals(len(config.server_attributes), 2)
        self.assertEquals(config.server_attributes['region'], 'us-east')

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
        self.assertEquals(config.copy_staleness_threshold, 4 * 60)
        self.assertEquals(config.log_deletion_delay, 5 * 60)

        self.assertEquals(config.copying_thread_profile_interval, 2)
        self.assertEquals(config.copying_thread_profile_output_path, '/tmp/some_profiles')

        self.assertEquals(config.max_new_log_detection_time, 2 * 60)
        self.assertTrue(config.strip_domain_from_default_server_host)

        self.assertEquals(config.pipeline_threshold, 0.5)

        self.assertEquals(config.failure_request_spacing_adjustment, 2.0)
        self.assertEquals(config.request_too_large_adjustment, 0.75)
        self.assertEquals(config.debug_level, 1)
        self.assertEquals(config.request_deadline, 30.0)
        self.assertPathEquals(config.ca_cert_path, '/var/lib/foo.pem')
        self.assertFalse(config.verify_server_certificate)
        self.assertTrue(config.debug_init)
        self.assertTrue(config.pidfile_advanced_reuse_guard)

        self.assertTrue(config.log_configs[0].get_bool('ignore_stale_files'))
        self.assertEqual(config.network_proxies, {"http": "http://foo.com", "https": "https://bar.com"})

    def test_missing_api_key(self):
        self._write_file_with_separator_conversion(""" {
            logs: [ { path:"/var/log/tomcat6/access.log"} ]
          }
        """)

        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_force_https_no_scheme(self):
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            scalyr_server: "agent.scalyr.com",
          }
        """)
        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEqual( "https://agent.scalyr.com", config.scalyr_server)

    def test_force_https_http(self):
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            scalyr_server: "http://agent.scalyr.com",
          }
        """)
        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEqual( "https://agent.scalyr.com", config.scalyr_server)

    def test_force_https_https(self):
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            scalyr_server: "https://agent.scalyr.com",
          }
        """)
        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEqual( "https://agent.scalyr.com", config.scalyr_server)

    def test_force_https_leading_whitespace(self):
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            scalyr_server: "  http://agent.scalyr.com",
          }
        """)
        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEqual( "https://agent.scalyr.com", config.scalyr_server)

    def test_allow_http(self):
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            allow_http: true,
            scalyr_server: "http://agent.scalyr.com",
          }
        """)
        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEqual( "http://agent.scalyr.com", config.scalyr_server)

    def test_non_string_value(self):
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            agent_log_path: [ "hi" ],
          }
        """)
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_non_json_attributes(self):
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            server_attributes: [ "hi" ],
          }
        """)
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_non_string_attribute_values(self):
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            server_attributes: { hi: [ 1 ] },
          }
        """)
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_non_bool_value(self):
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            implicit_metric_monitor: [ 1 ],
          }
        """)
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_no_https_proxy(self):
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            http_proxy: "http://bar.com",
          }
        """)
        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEqual(config.network_proxies, {"http": "http://bar.com"})

    def test_no_http_proxy(self):
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            https_proxy: "https://bar.com",
          }
        """)
        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEqual(config.network_proxies, {"https": "https://bar.com"})

    def test_sampling_rules(self):
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { match_expression: "INFO", sampling_rate: 0},
                                { match_expression: ".*error.*=foo", sampling_rate: 0.2 } ],
            }]
          }
        """)
        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(len(config.log_configs), 2)
        sampling_rules = config.log_configs[0].get_json_array('sampling_rules')
        self.assertEquals(len(sampling_rules), 2)
        self.assertEquals(sampling_rules.get_json_object(0).get_string("match_expression"), "INFO")
        self.assertEquals(sampling_rules.get_json_object(0).get_float("sampling_rate"), 0)
        self.assertEquals(sampling_rules.get_json_object(1).get_string("match_expression"), ".*error.*=foo")
        self.assertEquals(sampling_rules.get_json_object(1).get_float("sampling_rate"), 0.2)

    def test_bad_sampling_rules(self):
        # Missing match_expression.
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { sampling_rate: 0} ]
          }] }
        """)
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Bad regular expression.
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { match_expression: "[a", sampling_rate: 0} ]
          }] }
        """)
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Missing sampling.
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { match_expression: "INFO"} ]
          }] }
        """)
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Not number for percentage.
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { match_expression: "INFO", sampling_rate: true} ]
          }] }
        """)
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Bad percentage.
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { match_expression: "INFO", sampling_rate: 2.0} ]
          }] }
        """)
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_redaction_rules(self):
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              redaction_rules: [ { match_expression: "password=", replacement: "password=foo"},
                                 { match_expression: "password=.*", replacement: "password=foo"},
                                 { match_expression: "password=" },
              ],
            }]
          }
        """)
        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(len(config.log_configs), 2)
        redaction_rules = config.log_configs[0].get_json_array('redaction_rules')
        self.assertEquals(len(redaction_rules), 3)
        self.assertEquals(redaction_rules.get_json_object(0).get_string("match_expression"), "password=")
        self.assertEquals(redaction_rules.get_json_object(0).get_string("replacement"), "password=foo")
        self.assertEquals(redaction_rules.get_json_object(1).get_string("match_expression"), "password=.*")
        self.assertEquals(redaction_rules.get_json_object(1).get_string("replacement"), "password=foo")
        self.assertEquals(redaction_rules.get_json_object(2).get_string("match_expression"), "password=")
        self.assertEquals(redaction_rules.get_json_object(2).get_string("replacement"), "")

    def test_bad_redaction_rules(self):
        # Missing match expression.
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              redaction_rules: [ { replacement: "password=foo"} ],
            }] }
        """)
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Match expression is not a regexp.
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              redaction_rules: [ { match_expression: "[a" } ],
            }] }
        """)
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Replacement is not a string.
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              redaction_rules: [ { match_expression: "a", replacement: [ true ] } ],
            }] }
        """)
        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_configuration_directory(self):
        self._write_file_with_separator_conversion(""" { api_key: "hi there"
            logs: [ { path:"/var/log/tomcat6/access.log" }],
            server_attributes: {  serverHost:"foo.com" }
          }
        """)

        self._write_config_fragment_file_with_separator_conversion('nginx.json', """ {
           logs: [ { path: "/var/log/nginx/access.log" } ],
           server_attributes: { webServer:"true"}
          }
        """)

        self._write_config_fragment_file_with_separator_conversion('apache.json', """ {
           logs: [ { path: "/var/log/apache/access.log" } ]
          }
        """)

        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(len(config.additional_file_paths), 2)
        additional_paths = list(config.additional_file_paths)
        additional_paths.sort()
        self.assertTrue(additional_paths[0].endswith('apache.json'))
        self.assertTrue(additional_paths[1].endswith('nginx.json'))

        self.assertEquals(len(config.log_configs), 4)
        self.assertPathEquals(config.log_configs[0].get_string('path'), '/var/log/tomcat6/access.log')
        self.assertPathEquals(config.log_configs[1].get_string('path'), '/var/log/apache/access.log')
        self.assertPathEquals(config.log_configs[2].get_string('path'), '/var/log/nginx/access.log')
        self.assertEquals(config.log_configs[0].get_json_array('sampling_rules'), JsonArray())

        self.assertEquals(config.server_attributes['webServer'], 'true')
        self.assertEquals(config.server_attributes['serverHost'], 'foo.com')

    def test_api_key_and_scalyr_server_defined_in_config_directory(self):
        self._write_file_with_separator_conversion(""" {
            logs: [ { path:"/var/log/tomcat6/access.log" }],
          }
        """)

        self._write_config_fragment_file_with_separator_conversion('nginx.json', """ {
           api_key: "hi there",
           scalyr_server: "foobar",
           allow_http: true,
           logs: [ { path: "/var/log/nginx/access.log" } ],
          }
        """)

        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.scalyr_server, 'foobar')
        self.assertEquals(config.api_key, 'hi there')

    def test_bad_fields_in_configuration_directory(self):
        self._write_file_with_separator_conversion(""" { api_key: "hi there"
            logs: [ { path:"/var/log/tomcat6/access.log" }]
          }
        """)

        self._write_config_fragment_file_with_separator_conversion('nginx.json', """ {
           api_key: "should cause an error",
           logs: [ { path: "/var/log/nginx/access.log" } ]
          }
        """)

        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_multiple_scalyr_servers_in_configuration_directory(self):
        self._write_file_with_separator_conversion(""" { api_key: "hi there", scalyr_server: "test1",
            logs: [ { path:"/var/log/tomcat6/access.log" }]
          }
        """)

        self._write_config_fragment_file_with_separator_conversion('nginx.json', """ {
           scalyr_server: "should cause an error",
           logs: [ { path: "/var/log/nginx/access.log" } ]
          }
        """)

        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_ignore_non_json_files_in_config_dir(self):
        self._write_file_with_separator_conversion(""" { api_key: "hi there"
            logs: [ { path:"/var/log/tomcat6/access.log" }]
          }
        """)

        self._write_config_fragment_file_with_separator_conversion('nginx', """ {
           logs: [ { path: "/var/log/nginx/access.log" } ]
          }
        """)

        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(len(config.log_configs), 2)

    def test_parser_specification(self):
        self._write_file_with_separator_conversion(""" {
            implicit_agent_log_collection: false,
            api_key: "hi there",
            logs: [ { path: "/tmp/foo.txt",
                      parser: "foo-parser"} ]
          }
        """)
        config = self._create_test_configuration_instance()
        config.parse()
        self.assertEquals(len(config.log_configs), 1)
        self.assertEquals(config.log_configs[0]['attributes']['parser'], 'foo-parser')

    def test_monitors(self):
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            monitors: [ { module: "httpPuller"} ]
          }
        """)
        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(len(config.monitor_configs), 1)
        self.assertEquals(len(config.log_configs), 1)
        self.assertEquals(config.monitor_configs[0].get_string('module'), 'httpPuller')
        self.assertEquals(config.monitor_configs[0].get_string('log_path'), 'httpPuller.log')

        self.assertPathEquals(config.log_configs[0].get_string('path'), '/var/log/scalyr-agent-2/agent.log')

    def test_parse_log_config(self):
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there"
          }
        """)
        config = self._create_test_configuration_instance()
        config.parse()

        parsed_log_config = config.parse_log_config({
            "path": 'hi.log'
        })

        self.assertEquals(parsed_log_config['path'], '/var/log/scalyr-agent-2/hi.log')

        parsed_log_config = config.parse_log_config({
            "path": '/var/log/scalyr-agent-2/hi.log'
        }, default_parser="foo")

        self.assertEquals(parsed_log_config['attributes']['parser'], 'foo')

    def test_parse_monitor_config(self):
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there"
          }
        """)

        config = self._create_test_configuration_instance()
        config.parse()

        parsed_monitor_config = config.parse_monitor_config({
            "module": "foo"
        })

        self.assertEquals(parsed_monitor_config['module'], 'foo')

    def test_equivalent_configuration(self):
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ { path:"/var/log/tomcat6/access.log"} ]
          }
        """)
        config_a = self._create_test_configuration_instance()
        config_a.parse()

        config_b = self._create_test_configuration_instance()
        config_b.parse()

        self.assertTrue(config_a.equivalent(config_b))

        # Now write a new file that is slightly different.
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ { path:"/var/log/nginx/access.log"} ]
          }
        """)

        config_b = self._create_test_configuration_instance()
        config_b.parse()

        self.assertFalse(config_a.equivalent(config_b))

    def test_equivalent_configuration_ignore_debug_level(self):
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
          }
        """)
        config_a = self._create_test_configuration_instance()
        config_a.parse()

        # Now write a new file that is slightly different.
        self._write_file_with_separator_conversion(""" {
            api_key: "hi there",
            debug_level: 1,
          }
        """)

        config_b = self._create_test_configuration_instance()
        config_b.parse()

        # Should be not equivalent when we aren't ignoring debug_level,
        # but equivalent when we are.
        self.assertFalse(config_a.equivalent(config_b))
        self.assertEquals(config_b.debug_level, 1)

        self.assertTrue(config_a.equivalent(config_b, exclude_debug_level=True))
        self.assertEquals(config_b.debug_level, 1)

    def test_multiple_calls_to_bad_config(self):
        self._write_file_with_separator_conversion(""" {
            logs: [ { path:"/var/log/tomcat6/access.log"} ]
          }
        """)

        config = self._create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        error_seen = False
        try:
            self.assertTrue(config.agent_log_path is not None)
        except BadConfiguration:
            error_seen = True

        self.assertTrue(error_seen)

    def test_substitution(self):
        self._write_file_with_separator_conversion(""" {
            import_vars: [ "TEST_VAR" ],
            api_key: "hi$TEST_VAR",
          }
        """)

        os.environ['TEST_VAR'] = 'bye'
        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, 'hibye')

    def test_substitution_with_default(self):
        self._write_file_with_separator_conversion(""" {
            import_vars: [ {var: "UNDEFINED_VAR", default: "foo" } ],
            api_key: "hi$UNDEFINED_VAR",
          }
        """)

        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, 'hifoo')

    def test_substitution_with_unused_default(self):
        self._write_file_with_separator_conversion(""" {
            import_vars: [ {var: "TEST_VAR2", default: "foo" } ],
            api_key: "hi$TEST_VAR2",
          }
        """)

        os.environ['TEST_VAR2'] = 'bar'
        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, 'hibar')

    def test_substitution_with_empty_var(self):
        self._write_file_with_separator_conversion(""" {
            import_vars: [ {var: "TEST_VAR2", default: "foo" } ],
            api_key: "hi$TEST_VAR2",
          }
        """)

        os.environ['TEST_VAR2'] = ''
        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, 'hifoo')

    def test_api_key_override_no_override(self):
        self._write_file_with_separator_conversion(""" {
            logs: [ { path:"/var/log/tomcat6/$DIR_VAR.log" }],
            api_key: "abcd1234",
          }
        """)

        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, 'abcd1234')

    def test_api_key_override_empty_override(self):
        self._write_file_with_separator_conversion(""" {
            logs: [ { path:"/var/log/tomcat6/$DIR_VAR.log" }],
            api_key: "abcd1234",
          }
        """)
        os.environ['scalyr_api_key'] = ''

        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, 'abcd1234')

    def test_api_key_overridden_by_config_file(self):
        self._write_file_with_separator_conversion(""" {
            logs: [ { path:"/var/log/tomcat6/$DIR_VAR.log" }],
            api_key: "abcd1234",
          }
        """)
        os.environ['SCALYR_API_KEY'] = "xyz"
        mock_logger = Mock()
        config = self._create_test_configuration_instance(logger=mock_logger)
        config.parse()

        self.assertEquals(config.api_key, 'abcd1234')
        mock_logger.warn.assert_called_with(
            "Conflicting values detected between global config file parameter `api_key` and the environment variable "
            "`SCALYR_API_KEY`. Ignoring environment variable.",
            limit_once_per_x_secs=300, limit_key='config_conflict_global_api_key_SCALYR_API_KEY',
        )
        mock_logger.debug.assert_not_called()

    def test_api_key_use_env(self):
        self._write_file_with_separator_conversion(""" {
            logs: [ { path:"/var/log/tomcat6/$DIR_VAR.log" }]
          }
        """)
        os.environ['SCALYR_API_KEY'] = "xyz"
        mock_logger = Mock()
        config = self._create_test_configuration_instance(logger=mock_logger)
        config.parse()

        self.assertEquals(config.api_key, 'xyz')
        mock_logger.warn.assert_not_called()
        mock_logger.debug.assert_called_with(
            "Using the api key from environment variable `SCALYR_API_KEY`",
            limit_once_per_x_secs=300, limit_key='api_key_from_env',
        )

    def test_duplicate_api_key(self):
        self._write_file_with_separator_conversion("""{
            api_key: "abcd1234",
        }
        """)

        self._write_config_fragment_file_with_separator_conversion("apikey.json", """{
            api_key: "abcd1234",
        }
        """)

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
            "logs": [
                {"path": "/var/log/tomcat6/$DIR_VAR.log"}
            ],
            "api_key": "abcd1234",
            "use_unsafe_debugging": False,
        }
        self._write_file_with_separator_conversion(serialize_json(JsonObject(config_file_dict)))

        config = self._create_test_configuration_instance()

        # Parse config files once to capture all environment-aware variables in Configuration._environment_aware_map
        config.parse()
        expected_aware_fields = config._environment_aware_map

        # Currently, all environment-aware global config params are primitives.
        # (In the future, we will need to intercept the json_array, json_object, ArrayOfString methods)
        original_verify_or_set_optional_bool = config._Configuration__verify_or_set_optional_bool
        original_verify_or_set_optional_int = config._Configuration__verify_or_set_optional_int
        original_verify_or_set_optional_float = config._Configuration__verify_or_set_optional_float
        original_verify_or_set_optional_string = config._Configuration__verify_or_set_optional_string
        original_verify_or_set_optional_array_of_strings = config._Configuration__verify_or_set_optional_array_of_strings

        @patch.object(config, '_Configuration__verify_or_set_optional_bool')
        @patch.object(config, '_Configuration__verify_or_set_optional_int')
        @patch.object(config, '_Configuration__verify_or_set_optional_float')
        @patch.object(config, '_Configuration__verify_or_set_optional_string')
        @patch.object(config, '_Configuration__verify_or_set_optional_array_of_strings')
        def patch_and_start_test(p4, p3, p2, p1, p0):
            # Decorate the Configuration.__verify_or_set_optional_xxx methods as follows:
            # 1) capture fields that are environment-aware
            # 2) allow setting of the corresponding environment variable
            def capture_aware_field(field_type):
                def wrapper(*args, **kwargs):
                    field = args[1]
                    field_types[field] = field_type
                    envar_val = function_lookup['get_environment'](field)
                    if envar_val:
                        env_name = expected_aware_fields[field]
                        if not env_name:
                            env_name = 'SCALYR_%s' % field
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
                    elif field_type == str:
                        return original_verify_or_set_optional_string(*args, **kwargs)
                    elif field_type == ArrayOfStrings:
                        return original_verify_or_set_optional_array_of_strings(*args, **kwargs)
                return wrapper

            p0.side_effect = capture_aware_field(bool)
            p1.side_effect = capture_aware_field(int)
            p2.side_effect = capture_aware_field(float)
            p3.side_effect = capture_aware_field(str)
            p4.side_effect = capture_aware_field(ArrayOfStrings)

            # Build the Configuration object tree, also populating the field_types lookup in the process
            # This first iteration does not set any environment variables
            def no_set_values(field):
                return None
            function_lookup = {'get_environment': no_set_values}
            config.parse()

            # ---------------------------------------------------------------------------------------------------------
            # Ensure each field can be overridden (by faking environment variables)
            # ---------------------------------------------------------------------------------------------------------

            fake_env = {}
            config_obj = config._Configuration__get_config()

            # prepare fake environment variable values that differ from existing config object
            FAKE_INT = 1234567890
            FAKE_FLOAT = 1234567.89
            FAKE_STRING = str(FAKE_INT)
            FAKE_ARRAY_OF_STRINGS = ArrayOfStrings(['s1', 's2', 's3'])

            for field in expected_aware_fields:
                field_type = field_types[field]

                if field_type == bool:
                    # fake value should be different from config-file value
                    fake_env[field] = not config_obj.get_bool(field, none_if_missing=True)

                elif field_type == int:
                    # special case : debug_level cannot be arbitrary. Set it to config file value + 1
                    if field == 'debug_level':
                        existing_level = config_obj.get_int(field, none_if_missing=True)
                        fake_env[field] = existing_level + 1
                    else:
                        self.assertNotEquals(FAKE_INT, config_obj.get_int(field, none_if_missing=True))
                        fake_env[field] = FAKE_INT

                elif field_type == float:
                    self.assertNotEquals(FAKE_FLOAT, config_obj.get_float(field, none_if_missing=True))
                    fake_env[field] = FAKE_FLOAT

                elif field_type == str:
                    self.assertNotEquals(FAKE_STRING, config_obj.get_string(field, none_if_missing=True))
                    fake_env[field] = FAKE_STRING

                elif field_type == ArrayOfStrings:
                    self.assertNotEquals(FAKE_ARRAY_OF_STRINGS, config_obj.get_json_array(field, none_if_missing=True))
                    fake_env[field] = FAKE_ARRAY_OF_STRINGS

            def fake_environment_value(field):
                if field not in fake_env:
                    return None
                fake_field_val = fake_env[field]
                if isinstance(fake_field_val, ArrayOfStrings):
                    separator = ','
                    # legacy whitespace separator support for 'k8s_ignore_namespaces'
                    if field == 'k8s_ignore_namespaces':
                        separator = ' '
                    result = str(separator.join([x for x in fake_field_val])).lower()
                else:
                    result = str(fake_field_val).lower()
                return result
            function_lookup = {'get_environment': fake_environment_value}

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
                elif field_type == str:
                    value = config._Configuration__get_config().get_string(field)
                elif field_type == ArrayOfStrings:
                    value = config._Configuration__get_config().get_json_array(field)

                config_file_value = config_file_dict.get(field)
                if field in config_file_dict:
                    # Config params defined in the config file must not take on the fake environment values.
                    self.assertNotEquals(value, fake_env[field])
                    self.assertEquals(value, config_file_value)
                else:
                    # But those not defined in config file will take on environment values.
                    self.assertEquals(value, fake_env[field])
                    self.assertNotEquals(value, config_file_value)
        patch_and_start_test()

    def test_log_excludes_from_config(self):
        self._write_file_with_separator_conversion(""" { 
            api_key: "hi there",
            logs: [
                { 
                    path: "/var/log/tomcat6/access.log",
                    exclude: ["*.[0-9]*", "*.bak"]  
                }
            ],
          }
        """)
        config = self._create_test_configuration_instance()
        config.parse()
        excludes = config.log_configs[0]['exclude']
        self.assertEquals(type(excludes), JsonArray)
        self.assertEquals(list(excludes), ["*.[0-9]*", "*.bak"])

    def test_global_options_in_fragments(self):
        self._write_config_fragment_file_with_separator_conversion("fragment.json", """{
            api_key: "abcdefg",
            agent_log_path: "/var/silly1",
            http_proxy: "http://foo.com",
            https_proxy: "https://bar.com",
        }
        """)

        self._write_file_with_separator_conversion("""{
        }
        """)

        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals( config.api_key, "abcdefg" )
        self.assertEquals( config.agent_log_path, "/var/silly1" )
        self.assertEqual(config.network_proxies, {"http": "http://foo.com", 'https': 'https://bar.com'})

    def test_global_duplicate_options_in_fragments(self):
        self._write_config_fragment_file_with_separator_conversion("fragment.json", """{
            api_key: "abcdefg",
            agent_log_path: "/var/silly1",
            http_proxy: "http://foo.com",
            https_proxy: "https://bar.com",
        }
        """)

        self._write_file_with_separator_conversion("""{
            agent_log_path: "/var/silly1",
        }
        """)

        config = self._create_test_configuration_instance()
        self.assertRaises( BadConfiguration, config.parse )


    def test_json_array_substitution(self):
        self._write_file_with_separator_conversion(""" {
            import_vars: [ "TEST_VAR", "DIR_VAR" ],
            api_key: "hi$TEST_VAR",
            logs: [ { path:"/var/log/tomcat6/$DIR_VAR.log" }]
          }
        """)

        os.environ['TEST_VAR'] = 'bye'
        os.environ['DIR_VAR'] = 'ok'

        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, 'hibye')
        self.assertPathEquals(config.log_configs[0].get_string('path'), '/var/log/tomcat6/ok.log')

    def test_empty_substitution(self):
        self._write_file_with_separator_conversion(""" {
            import_vars: [ "UNDEFINED_VAR" ],
            api_key: "hi$UNDEFINED_VAR",
          }
        """)

        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, 'hi')

    def test_import_vars_in_configuration_directory(self):
        os.environ['TEST_VAR'] = 'bye'
        self._write_file_with_separator_conversion(""" { api_key: "hi there"
            logs: [ { path:"/var/log/tomcat6/access.log" }],
            server_attributes: {  serverHost:"foo.com" }
          }
        """)

        self._write_config_fragment_file_with_separator_conversion('nginx.json', """ {
           import_vars: [ "TEST_VAR" ],
           logs: [ { path: "/var/log/nginx/$TEST_VAR.log" } ],
           server_attributes: { webServer:"true"}
          }
        """)

        config = self._create_test_configuration_instance()
        config.parse()

        self.assertEquals(len(config.additional_file_paths), 1)
        additional_paths = list(config.additional_file_paths)
        additional_paths.sort()
        self.assertTrue(additional_paths[0].endswith('nginx.json'))

        self.assertEquals(len(config.log_configs), 3)
        self.assertPathEquals(config.log_configs[0].get_string('path'), '/var/log/tomcat6/access.log')
        self.assertPathEquals(config.log_configs[1].get_string('path'), '/var/log/nginx/bye.log')
        self.assertEquals(config.log_configs[0].get_json_array('sampling_rules'), JsonArray())

        self.assertEquals(config.server_attributes['webServer'], 'true')
        self.assertEquals(config.server_attributes['serverHost'], 'foo.com')


class TestParseArrayOfStrings(TestConfigurationBase):

    def test_none(self):
        self.assertIsNone(parse_array_of_strings(None))

    def test_empty_string(self):
        self.assertEqual(parse_array_of_strings(''), ArrayOfStrings())

    def test_list(self):
        self.assertEqual(parse_array_of_strings('a, b, c'), ArrayOfStrings(['a', 'b', 'c']))


class TestConvertConfigParam(TestConfigurationBase):

    def test_none_to_anything(self):
        """"""
        self.assertRaises(BadConfiguration, lambda: convert_config_param('dummy_field', None, str))
        self.assertRaises(BadConfiguration, lambda: convert_config_param('dummy_field', None, bool))
        self.assertRaises(BadConfiguration, lambda: convert_config_param('dummy_field', None, int))
        self.assertRaises(BadConfiguration, lambda: convert_config_param('dummy_field', None, float))
        self.assertRaises(BadConfiguration, lambda: convert_config_param('dummy_field', None, list))
        self.assertRaises(BadConfiguration, lambda: convert_config_param('dummy_field', None, JsonArray))
        self.assertRaises(BadConfiguration, lambda: convert_config_param('dummy_field', None, JsonObject))
        self.assertRaises(BadConfiguration, lambda: convert_config_param('dummy_field', None, ArrayOfStrings))

    def test_empty_string(self):
        self.assertEqual('', convert_config_param('dummy_field', '', str))
        self.assertEqual(False, convert_config_param('dummy_field', '', bool))
        self.assertRaises(BadConfiguration, lambda: convert_config_param('dummy_field', '', int))
        self.assertRaises(BadConfiguration, lambda: convert_config_param('dummy_field', '', float))
        self.assertEqual(ArrayOfStrings(), convert_config_param('dummy_field', '', ArrayOfStrings))
        self.assertEqual(ArrayOfStrings(),
                         convert_config_param('dummy_field', '', SpaceAndCommaSeparatedArrayOfStrings))
        self.assertRaises(IndexError, lambda: convert_config_param('dummy_field', '', JsonArray))
        self.assertRaises(IndexError, lambda: convert_config_param('dummy_field', '', JsonArray))


class TestGetConfigFromEnv(TestConfigurationBase):

    def test_get_empty_array_of_string(self):
        os.environ['SCALYR_K8S_IGNORE_NAMESPACES'] = ''
        self.assertEqual(ArrayOfStrings(),
                         get_config_from_env('k8s_ignore_namespaces', convert_to=SpaceAndCommaSeparatedArrayOfStrings))

        os.environ['SCALYR_K8S_IGNORE_NAMESPACES'] = 'a, b, c'
        self.assertEqual(ArrayOfStrings(['a', 'b', 'c']),
                         get_config_from_env('k8s_ignore_namespaces', convert_to=SpaceAndCommaSeparatedArrayOfStrings))

        del os.environ['SCALYR_K8S_IGNORE_NAMESPACES']
        self.assertIsNone(get_config_from_env('k8s_ignore_namespaces', convert_to=SpaceAndCommaSeparatedArrayOfStrings))

    def test_get_empty_string(self):
        os.environ['SCALYR_K8S_API_URL'] = ''
        self.assertEqual('', get_config_from_env('k8s_api_url', convert_to=str))

        del os.environ['SCALYR_K8S_API_URL']
        self.assertIsNone(get_config_from_env('k8s_api_url', convert_to=str))
