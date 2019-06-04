import os
from mock import patch, Mock

from scalyr_agent import scalyr_monitor
from scalyr_agent.builtin_monitors.docker_monitor import DockerMonitor
from scalyr_agent.copying_manager import CopyingManager
from scalyr_agent.monitors_manager import MonitorsManager
from scalyr_agent.json_lib.objects import ArrayOfStrings
from scalyr_agent.test_util import FakeAgentLogger, FakePlatform
from scalyr_agent.tests.configuration_test import TestConfiguration


class TestConfigurationDocker(TestConfiguration):
    """This test subclasses from TestConfiguration for easier exclusion in python 2.5 and below"""

    def _make_monitors_manager(self, config):
        def fake_init(self):
            # Initialize some requisite variables so that the k8s monitor loop can run
            self._DockerMonitor__socket_file = None
            self._DockerMonitor__container_checker = None
            self._DockerMonitor__namespaces_to_ignore = []
            self._DockerMonitor__include_controller_info = None
            self._DockerMonitor__report_container_metrics = None
            self._DockerMonitor__metric_fetcher = None

        mock_logger = Mock()

        @patch.object(DockerMonitor, '_initialize', new=fake_init)
        def create_manager():
            scalyr_monitor.log = mock_logger
            return MonitorsManager(config, FakePlatform([]))

        monitors_manager = create_manager()
        return monitors_manager, mock_logger

    @patch('scalyr_agent.builtin_monitors.docker_monitor.docker')
    def test_environment_aware_module_params(self, mock_docker):

        # Define test values here for all k8s and k8s_event monitor config params that are environment aware.
        # Be sure to use non-default test values
        TEST_INT = 123456789
        TEST_STRING = 'dummy string'
        TEST_ARRAY_OF_STRINGS = ['s1', 's2', 's3']
        STANDARD_PREFIX = '_STANDARD_PREFIX_'  # env var is SCALYR_<param_name>

        # The following map contains config params to be tested
        # config_param_name: (custom_env_name, test_value)
        docker_testmap = {
            "container_check_interval": (STANDARD_PREFIX, TEST_INT, int),
            "docker_api_version": (STANDARD_PREFIX, TEST_STRING, str),
            "docker_log_prefix": (STANDARD_PREFIX, TEST_STRING, str),
            "log_mode": ('SCALYR_DOCKER_LOG_MODE', TEST_STRING, str),
            "docker_raw_logs": (STANDARD_PREFIX, False, bool),  # test config file is set to True
            "metrics_only": ('SCALYR_DOCKER_METRICS_ONLY', True, bool),
            "container_globs": (STANDARD_PREFIX, TEST_ARRAY_OF_STRINGS, ArrayOfStrings),
            "container_globs_exclude": (STANDARD_PREFIX, TEST_ARRAY_OF_STRINGS, ArrayOfStrings),
            "report_container_metrics": (STANDARD_PREFIX, False, bool),
            "label_include_globs": (STANDARD_PREFIX, TEST_ARRAY_OF_STRINGS, ArrayOfStrings),
            "label_exclude_globs": (STANDARD_PREFIX, TEST_ARRAY_OF_STRINGS, ArrayOfStrings),
            "labels_as_attributes": (STANDARD_PREFIX, True, bool),
            "label_prefix": (STANDARD_PREFIX, TEST_STRING, str),
            "use_labels_for_log_config": (STANDARD_PREFIX, False, bool),
        }

        # Fake the environment varaibles
        for key, value in docker_testmap.items():
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
        self._write_config_fragment_file_with_separator_conversion('docker.json', """ {
            "monitors": [
                {
                    module: "scalyr_agent.builtin_monitors.docker_monitor",
                    docker_raw_logs: true
                }
            ]
        }
        """)

        config = self._create_test_configuration_instance()
        config.parse()

        monitors_manager, mock_logger = self._make_monitors_manager(config)
        docker_monitor = monitors_manager.monitors[0]

        # All environment-aware params defined in the docker monitor must be gested
        self.assertEquals(
            set(docker_testmap.keys()),
            set(docker_monitor._config._environment_aware_map.keys()))

        # Verify module-level conflicts between env var and config file are logged at module-creation time
        mock_logger.warn.assert_called_with(
            'Conflicting values detected between scalyr_agent.builtin_monitors.docker_monitor config file '
            'parameter `docker_raw_logs` and the environment variable `SCALYR_DOCKER_RAW_LOGS`. '
            'Ignoring environment variable.',
            limit_once_per_x_secs=300,
            limit_key='config_conflict_scalyr_agent.builtin_monitors.docker_monitor_docker_raw_logs_SCALYR_DOCKER_RAW_LOGS',
        )

        CopyingManager(config, monitors_manager.monitors)
        # Override Agent Logger to prevent writing to disk
        for monitor in monitors_manager.monitors:
            monitor._logger = FakeAgentLogger('fake_agent_logger')

        # Verify environment variable values propagate into DockerMonitor monitor MonitorConfig
        monitor_2_testmap = {
            docker_monitor: docker_testmap,
        }
        for monitor, testmap in monitor_2_testmap.items():
            for key, value in testmap.items():
                test_val, convert_to = value[1:]
                if key in ['docker_raw_logs']:
                    # Keys were defined in config files so should not have changed
                    self.assertNotEquals(test_val, monitor._config.get(key, convert_to=convert_to))
                else:
                    # Keys were empty in config files so they take on environment values
                    materialized_value = monitor._config.get(key, convert_to=convert_to)
                    if hasattr(test_val, '__iter__'):
                        self.assertEquals([x1 for x1 in test_val], [x2 for x2 in materialized_value])
                    else:
                        self.assertEquals(test_val, materialized_value)

    def test_label_include_globs_from_config(self):
        self._write_file_with_separator_conversion(""" { 
            api_key: "hi there",
            logs: [ { path:"/var/log/tomcat6/access.log" }],
            monitors: [
                {
                    module: "scalyr_agent.builtin_monitors.docker_monitor",
                    docker_raw_logs: true
                    label_include_globs: ["*glob1*", "*glob2*", "*glob3*"]
                }
            ]
          }
        """)
        config = self._create_test_configuration_instance()
        config.parse()

        test_manager, _ = self._make_monitors_manager(config)
        docker_monitor = test_manager.monitors[0]
        include_globs = docker_monitor._config.get('label_include_globs')
        elems = ["*glob1*", "*glob2*", "*glob3*"]
        self.assertNotEquals(elems, include_globs)  # list != JsonArray
        self.assertEquals(elems, [x for x in include_globs])

    def test_label_include_globs_from_environment(self):

        include_elems = ['*env_glob1*', '*env_glob2*']
        exclude_elems = ['*env_glob1_exclude_1', '*env_glob1_exclude_2', '*env_glob1_exclude_3']

        os.environ['SCALYR_LABEL_INCLUDE_GLOBS'] = '*env_glob1*, *env_glob2*'
        os.environ['SCALYR_LABEL_EXCLUDE_GLOBS'] = '*env_glob1_exclude_1, *env_glob1_exclude_2, *env_glob1_exclude_3'
        self._write_file_with_separator_conversion(""" { 
            api_key: "hi there",
            logs: [ { path:"/var/log/tomcat6/access.log" }],
            monitors: [
                {
                    module: "scalyr_agent.builtin_monitors.docker_monitor",                    
                    docker_raw_logs: true
                }
            ]
          }
        """)
        config = self._create_test_configuration_instance()
        config.parse()

        test_manager, _ = self._make_monitors_manager(config)
        docker_monitor = test_manager.monitors[0]
        include_globs = docker_monitor._config.get('label_include_globs')
        exclude_globs = docker_monitor._config.get('label_exclude_globs')
        self.assertNotEquals(include_elems, include_globs)  # list != ArrayOfStrings
        self.assertNotEquals(exclude_elems, exclude_globs)  # list != ArrayOfStrings
        self.assertEquals(type(include_globs), ArrayOfStrings)
        self.assertEquals(type(exclude_globs), ArrayOfStrings)
        self.assertEquals(include_elems, list(include_globs))
        self.assertEquals(exclude_elems, list(exclude_globs))
