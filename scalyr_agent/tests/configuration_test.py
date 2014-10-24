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
from scalyr_agent.platform_controller import DefaultPaths

__author__ = 'czerwin@scalyr.com'

import os
import tempfile
import unittest

from scalyr_agent.configuration import Configuration, BadConfiguration
from scalyr_agent.json_lib import JsonObject, JsonArray


class TestConfiguration(unittest.TestCase):
    def setUp(self):
        self.__config_dir = tempfile.mkdtemp()
        self.__config_file = os.path.join(self.__config_dir, 'agent.json')
        self.__config_fragments_dir = os.path.join(self.__config_dir, 'agent.d')
        os.makedirs(self.__config_fragments_dir)

    def test_basic_case(self):
        self.__write_file(""" {
            api_key: "hi there",
            logs: [ { path:"/var/log/tomcat6/access.log"} ]
          }
        """)
        config = self.__create_test_configuration_instance()
        config.parse()
        self.assertEquals(config.api_key, "hi there")
        self.assertEquals(config.agent_log_path, '/var/log/scalyr-agent-2')
        self.assertEquals(config.agent_data_path, '/var/lib/scalyr-agent-2')
        self.assertEquals(config.additional_monitor_module_paths, '')
        self.assertEquals(config.config_directory, self.__config_fragments_dir)
        self.assertEquals(config.implicit_metric_monitor, True)
        self.assertEquals(config.implicit_agent_log_collection, True)
        self.assertFalse(config.use_unsafe_debugging)
        self.assertEquals(config.scalyr_server, 'https://agent.scalyr.com')
        self.assertEquals(len(config.server_attributes), 1)
        self.assertTrue('serverHost' in config.server_attributes)

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
        self.assertTrue(config.ca_cert_path.endswith('ca_certs.crt'))
        self.assertTrue(config.verify_server_certificate)

        self.assertEquals(len(config.logs), 4)
        self.assertEquals(config.logs[0].config.get_string('path'), '/var/log/tomcat6/access.log')
        self.assertEquals(config.logs[0].config.get_json_object('attributes'), JsonObject())
        self.assertEquals(config.logs[0].config.get_json_array('sampling_rules'), JsonArray())
        self.assertEquals(config.logs[0].config.get_json_array('redaction_rules'), JsonArray())
        self.assertEquals(config.logs[1].config.get_string('path'), '/var/log/scalyr-agent-2/agent.log')
        self.assertEquals(config.logs[2].config.get_string('path'), '/var/log/scalyr-agent-2/linux_system_metrics.log')
        self.assertEquals(config.logs[3].config.get_string('path'), '/var/log/scalyr-agent-2/linux_process_metrics.log')

        self.assertEquals(len(config.monitors), 2)
        self.assertEquals(config.monitors[0].config.get_string('module'),
                          'scalyr_agent.builtin_monitors.linux_system_metrics')
        self.assertEquals(config.monitors[0].config.get_string('log_path'),
                          'scalyr_agent.builtin_monitors.linux_system_metrics.log')
        self.assertEquals(config.monitors[1].config.get_string('module'),
                          'scalyr_agent.builtin_monitors.linux_process_metrics')
        self.assertEquals(config.monitors[1].config.get_string('log_path'),
                          'scalyr_agent.builtin_monitors.linux_process_metrics.log')

    def test_empty_config(self):
        self.__write_file(""" {
            api_key: "hi there"
          }
        """)

        config = self.__create_test_configuration_instance()
        config.parse()
        self.assertEquals(config.api_key, "hi there")
        self.assertEquals(len(config.logs), 3)

        self.assertEquals(config.logs[0].config.get_string('path'), '/var/log/scalyr-agent-2/agent.log')
        self.assertEquals(config.logs[1].config.get_string('path'), '/var/log/scalyr-agent-2/linux_system_metrics.log')
        self.assertEquals(config.logs[2].config.get_string('path'), '/var/log/scalyr-agent-2/linux_process_metrics.log')

    def test_overriding_basic_settings(self):
        self.__write_file(""" {
            api_key: "hi there",
            agent_log_path: "silly1",
            agent_data_path: "silly2",
            additional_monitor_module_paths: "silly3",
            config_directory: "silly4",
            implicit_metric_monitor: false,
            implicit_agent_log_collection: false,
            use_unsafe_debugging: true,
            scalyr_server: "noland.scalyr.com",
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
            logs: [ { path:"/var/log/tomcat6/access.log"} ]
          }
        """)
        config = self.__create_test_configuration_instance()
        config.parse()
        self.assertEquals(config.api_key, "hi there")
        self.assertEquals(config.agent_log_path, 'silly1')
        self.assertEquals(config.agent_data_path, 'silly2')
        self.assertEquals(config.additional_monitor_module_paths, 'silly3')
        self.assertEquals(config.config_directory, os.path.join(self.__config_dir, 'silly4'))
        self.assertEquals(config.implicit_metric_monitor, False)
        self.assertEquals(config.implicit_agent_log_collection, False)
        self.assertTrue(config.use_unsafe_debugging)
        self.assertEquals(config.scalyr_server, 'noland.scalyr.com')
        self.assertEquals(len(config.server_attributes), 2)
        self.assertEquals(config.server_attributes['region'], 'us-east')

        self.assertEquals(config.max_allowed_request_size, 2000000)
        self.assertEquals(config.min_allowed_request_size, 7000)

        self.assertEquals(config.min_request_spacing_interval, 2.0)
        self.assertEquals(config.max_request_spacing_interval, 10.0)

        self.assertEquals(config.high_water_bytes_sent, 50000)
        self.assertEquals(config.high_water_request_spacing_adjustment, 2.0)
        self.assertEquals(config.low_water_bytes_sent, 5000)
        self.assertEquals(config.low_water_request_spacing_adjustment, -1.0)

        self.assertEquals(config.failure_request_spacing_adjustment, 2.0)
        self.assertEquals(config.request_too_large_adjustment, 0.75)
        self.assertEquals(config.debug_level, 1)
        self.assertEquals(config.request_deadline, 30.0)
        self.assertEquals(config.ca_cert_path, '/var/lib/foo.pem')
        self.assertFalse(config.verify_server_certificate)

    def test_missing_api_key(self):
        self.__write_file(""" {
            logs: [ { path:"/var/log/tomcat6/access.log"} ]
          }
        """)

        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_non_string_value(self):
        self.__write_file(""" {
            api_key: "hi there",
            agent_log_path: [ "hi" ],
          }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_non_json_attributes(self):
        self.__write_file(""" {
            api_key: "hi there",
            server_attributes: [ "hi" ],
          }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_non_string_attribute_values(self):
        self.__write_file(""" {
            api_key: "hi there",
            server_attributes: { hi: [ 1 ] },
          }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_non_bool_value(self):
        self.__write_file(""" {
            api_key: "hi there",
            implicit_metric_monitor: [ 1 ],
          }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_sampling_rules(self):
        self.__write_file(""" {
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

        self.assertEquals(len(config.logs), 4)
        sampling_rules = config.logs[0].config.get_json_array('sampling_rules')
        self.assertEquals(len(sampling_rules), 2)
        self.assertEquals(sampling_rules.get_json_object(0).get_string("match_expression"), "INFO")
        self.assertEquals(sampling_rules.get_json_object(0).get_float("sampling_rate"), 0)
        self.assertEquals(sampling_rules.get_json_object(1).get_string("match_expression"), ".*error.*=foo")
        self.assertEquals(sampling_rules.get_json_object(1).get_float("sampling_rate"), 0.2)

    def test_bad_sampling_rules(self):
        # Missing match_expression.
        self.__write_file(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { sampling_rate: 0} ]
          }] }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Bad regular expression.
        self.__write_file(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { match_expression: "[a", sampling_rate: 0} ]
          }] }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Missing sampling.
        self.__write_file(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { match_expression: "INFO"} ]
          }] }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Not number for percentage.
        self.__write_file(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { match_expression: "INFO", sampling_rate: true} ]
          }] }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Bad percentage.
        self.__write_file(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              sampling_rules: [ { match_expression: "INFO", sampling_rate: 2.0} ]
          }] }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_redaction_rules(self):
        self.__write_file(""" {
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

        self.assertEquals(len(config.logs), 4)
        redaction_rules = config.logs[0].config.get_json_array('redaction_rules')
        self.assertEquals(len(redaction_rules), 3)
        self.assertEquals(redaction_rules.get_json_object(0).get_string("match_expression"), "password=")
        self.assertEquals(redaction_rules.get_json_object(0).get_string("replacement"), "password=foo")
        self.assertEquals(redaction_rules.get_json_object(1).get_string("match_expression"), "password=.*")
        self.assertEquals(redaction_rules.get_json_object(1).get_string("replacement"), "password=foo")
        self.assertEquals(redaction_rules.get_json_object(2).get_string("match_expression"), "password=")
        self.assertEquals(redaction_rules.get_json_object(2).get_string("replacement"), "")

    def test_bad_redaction_rules(self):
        # Missing match expression.
        self.__write_file(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              redaction_rules: [ { replacement: "password=foo"} ],
            }] }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Match expression is not a regexp.
        self.__write_file(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              redaction_rules: [ { match_expression: "[a" } ],
            }] }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

        # Replacement is not a string.
        self.__write_file(""" {
            api_key: "hi there",
            logs: [ {
              path:"/var/log/tomcat6/access.log",
              redaction_rules: [ { match_expression: "a", replacement: [ true ] } ],
            }] }
        """)
        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_configuration_directory(self):
        self.__write_file(""" { api_key: "hi there"
            logs: [ { path:"/var/log/tomcat6/access.log" }],
            server_attributes: {  serverHost:"foo.com" }
          }
        """)

        self.__write_config_fragment_file('nginx.json', """ {
           logs: [ { path: "/var/log/nginx/access.log" } ],
           server_attributes: { webServer:"true"}
          }
        """)

        self.__write_config_fragment_file('apache.json', """ {
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

        self.assertEquals(len(config.logs), 6)
        self.assertEquals(config.logs[0].config.get_string('path'), '/var/log/tomcat6/access.log')
        self.assertEquals(config.logs[1].config.get_string('path'), '/var/log/apache/access.log')
        self.assertEquals(config.logs[2].config.get_string('path'), '/var/log/nginx/access.log')
        self.assertEquals(config.logs[0].config.get_json_array('sampling_rules'), JsonArray())

        self.assertEquals(config.server_attributes['webServer'], 'true')
        self.assertEquals(config.server_attributes['serverHost'], 'foo.com')

    def test_bad_fields_in_configuration_directory(self):
        self.__write_file(""" { api_key: "hi there"
            logs: [ { path:"/var/log/tomcat6/access.log" }]
          }
        """)

        self.__write_config_fragment_file('nginx.json', """ {
           api_key: "should cause an error",
           logs: [ { path: "/var/log/nginx/access.log" } ]
          }
        """)

        config = self.__create_test_configuration_instance()
        self.assertRaises(BadConfiguration, config.parse)

    def test_ignore_non_json_files_in_config_dir(self):
        self.__write_file(""" { api_key: "hi there"
            logs: [ { path:"/var/log/tomcat6/access.log" }]
          }
        """)

        self.__write_config_fragment_file('nginx', """ {
           logs: [ { path: "/var/log/nginx/access.log" } ]
          }
        """)

        config = self.__create_test_configuration_instance()
        config.parse()

        self.assertEquals(len(config.logs), 4)

    def test_parser_specification(self):
        self.__write_file(""" {
            implicit_agent_log_collection: false,
            api_key: "hi there",
            logs: [ { path: "/tmp/foo.txt",
                      parser: "foo-parser"} ]
          }
        """)
        config = self.__create_test_configuration_instance()
        config.parse()
        self.assertEquals(len(config.logs), 3)
        self.assertEquals(config.logs[0].config['attributes']['parser'], 'foo-parser')

    def test_monitors(self):
        self.__write_file(""" {
            api_key: "hi there",
            monitors: [ { module: "httpPuller"} ]
          }
        """)
        config = self.__create_test_configuration_instance()
        config.parse()

        self.assertEquals(len(config.monitors), 3)
        self.assertEquals(len(config.logs), 4)
        self.assertEquals(config.monitors[0].config.get_string('module'), 'httpPuller')
        self.assertEquals(config.monitors[0].config.get_string('log_path'), 'httpPuller.log')
        self.assertEquals(config.monitors[0].config.get_string('id'), '')

        self.assertEquals(config.logs[0].config.get_string('path'), '/var/log/scalyr-agent-2/agent.log')
        self.assertEquals(config.logs[1].config.get_string('path'), '/var/log/scalyr-agent-2/httpPuller.log')
        self.assertEquals(config.logs[1].config.get_json_object('attributes').get_string('parser'), 'agent-metrics')
        self.assertEquals(config.logs[2].config.get_string('path'), '/var/log/scalyr-agent-2/linux_system_metrics.log')

    def test_multiple_modules(self):
        self.__write_file(""" {
            api_key: "hi there",
            monitors: [ { module: "httpPuller"}, { module: "hithere.httpPuller" }, { module: "another"},
                        { module: "foo", id: "fixed_id" } ]
          }
        """)
        config = self.__create_test_configuration_instance()
        config.parse()

        self.assertEquals(len(config.monitors), 6)
        self.assertEquals(len(config.logs), 6)
        self.assertEquals(config.monitors[0].config.get_string('module'), 'httpPuller')
        self.assertEquals(config.monitors[0].config.get_string('log_path'), 'httpPuller.log')
        self.assertEquals(config.monitors[0].config.get_string('id'), '1')
        self.assertEquals(config.monitors[1].config.get_string('module'), 'hithere.httpPuller')
        self.assertEquals(config.monitors[1].config.get_string('log_path'), 'hithere.httpPuller.log')
        self.assertEquals(config.monitors[1].config.get_string('id'), '2')
        self.assertEquals(config.monitors[2].config.get_string('module'), 'another')
        self.assertEquals(config.monitors[2].config.get_string('log_path'), 'another.log')
        self.assertEquals(config.monitors[2].config.get_string('id'), '')
        self.assertEquals(config.monitors[3].config.get_string('module'), 'foo')
        self.assertEquals(config.monitors[3].config.get_string('log_path'), 'foo.log')
        self.assertEquals(config.monitors[3].config.get_string('id'), 'fixed_id')
        self.assertEquals(config.monitors[4].config.get_string('module'),
                          'scalyr_agent.builtin_monitors.linux_system_metrics')
        self.assertEquals(config.monitors[4].config.get_string('log_path'),
                          'scalyr_agent.builtin_monitors.linux_system_metrics.log')
        self.assertEquals(config.monitors[4].config.get_string('id'), '')
        self.assertEquals(config.monitors[5].config.get_string('module'),
                          'scalyr_agent.builtin_monitors.linux_process_metrics')
        self.assertEquals(config.monitors[5].config.get_string('log_path'),
                          'scalyr_agent.builtin_monitors.linux_process_metrics.log')
        self.assertEquals(config.monitors[5].config.get_string('id'), 'agent')

        self.assertEquals(config.logs[0].config.get_string('path'), '/var/log/scalyr-agent-2/agent.log')
        self.assertEquals(config.logs[1].config.get_string('path'), '/var/log/scalyr-agent-2/httpPuller.log')
        self.assertEquals(config.logs[2].config.get_string('path'), '/var/log/scalyr-agent-2/another.log')
        self.assertEquals(config.logs[3].config.get_string('path'), '/var/log/scalyr-agent-2/foo.log')
        self.assertEquals(config.logs[4].config.get_string('path'), '/var/log/scalyr-agent-2/linux_system_metrics.log')

    def test_equivalent_configuration(self):
        self.__write_file(""" {
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
        self.__write_file(""" {
            api_key: "hi there",
            logs: [ { path:"/var/log/nginx/access.log"} ]
          }
        """)

        config_b = self.__create_test_configuration_instance()
        config_b.parse()

        self.assertFalse(config_a.equivalent(config_b))

    def test_equivalent_configuration_ignore_debug_level(self):
        self.__write_file(""" {
            api_key: "hi there",
          }
        """)
        config_a = self.__create_test_configuration_instance()
        config_a.parse()

        # Now write a new file that is slightly different.
        self.__write_file(""" {
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
        self.__write_file(""" {
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
        self.__write_file(""" {
            import_vars: [ "TEST_VAR" ],
            api_key: "hi$TEST_VAR",
          }
        """)

        os.environ['TEST_VAR'] = 'bye'
        config = self.__create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, 'hibye')

    def test_json_array_substitution(self):
        self.__write_file(""" {
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
        self.assertEquals(config.logs[0].config.get_string('path'), '/var/log/tomcat6/ok.log')

    def test_empty_substitution(self):
        self.__write_file(""" {
            import_vars: [ "UNDEFINED_VAR" ],
            api_key: "hi$UNDEFINED_VAR",
          }
        """)

        config = self.__create_test_configuration_instance()
        config.parse()

        self.assertEquals(config.api_key, 'hi')

    def __write_file(self, contents):
        fp = open(self.__config_file, 'w')
        fp.write(contents)
        fp.close()

    def __write_config_fragment_file(self, file_path, contents):
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

        def log_factory(config):
            return TestConfiguration.LogObject(config)

        def monitor_factory(config, _):
            return TestConfiguration.MonitorObject(config)

        default_paths = DefaultPaths('/var/log/scalyr-agent-2', '/etc/scalyr-agent-2/agent.json',
                                     '/var/lib/scalyr-agent-2')

        monitors = [JsonObject(module='scalyr_agent.builtin_monitors.linux_system_metrics'),
                    JsonObject(module='scalyr_agent.builtin_monitors.linux_process_metrics',
                               pid='$$', id='agent')]
        return Configuration(self.__config_file, default_paths, monitors, log_factory, monitor_factory)