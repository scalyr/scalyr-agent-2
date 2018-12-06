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


__author__ = 'czerwin@scalyr.com'

import os
import tempfile

from scalyr_agent.configuration import Configuration, BadConfiguration
from scalyr_agent.json_lib import JsonObject, JsonArray
from scalyr_agent.json_lib import parse as parse_json, serialize as serialize_json
from scalyr_agent.platform_controller import DefaultPaths

from scalyr_agent.test_base import ScalyrTestCase


class TestConfiguration(ScalyrTestCase):
    def setUp(self):
        self.__config_dir = tempfile.mkdtemp()
        self.__config_file = os.path.join(self.__config_dir, 'agent.json')
        self.__config_fragments_dir = os.path.join(self.__config_dir, 'agent.d')
        os.makedirs(self.__config_fragments_dir)
        if os.environ.get('scalyr_api_key'):
            del os.environ['scalyr_api_key']

    def test_basic_case(self):
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ { path:"/var/log/tomcat6/access.log"} ]
          }
        """)
        config = self.__create_test_configuration_instance()
        config.parse()
        self.assertEquals(config.api_key, "hi there")
        self.assertPathEquals(config.agent_log_path, '/var/log/scalyr-agent-2')
        self.assertPathEquals(config.agent_data_path, '/var/lib/scalyr-agent-2')
        self.assertEquals(config.additional_monitor_module_paths, '')
        self.assertEquals(config.config_directory, self.__config_fragments_dir)
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
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there"
          }
        """)

        config = self.__create_test_configuration_instance()
        config.parse()
        self.assertEquals(config.api_key, "hi there")
        self.assertEquals(len(config.log_configs), 1)

        self.assertPathEquals(config.log_configs[0].get_string('path'), '/var/log/scalyr-agent-2/agent.log')

    def test_overriding_basic_settings(self):
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there",
            agent_log_path: "/var/silly1",
            agent_data_path: "/var/silly2",
            additional_monitor_module_paths: "silly3",
            config_directory: "silly4",
            implicit_metric_monitor: false,
            implicit_agent_log_collection: false,
            use_unsafe_debugging: true,
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
        config = self.__create_test_configuration_instance()
        config.parse()
        self.assertEquals(config.api_key, "hi there")
        self.assertPathEquals(config.agent_log_path, '/var/silly1')
        self.assertPathEquals(config.agent_data_path, '/var/silly2')
        self.assertEquals(config.additional_monitor_module_paths, 'silly3')
        self.assertEquals(config.config_directory, os.path.join(self.__config_dir, 'silly4'))
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
        self.__write_file_with_separator_conversion(""" {
            logs: [ { path:"/var/log/tomcat6/access.log"} ]
          }
        """)

        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_non_string_value(self):
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there",
            agent_log_path: [ "hi" ],
          }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_non_json_attributes(self):
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there",
            server_attributes: [ "hi" ],
          }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_non_string_attribute_values(self):
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there",
            server_attributes: { hi: [ 1 ] },
          }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_non_bool_value(self):
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there",
            implicit_metric_monitor: [ 1 ],
          }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_no_https_proxy(self):
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there",
            http_proxy: "http://bar.com",
          }
        """)
        config = self.__create_test_configuration_instance()
        config.parse()
        self.assertEqual(config.network_proxies, {"http": "http://bar.com"})

    def test_no_http_proxy(self):
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there",
            https_proxy: "https://bar.com",
          }
        """)
        config = self.__create_test_configuration_instance()
        config.parse()
        self.assertEqual(config.network_proxies, {"https": "https://bar.com"})

    def test_sampling_rules(self):
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { match_expression: "INFO", sampling_rate: 0},
                                { match_expression: ".*error.*=foo", sampling_rate: 0.2 } ],
            }]
          }
        """)
        config = self.__create_test_configuration_instance()
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
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { sampling_rate: 0} ]
          }] }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Bad regular expression.
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { match_expression: "[a", sampling_rate: 0} ]
          }] }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Missing sampling.
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { match_expression: "INFO"} ]
          }] }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Not number for percentage.
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { match_expression: "INFO", sampling_rate: true} ]
          }] }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Bad percentage.
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { match_expression: "INFO", sampling_rate: 2.0} ]
          }] }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_redaction_rules(self):
        self.__write_file_with_separator_conversion(""" {
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
        config = self.__create_test_configuration_instance()
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
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              redaction_rules: [ { replacement: "password=foo"} ],
            }] }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Match expression is not a regexp.
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              redaction_rules: [ { match_expression: "[a" } ],
            }] }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Replacement is not a string.
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              redaction_rules: [ { match_expression: "a", replacement: [ true ] } ],
            }] }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_configuration_directory(self):
        self.__write_file_with_separator_conversion(""" { api_key: "hi there"
            logs: [ { path:"/var/log/tomcat6/access.log" }],
            server_attributes: {  serverHost:"foo.com" }
          }
        """)

        self.__write_config_fragment_file_with_separator_conversion('nginx.json', """ {
           logs: [ { path: "/var/log/nginx/access.log" } ],
           server_attributes: { webServer:"true"}
          }
        """)

        self.__write_config_fragment_file_with_separator_conversion('apache.json', """ {
           logs: [ { path: "/var/log/apache/access.log" } ]
          }
        """)

        config = self.__create_test_configuration_instance()
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
        self.__write_file_with_separator_conversion(""" {
            logs: [ { path:"/var/log/tomcat6/access.log" }],
          }
        """)

        self.__write_config_fragment_file_with_separator_conversion('nginx.json', """ {
           api_key: "hi there",
           scalyr_server: "foobar",
           logs: [ { path: "/var/log/nginx/access.log" } ],
          }
        """)

        config = self.__create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.scalyr_server, 'foobar')
        self.assertEquals(config.api_key, 'hi there')

    def test_bad_fields_in_configuration_directory(self):
        self.__write_file_with_separator_conversion(""" { api_key: "hi there"
            logs: [ { path:"/var/log/tomcat6/access.log" }]
          }
        """)

        self.__write_config_fragment_file_with_separator_conversion('nginx.json', """ {
           api_key: "should cause an error",
           logs: [ { path: "/var/log/nginx/access.log" } ]
          }
        """)

        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_multiple_scalyr_servers_in_configuration_directory(self):
        self.__write_file_with_separator_conversion(""" { api_key: "hi there", scalyr_server: "test1",
            logs: [ { path:"/var/log/tomcat6/access.log" }]
          }
        """)

        self.__write_config_fragment_file_with_separator_conversion('nginx.json', """ {
           scalyr_server: "should cause an error",
           logs: [ { path: "/var/log/nginx/access.log" } ]
          }
        """)

        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_ignore_non_json_files_in_config_dir(self):
        self.__write_file_with_separator_conversion(""" { api_key: "hi there"
            logs: [ { path:"/var/log/tomcat6/access.log" }]
          }
        """)

        self.__write_config_fragment_file_with_separator_conversion('nginx', """ {
           logs: [ { path: "/var/log/nginx/access.log" } ]
          }
        """)

        config = self.__create_test_configuration_instance()
        config.parse()

        self.assertEquals(len(config.log_configs), 2)

    def test_parser_specification(self):
        self.__write_file_with_separator_conversion(""" {
            implicit_agent_log_collection: false,
            api_key: "hi there",
            logs: [ { path: "/tmp/foo.txt",
                      parser: "foo-parser"} ]
          }
        """)
        config = self.__create_test_configuration_instance()
        config.parse()
        self.assertEquals(len(config.log_configs), 1)
        self.assertEquals(config.log_configs[0]['attributes']['parser'], 'foo-parser')

    def test_monitors(self):
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there",
            monitors: [ { module: "httpPuller"} ]
          }
        """)
        config = self.__create_test_configuration_instance()
        config.parse()

        self.assertEquals(len(config.monitor_configs), 1)
        self.assertEquals(len(config.log_configs), 1)
        self.assertEquals(config.monitor_configs[0].get_string('module'), 'httpPuller')
        self.assertEquals(config.monitor_configs[0].get_string('log_path'), 'httpPuller.log')

        self.assertPathEquals(config.log_configs[0].get_string('path'), '/var/log/scalyr-agent-2/agent.log')

    def test_parse_log_config(self):
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there"
          }
        """)
        config = self.__create_test_configuration_instance()
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
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there"
          }
        """)

        config = self.__create_test_configuration_instance()
        config.parse()

        parsed_monitor_config = config.parse_monitor_config({
            "module": "foo"
        })

        self.assertEquals(parsed_monitor_config['module'], 'foo')

    def test_equivalent_configuration(self):
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ { path:"/var/log/tomcat6/access.log"} ]
          }
        """)
        config_a = self.__create_test_configuration_instance()
        config_a.parse()

        config_b = self.__create_test_configuration_instance()
        config_b.parse()

        self.assertTrue(config_a.equivalent(config_b))

        # Now write a new file that is slightly different.
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there",
            logs: [ { path:"/var/log/nginx/access.log"} ]
          }
        """)

        config_b = self.__create_test_configuration_instance()
        config_b.parse()

        self.assertFalse(config_a.equivalent(config_b))

    def test_equivalent_configuration_ignore_debug_level(self):
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there",
          }
        """)
        config_a = self.__create_test_configuration_instance()
        config_a.parse()

        # Now write a new file that is slightly different.
        self.__write_file_with_separator_conversion(""" {
            api_key: "hi there",
            debug_level: 1,
          }
        """)

        config_b = self.__create_test_configuration_instance()
        config_b.parse()

        # Should be not equivalent when we aren't ignoring debug_level,
        # but equivalent when we are.
        self.assertFalse(config_a.equivalent(config_b))
        self.assertEquals(config_b.debug_level, 1)

        self.assertTrue(config_a.equivalent(config_b, exclude_debug_level=True))
        self.assertEquals(config_b.debug_level, 1)

    def test_multiple_calls_to_bad_config(self):
        self.__write_file_with_separator_conversion(""" {
            logs: [ { path:"/var/log/tomcat6/access.log"} ]
          }
        """)

        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        error_seen = False
        try:
            self.assertTrue(config.agent_log_path is not None)
        except BadConfiguration:
            error_seen = True

        self.assertTrue(error_seen)

    def test_substitution(self):
        self.__write_file_with_separator_conversion(""" {
            import_vars: [ "TEST_VAR" ],
            api_key: "hi$TEST_VAR",
          }
        """)

        os.environ['TEST_VAR'] = 'bye'
        config = self.__create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, 'hibye')

    def test_substitution_with_default(self):
        self.__write_file_with_separator_conversion(""" {
            import_vars: [ {var: "UNDEFINED_VAR", default: "foo" } ],
            api_key: "hi$UNDEFINED_VAR",
          }
        """)

        config = self.__create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, 'hifoo')

    def test_substitution_with_unused_default(self):
        self.__write_file_with_separator_conversion(""" {
            import_vars: [ {var: "TEST_VAR2", default: "foo" } ],
            api_key: "hi$TEST_VAR2",
          }
        """)

        os.environ['TEST_VAR2'] = 'bar'
        config = self.__create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, 'hibar')

    def test_substitution_with_empty_var(self):
        self.__write_file_with_separator_conversion(""" {
            import_vars: [ {var: "TEST_VAR2", default: "foo" } ],
            api_key: "hi$TEST_VAR2",
          }
        """)

        os.environ['TEST_VAR2'] = ''
        config = self.__create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, 'hifoo')

    def test_api_key_override_no_override(self):
        self.__write_file_with_separator_conversion(""" {
            logs: [ { path:"/var/log/tomcat6/$DIR_VAR.log" }],
            api_key: "abcd1234",
          }
        """)

        config = self.__create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, 'abcd1234')

    def test_api_key_override_empty_override(self):
        self.__write_file_with_separator_conversion(""" {
            logs: [ { path:"/var/log/tomcat6/$DIR_VAR.log" }],
            api_key: "abcd1234",
          }
        """)
        os.environ['scalyr_api_key'] = ''

        config = self.__create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, 'abcd1234')

    def test_api_key_override_ignore_env(self):
        self.__write_file_with_separator_conversion(""" {
            logs: [ { path:"/var/log/tomcat6/$DIR_VAR.log" }],
            api_key: "abcd1234",
          }
        """)
        os.environ['scalyr_api_key'] = "xyz"

        config = self.__create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, 'abcd1234')

    def test_api_key_override_use_env(self):
        self.__write_file_with_separator_conversion(""" {
            logs: [ { path:"/var/log/tomcat6/$DIR_VAR.log" }]
          }
        """)
        os.environ['scalyr_api_key'] = "xyz"

        config = self.__create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, 'xyz')

    def test_duplicate_api_key(self):
        self.__write_file_with_separator_conversion("""{
            api_key: "abcd1234",
        }
        """)

        self.__write_config_fragment_file_with_separator_conversion("apikey.json", """{
            api_key: "abcd1234",
        }
        """)

        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_global_options_in_fragments(self):
        self.__write_config_fragment_file_with_separator_conversion("fragment.json", """{
            api_key: "abcdefg",
            agent_log_path: "/var/silly1",
            http_proxy: "http://foo.com",
            https_proxy: "https://bar.com",
        }
        """)

        self.__write_file_with_separator_conversion("""{
        }
        """)

        config = self.__create_test_configuration_instance()
        config.parse()

        self.assertEquals( config.api_key, "abcdefg" )
        self.assertEquals( config.agent_log_path, "/var/silly1" )
        self.assertEqual(config.network_proxies, {"http": "http://foo.com", 'https': 'https://bar.com'})

    def test_global_duplicate_options_in_fragments(self):
        self.__write_config_fragment_file_with_separator_conversion("fragment.json", """{
            api_key: "abcdefg",
            agent_log_path: "/var/silly1",
            http_proxy: "http://foo.com",
            https_proxy: "https://bar.com",
        }
        """)

        self.__write_file_with_separator_conversion("""{
            agent_log_path: "/var/silly1",
        }
        """)

        config = self.__create_test_configuration_instance()
        self.assertRaises( BadConfiguration, config.parse )


    def test_json_array_substitution(self):
        self.__write_file_with_separator_conversion(""" {
            import_vars: [ "TEST_VAR", "DIR_VAR" ],
            api_key: "hi$TEST_VAR",
            logs: [ { path:"/var/log/tomcat6/$DIR_VAR.log" }]
          }
        """)

        os.environ['TEST_VAR'] = 'bye'
        os.environ['DIR_VAR'] = 'ok'

        config = self.__create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, 'hibye')
        self.assertPathEquals(config.log_configs[0].get_string('path'), '/var/log/tomcat6/ok.log')

    def test_empty_substitution(self):
        self.__write_file_with_separator_conversion(""" {
            import_vars: [ "UNDEFINED_VAR" ],
            api_key: "hi$UNDEFINED_VAR",
          }
        """)

        config = self.__create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, 'hi')

    def test_import_vars_in_configuration_directory(self):
        os.environ['TEST_VAR'] = 'bye'
        self.__write_file_with_separator_conversion(""" { api_key: "hi there"
            logs: [ { path:"/var/log/tomcat6/access.log" }],
            server_attributes: {  serverHost:"foo.com" }
          }
        """)

        self.__write_config_fragment_file_with_separator_conversion('nginx.json', """ {
           import_vars: [ "TEST_VAR" ],
           logs: [ { path: "/var/log/nginx/$TEST_VAR.log" } ],
           server_attributes: { webServer:"true"}
          }
        """)

        config = self.__create_test_configuration_instance()
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

    def __write_file_with_separator_conversion(self, contents):
        contents = serialize_json(self.__convert_separators(parse_json(contents)))

        fp = open(self.__config_file, 'w')
        fp.write(contents)
        fp.close()

    def __write_config_fragment_file_with_separator_conversion(self, file_path, contents):
        contents = serialize_json(self.__convert_separators(parse_json(contents)))

        full_path = os.path.join(self.__config_fragments_dir, file_path)
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

    def __create_test_configuration_instance(self):
        """Creates an instance of a Configuration file for testing.

        @return:  The test instance
        @rtype: Configuration
        """
        default_paths = DefaultPaths(self.convert_path('/var/log/scalyr-agent-2'),
                                     self.convert_path('/etc/scalyr-agent-2/agent.json'),
                                     self.convert_path('/var/lib/scalyr-agent-2'))

        return Configuration(self.__config_file, default_paths)

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
