import os
from mock import patch, Mock

from scalyr_agent import scalyr_monitor
from scalyr_agent.builtin_monitors.kubernetes_monitor import KubernetesMonitor
from scalyr_agent.config_util import BadConfiguration
from scalyr_agent.configuration import Configuration
from scalyr_agent.copying_manager import CopyingManager
from scalyr_agent.monitors_manager import MonitorsManager
from scalyr_agent.json_lib.objects import ArrayOfStrings
from scalyr_agent.test_util import FakeAgentLogger, FakePlatform
from scalyr_agent.tests.configuration_test import TestConfigurationBase


class TestConfigurationK8s(TestConfigurationBase):
    """This test subclasses from TestConfiguration for easier exclusion in python 2.5 and below"""

    def _create_test_objects(self):
        config = self._create_test_configuration_instance()
        config.parse()

        # echee TODO: once AGENT-40 docker PR merges in, some of the test-setup code below can be eliminated and
        # reused from that PR (I moved common code into scalyr_agent/test_util
        def fake_init(self):
            # Initialize some requisite variables so that the k8s monitor loop can run
            self._KubernetesMonitor__container_checker = None
            self._KubernetesMonitor__namespaces_to_ignore = []
            self._KubernetesMonitor__include_controller_info = None
            self._KubernetesMonitor__report_container_metrics = None
            self._KubernetesMonitor__metric_fetcher = None
            self._set_ignore_namespaces()

        mock_logger = Mock()

        @patch.object(KubernetesMonitor, '_initialize', new=fake_init)
        def create_manager():
            scalyr_monitor.log = mock_logger
            return MonitorsManager(config, FakePlatform([]))

        monitors_manager = create_manager()
        return monitors_manager, config, mock_logger


    @patch('scalyr_agent.builtin_monitors.kubernetes_monitor.docker')
    def test_environment_aware_module_params(self, mock_docker):

        # Define test values here for all k8s and k8s_event monitor config params that are environment aware.
        # Be sure to use non-default test values
        TEST_INT = 123456789
        TEST_FLOAT = 1234567.89
        TEST_STRING = 'dummy string'
        TEST_PARSE_FORMAT = 'cri'
        TEST_ARRAY_OF_STRINGS = ['s1', 's2', 's3']
        STANDARD_PREFIX = '_STANDARD_PREFIX_'  # env var is SCALYR_<param_name>

        # The following map contains config params to be tested
        # config_param_name: (custom_env_name, test_value)
        k8s_testmap = {
            "container_check_interval": (STANDARD_PREFIX, TEST_INT, int),
            "docker_max_parallel_stats": (STANDARD_PREFIX, TEST_INT, int),
            "docker_percpu_metrics": (STANDARD_PREFIX, True, bool),
            "container_globs": (STANDARD_PREFIX, TEST_ARRAY_OF_STRINGS, ArrayOfStrings),
            "report_container_metrics": (STANDARD_PREFIX, False, bool),
            "report_k8s_metrics": (STANDARD_PREFIX, True, bool),
            "k8s_ignore_pod_sandboxes": (STANDARD_PREFIX, False, bool),
            "k8s_include_all_containers": (STANDARD_PREFIX, False, bool),
            "k8s_ignore_pod_sandboxes": (STANDARD_PREFIX, False, bool),
            "k8s_include_all_containers": (STANDARD_PREFIX, False, bool),
            "k8s_parse_format": (STANDARD_PREFIX, TEST_PARSE_FORMAT, str),
            "k8s_always_use_cri": (STANDARD_PREFIX, True, bool),
            "k8s_cri_query_filesystem": (STANDARD_PREFIX, True, bool),
            "k8s_always_use_docker": (STANDARD_PREFIX, True, bool),
            "k8s_kubelet_host_ip": (STANDARD_PREFIX, False, bool),
            "gather_k8s_pod_info": (STANDARD_PREFIX, True, bool),
        }

        k8s_events_testmap = {
            "max_log_size": ("SCALYR_K8S_MAX_LOG_SIZE", TEST_INT, int),
            "max_log_rotations": ("SCALYR_K8S_MAX_LOG_ROTATIONS", TEST_INT, int),
            "log_flush_delay": ("SCALYR_K8S_LOG_FLUSH_DELAY", TEST_FLOAT, float),
            "message_log": ("SCALYR_K8S_MESSAGE_LOG", TEST_STRING, str),
            "event_object_filter": ("SCALYR_K8S_EVENT_OBJECT_FILTER", TEST_ARRAY_OF_STRINGS, ArrayOfStrings),
            "leader_check_interval": ("SCALYR_K8S_LEADER_CHECK_INTERVAL", TEST_INT, int),
            "leader_node": ("SCALYR_K8S_LEADER_NODE", TEST_STRING, str),
            "check_labels": ("SCALYR_K8S_CHECK_LABELS", True, bool),
            "ignore_master": ("SCALYR_K8S_IGNORE_MASTER", False, bool),
        }

        # Fake the environment variables
        for map in [k8s_testmap, k8s_events_testmap]:
            for key, value in map.items():
                custom_name = value[0]
                env_name = ('SCALYR_%s' % key).upper() if custom_name == STANDARD_PREFIX else custom_name.upper()
                envar_value = str(value[1])
                if value[2] == ArrayOfStrings:
                    # Array of strings should be entered into environment in the user-preferred format
                    # which is without square brackets and quotes around each element
                    envar_value = envar_value[1:-1]  # strip square brackets
                    envar_value = envar_value.replace("'", '')
                else:
                    envar_value = envar_value.lower()  # lower() needed for proper bool encoding
                os.environ[env_name] = envar_value

        self._write_file_with_separator_conversion(""" {
            logs: [ { path:"/var/log/tomcat6/$DIR_VAR.log" }],
            api_key: "abcd1234",
        }      
        """)
        self._write_config_fragment_file_with_separator_conversion('k8s.json', """ {
            "monitors": [
                {
                    "module": "scalyr_agent.builtin_monitors.kubernetes_monitor",
                    "report_k8s_metrics": false,                    
                },
                {
                    "module": "scalyr_agent.builtin_monitors.kubernetes_events_monitor"
                }            
            ]
        }
        """)

        monitors_manager, config, mock_logger = self._create_test_objects()
        k8s_monitor = monitors_manager.monitors[0]
        k8s_events_monitor = monitors_manager.monitors[1]

        # All environment-aware params defined in the k8s and k8s_events monitors must be tested
        self.assertEquals(
            set(k8s_testmap.keys()),
            set(k8s_monitor._config._environment_aware_map.keys()))

        self.assertEquals(
            set(k8s_events_testmap.keys()),
            set(k8s_events_monitor._config._environment_aware_map.keys()))

        # Verify module-level conflicts between env var and config file are logged at module-creation time
        mock_logger.warn.assert_called_with(
            'Conflicting values detected between scalyr_agent.builtin_monitors.kubernetes_monitor config file '
            'parameter `report_k8s_metrics` and the environment variable `SCALYR_REPORT_K8S_METRICS`. '
            'Ignoring environment variable.',
            limit_once_per_x_secs=300,
            limit_key='config_conflict_scalyr_agent.builtin_monitors.kubernetes_monitor_report_k8s_metrics_SCALYR_REPORT_K8S_METRICS',
        )

        CopyingManager(config, monitors_manager.monitors)
        # Override Agent Logger to prevent writing to disk
        for monitor in monitors_manager.monitors:
            monitor._logger = FakeAgentLogger('fake_agent_logger')

        # Verify environment variable values propagate into kubernetes monitor MonitorConfig
        monitor_2_testmap = {
            k8s_monitor: k8s_testmap,
            k8s_events_monitor: k8s_events_testmap,
        }
        for monitor, testmap in monitor_2_testmap.items():
            for key, value in testmap.items():
                test_val, convert_to = value[1:]
                if key in ['report_k8s_metrics', 'api_key']:
                    # Keys were defined in config files so should not have changed
                    self.assertNotEquals(test_val, monitor._config.get(key, convert_to=convert_to))
                else:
                    # Keys were empty in config files so they take on environment values
                    materialized_value = monitor._config.get(key, convert_to=convert_to)
                    if hasattr(test_val, '__iter__'):
                        self.assertEquals([x1 for x1 in test_val], [x2 for x2 in materialized_value])
                    else:
                        self.assertEquals(test_val, materialized_value)

    def test_k8s_event_object_filter_from_config(self):
        self._write_file_with_separator_conversion(""" { 
            api_key: "hi there",
            logs: [ { path:"/var/log/tomcat6/access.log" }],
            monitors: [
                {
                    module: "scalyr_agent.builtin_monitors.kubernetes_events_monitor",
                    event_object_filter: ["CronJob", "DaemonSet", "Deployment"]
                }
            ]
          }
        """)
        config = self._create_test_configuration_instance()
        config.parse()

        test_manager = MonitorsManager(config, FakePlatform([]))
        k8s_event_monitor = test_manager.monitors[0]
        event_object_filter = k8s_event_monitor._config.get('event_object_filter')
        elems = ["CronJob", "DaemonSet", "Deployment"]
        self.assertNotEquals(elems, event_object_filter)  # list != JsonArray
        self.assertEquals(elems, [x for x in event_object_filter])

    def test_k8s_event_object_filter_from_environment_0(self):
        self._test_k8s_event_object_filter_from_environment('["CronJob", "DaemonSet", "Deployment"]')

    def test_k8s_event_object_filter_from_environment_1(self):
        self._test_k8s_event_object_filter_from_environment('"CronJob", "DaemonSet", "Deployment"')

    def test_k8s_event_object_filter_from_environment_2(self):
        self._test_k8s_event_object_filter_from_environment('CronJob, DaemonSet, Deployment')

    def test_k8s_event_object_filter_from_environment_3(self):
        self._test_k8s_event_object_filter_from_environment('CronJob,DaemonSet,Deployment')

    def _test_k8s_event_object_filter_from_environment(self, environment_value):
        elems = ["CronJob", "DaemonSet", "Deployment"]
        os.environ['SCALYR_K8S_EVENT_OBJECT_FILTER'] = environment_value
        self._write_file_with_separator_conversion(""" { 
            api_key: "hi there",
            logs: [ { path:"/var/log/tomcat6/access.log" }],
            monitors: [
                {
                    module: "scalyr_agent.builtin_monitors.kubernetes_events_monitor",                    
                }
            ]
          }
        """)
        config = self._create_test_configuration_instance()
        config.parse()

        test_manager = MonitorsManager(config, FakePlatform([]))
        k8s_event_monitor = test_manager.monitors[0]
        event_object_filter = k8s_event_monitor._config.get('event_object_filter')
        self.assertNotEquals(elems, event_object_filter)  # list != ArrayOfStrings
        self.assertEquals(type(event_object_filter), ArrayOfStrings)
        self.assertEquals(elems, list(event_object_filter))

    def test_k8s_events_disable(self):
        def _assert_environment_variable(env_var_name, env_var_value, expected_value):
            os.environ[env_var_name] = env_var_value
            self._write_file_with_separator_conversion(""" { 
                api_key: "hi there",
                logs: [ { path:"/var/log/tomcat6/access.log" }],
                monitors: [
                    {
                        module: "scalyr_agent.builtin_monitors.kubernetes_events_monitor",
                    }
                ]
              }
            """)
            config = self._create_test_configuration_instance()
            config.parse()

            test_manager = MonitorsManager(config, FakePlatform([]))
            k8s_event_monitor = test_manager.monitors[0]
            self.assertEquals(expected_value, k8s_event_monitor._KubernetesEventsMonitor__disable_monitor)

        # Legacy env variable is supported
        _assert_environment_variable('K8S_EVENTS_DISABLE', 't', True)
        _assert_environment_variable('K8S_EVENTS_DISABLE', 'T', True)
        _assert_environment_variable('K8S_EVENTS_DISABLE', 'true', True)
        _assert_environment_variable('K8S_EVENTS_DISABLE', 'True', True)
        _assert_environment_variable('K8S_EVENTS_DISABLE', 'TRUE', True)
        _assert_environment_variable('K8S_EVENTS_DISABLE', 'X', False)

        # And new environment variable likewise
        _assert_environment_variable('SCALYR_K8S_EVENTS_DISABLE', 'true', True)
        _assert_environment_variable('SCALYR_K8S_EVENTS_DISABLE', 'True', True)
        _assert_environment_variable('SCALYR_K8S_EVENTS_DISABLE', 'T', False)
        _assert_environment_variable('SCALYR_K8S_EVENTS_DISABLE', 'false', False)
        _assert_environment_variable('SCALYR_K8S_EVENTS_DISABLE', 'False', False)
        _assert_environment_variable('SCALYR_K8S_EVENTS_DISABLE', 'F', False)

    def test_k8s_ignore_namespaces(self):

        def _verify(expected):
            monitors_manager, config, mock_logger = self._create_test_objects()
            k8s_monitor = monitors_manager.monitors[0]
            result = k8s_monitor._get_ignore_namespaces()
            self.assertEquals(expected, result)

        def _test_k8s_ignore_namespaces_local(test_str, expected):
            k8s_config_line = ''
            if test_str is not None:
                k8s_config_line = ", k8s_ignore_namespaces: %s" % test_str

            self._write_file_with_separator_conversion(""" { 
                api_key: "hi there",
                logs: [ { path:"/var/log/tomcat6/access.log" }],
                monitors: [
                    {
                        module: "scalyr_agent.builtin_monitors.kubernetes_monitor"
                        %s
                    }
                ]
              }
            """ % k8s_config_line)
            _verify(expected)

        def _test_k8s_ignore_namespaces_global(test_str, expected):
            self._write_file_with_separator_conversion(""" { 
                api_key: "hi there",
                k8s_ignore_namespaces: %s,
                logs: [ { path:"/var/log/tomcat6/access.log" }],
                monitors: [
                    {
                        module: "scalyr_agent.builtin_monitors.kubernetes_monitor"
                    }
                ]
              }
            """ % test_str)
            _verify(expected)

        def _set_env_val(test_str):
            """
            Value of None means delete it from the environment
            Empty string means set the environment value to empty string (see AGENT-241)
            """
            if test_str is None:
                if 'SCALYR_K8S_IGNORE_NAMESPACES' in os.environ:
                    del os.environ['SCALYR_K8S_IGNORE_NAMESPACES']
            else:
                os.environ['SCALYR_K8S_IGNORE_NAMESPACES'] = test_str

        def _test_k8s_ignore_namespaces_environ(test_str, expected):
            _set_env_val(test_str)
            self._write_file_with_separator_conversion(""" { 
                api_key: "hi there",
                logs: [ { path:"/var/log/tomcat6/access.log" }],
                monitors: [
                    {
                        module: "scalyr_agent.builtin_monitors.kubernetes_monitor"
                    }
                ]
              }
            """)
            _verify(expected)

        def _test_k8s_ignore_namespaces_supersedes(env_str, local_str, expected):
            _set_env_val(env_str)

            k8s_config_line = ''
            if local_str is not None:
                k8s_config_line = ", k8s_ignore_namespaces: %s" % local_str

            self._write_file_with_separator_conversion(""" { 
                api_key: "hi there",
                logs: [ { path:"/var/log/tomcat6/access.log" }],
                monitors: [
                    {
                        module: "scalyr_agent.builtin_monitors.kubernetes_monitor"
                        %s
                    }
                ]
              }
            """ % k8s_config_line)
            _verify(expected)

        expected = ['a', 'b', 'c', 'd']
        kube_system = Configuration.DEFAULT_K8S_IGNORE_NAMESPACES

        # define locally in agent.json
        _test_k8s_ignore_namespaces_local(r'"a, b  c, d"', expected)
        _test_k8s_ignore_namespaces_local(r'["a", "b", "c", "d"]', expected)
        _test_k8s_ignore_namespaces_local(None, ['kube-system'])
        _test_k8s_ignore_namespaces_local(r'""', [])

        # defined globally in agent.json
        _test_k8s_ignore_namespaces_global(r'["a", "b", "c", "d"]', expected)
        self.assertRaises(BadConfiguration, lambda: _test_k8s_ignore_namespaces_global(r'"a, b  c, d"', expected))

        # defined in environment
        _test_k8s_ignore_namespaces_environ(r'a, b  c, d', expected)
        _test_k8s_ignore_namespaces_environ(r'["a", "b", "c", "d"]', expected)
        _test_k8s_ignore_namespaces_environ(None, ['kube-system'])
        # empty string overrides default kube-system
        _test_k8s_ignore_namespaces_environ(r'', [])

        # environment supersedes local
        _test_k8s_ignore_namespaces_supersedes("a b c d", r'"1 2 3"', expected)
        _test_k8s_ignore_namespaces_supersedes("a b, c d", r'"1, 2 3"', expected)
        _test_k8s_ignore_namespaces_supersedes(r'["a", "b", "c", "d"]', r'["1", "2", "3"]', expected)
        _test_k8s_ignore_namespaces_supersedes(None, r'"1, 2, 3"', ["1", "2", "3"])
        _test_k8s_ignore_namespaces_supersedes(r'', r'"1, 2, 3"', [])
        _test_k8s_ignore_namespaces_supersedes(None, None, kube_system)
        _test_k8s_ignore_namespaces_supersedes(None, r'""', [])
        _test_k8s_ignore_namespaces_supersedes(r'', r'""', [])
