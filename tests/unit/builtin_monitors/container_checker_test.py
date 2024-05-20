from __future__ import absolute_import
from __future__ import unicode_literals

import base64
import json
from dataclasses import dataclass, field
from threading import Condition, Thread, Lock
from typing import Dict, List

from mock.mock import MagicMock, call

from scalyr_agent.json_lib import JsonArray, JsonObject
from scalyr_agent.monitor_utils.k8s import (
    K8sConfigBuilder,
    K8sNamespaceFilter, Controller,
)
from scalyr_agent.monitor_utils.annotation_config import process_annotations

__author__ = "ales.novak@scalyr.com"


from scalyr_agent.builtin_monitors.kubernetes_monitor import (
    ContainerChecker,
)

from tests.unit.configuration_test import TestConfigurationBase

import mock

class MockRunState():
    def __init__(self):
        self.running_lock = Lock()
        self.next_loop_condition = Condition()
        self.running = True

    def wait_for_next_loop_start(self):
        with self.next_loop_condition:
            if not self.next_loop_condition.wait(timeout=15):
                raise Exception("Failed to acquire started lock")

    def is_running(self):
        with self.next_loop_condition:
            self.next_loop_condition.notify_all()

        with self.running_lock:
            return self.running

    def set_running(self, running):
        with self.running_lock:
            self.running = running

    def sleep_but_awaken_if_stopped(self, timeout):
        pass


@dataclass
class MockNamespace():
    name: str
    annotations: Dict
    digest: bytes = b""


@dataclass
class MockPod():
    namespace: str
    name: str
    node_name: str
    uid: str
    annotations: Dict
    container_names: List[str]
    controller: Controller
    labels: Dict = field(default_factory=dict)


@dataclass
class MockPodInfo():
    digest: str


class ContainerCheckerTest(TestConfigurationBase):
    def setUp(self):
        super(ContainerCheckerTest, self).setUp()
        self.tear_down_functions = []

        self._write_file_with_separator_conversion(
            """{
            "api_key": "hi there",
            "k8s_logs": [
              {
                "k8s_container_glob": "no_match",
                "test": "no_match",
              },
              {
                "attributes": { "container_name": "${k8s_container_name}" }
              }
            ]
          }"""
        )
        self.config = self._create_test_configuration_instance()
        self.config.parse()

        self.mock_logger = mock.Mock()
        self.log_watcher = mock.Mock()
        # Return log config
        self.log_watcher.add_log_config.return_value = {}
        self.log_watcher.update_log_configs_on_path.return_value = {}

        self.container_checker = ContainerChecker(
            config=self._container_checker_config(),
            global_config=self.config,
            logger=self.mock_logger,
            socket_file=None,
            docker_api_version=None,
            agent_pod=mock.MagicMock(namespace="testing_namespace", name="testing_pod"),
            host_hostname=None,
            log_path=None,
            include_all=False,
            include_controller_info=True,
            namespaces_to_include=[K8sNamespaceFilter.default_value()],
            ignore_pod_sandboxes=False,
        )

        self.container_checker.get_cluster_name = lambda *_: "the-cluster-name"
        self.container_checker.set_log_watcher(self.log_watcher, MagicMock(module_name="unittest_module"))
        self.container_checker._k8s_config_builder = mock.Mock(
            return_value=K8sConfigBuilder(
                self.config.k8s_log_configs,
                MagicMock(),
                None,
                parse_format="test_parse_format",
            )
        )
        self.container_checker.k8s_cache = mock.Mock()
        self.container_checker.k8s_cache.is_initialized.return_value = True
        self.container_checker._container_enumerator = mock.Mock()

        def mock_get_secret(namespace, name, current_time=None, allow_expired=False):
            return mock.MagicMock(
            data={
                "scalyr-api-key": base64.b64encode((name + "-value").encode("utf-8"))
            }
        )
        self.container_checker.k8s_cache.secret.side_effect = mock_get_secret

    def tearDown(self):
        super(ContainerCheckerTest, self).tearDown()
        for tear_down_function in self.tear_down_functions:
            tear_down_function()
        self.tear_down_functions = []

    def _flatten_labels(self, labels):
        return ",".join(
            f"{label}={value}"
            for label, value in labels.items()
        )

    def _container_checker_config(self):
        return {
            "k8s_use_v2_attributes": True,
            "initial_stopped_container_collection_window": 0,
            "k8s_label_include_globs": ["*"],
            "k8s_label_exclude_globs": []
        }

    def _start_check_containers_thread(self):

        exception_holder = []
        run_state = MockRunState()

        def run(exception_holder):
            try:
                self.container_checker.check_containers(run_state)
            except Exception as e:
                exception_holder.append(e)

        t = Thread(target=run, args=(exception_holder,))

        def stop_running():
            run_state.set_running(False)
            t.join()

        self.tear_down_functions.append(stop_running)

        t.start()

        return run_state, exception_holder

    def _get_containers_value_from_pods(self, pods):
        return {
            container_name: {
                "k8s_info": {
                    "k8s_container_name": container_name,
                    "pod_info": MockPodInfo(
                        digest=f"{k8s_pod.name}-digest-1"
                    ),
                    "pod_name": k8s_pod.name,
                    "pod_namespace": k8s_pod.namespace
                },
                "name": container_name,
                "log_path": f"/var/log/scalyr-agent2/containers/{container_name}.log"
            }
            for k8s_pod in pods
            for container_name in k8s_pod.container_names
        }

    def _mock_get_containers_value(self, value):
        self.container_checker._container_enumerator.get_containers.return_value = value
        return value

    def _set_mocked_k8s_objects(self, k8s_pods, k8s_namespaces):
        get_containers_value = self._mock_get_containers_value(
            self._get_containers_value_from_pods(k8s_pods)
        )

        def mocked_pod(
            namespace,
            name,
            current_time=None,
            allow_expired=True,
            query_options=None,
            ignore_k8s_api_exception=False):
            return {
                pod.name: pod
                for pod in k8s_pods
            }[name]

        self.container_checker.k8s_cache.pod.side_effect = mocked_pod

        def namespace(
                name,
                current_time=None,
                allow_expired=True,
                query_options=None,
                ignore_k8s_api_exception=False,
        ):
            return {
                namespace.name: namespace
                for namespace in k8s_namespaces
            }[name]

        self.container_checker.k8s_cache.namespace.side_effect = namespace

        return get_containers_value


    def _assert_mock_logger_no_severe_messages(self):
        assert len(
            self.mock_logger.exception.mock_calls) == 0, "Some exceptions were logged: %s" % self.mock_logger.exception.mock_calls
        assert len(
            self.mock_logger.warn.mock_calls) == 0, "Some warnings were logged: %s" % self.mock_logger.warn.mock_calls
        assert len(
            self.mock_logger.error.mock_calls) == 0, "Some errors were logged: %s" % self.mock_logger.error.mock_calls


class ContainerCheckerMultiAccountTest(ContainerCheckerTest):
    def test_check_namespace_change(self):
        k8s_namespace = MockNamespace(
            name="namespace",
            annotations=process_annotations(
                {"log.config.scalyr.com/teams.1.secret": "scalyr-api-key-team-2"}
            ),
            digest=b"digest-1"
        )
        k8s_pod = MockPod(
            namespace=k8s_namespace.name,
            name="work-pod-name",
            node_name="test_node",
            uid="lkjsefr",
            annotations=process_annotations({}),
            container_names=[
                "work-container"
            ],
            controller=Controller(
                name="controller_name_k8s_pod_1_namespace_1",
                kind="controller_kind_k8s_pod_1_namespace_1",
                labels={"controller_labels_k8s_pod_1_namespace_1": "value"}
            )
        )

        self._set_mocked_k8s_objects([k8s_pod], [k8s_namespace])

        run_state, exception_holder = self._start_check_containers_thread()

        # Wait for ContainerChecker to complete at least one loop
        run_state.wait_for_next_loop_start()
        run_state.wait_for_next_loop_start()

        assert len(exception_holder) == 0, "Expected no exceptions"
        self._assert_mock_logger_no_severe_messages()

        assert len(self.log_watcher.add_log_config.call_args_list) == 1

        assert self.log_watcher.add_log_config.call_args_list[0].args[1]["path"] == '/var/log/scalyr-agent2/containers/work-container.log'
        assert self.log_watcher.add_log_config.call_args_list[0].args[1]["api_key"] == 'scalyr-api-key-team-2-value'

        self.log_watcher.add_log_config.reset_mock()

        # Wait for the loop to complete and pause it to change pod annotations.
        with run_state.running_lock as lock:
            run_state.wait_for_next_loop_start()

            k8s_namespace.annotations = process_annotations(
                {"log.config.scalyr.com/teams.1.secret": "scalyr-api-key-team-3"}
            )
            k8s_namespace.digest = b"digest-2"

        run_state.wait_for_next_loop_start()
        run_state.wait_for_next_loop_start()

        assert len(exception_holder) == 0, "Expected no exceptions"
        self._assert_mock_logger_no_severe_messages()

        self.log_watcher.add_log_config.assert_not_called()

        assert self.log_watcher.update_log_configs_on_path.call_args_list[0].args[0] == '/var/log/scalyr-agent2/containers/work-container.log'
        assert self.log_watcher.update_log_configs_on_path.call_args_list[0].args[1] == 'unittest_module'

        assert len(self.log_watcher.update_log_configs_on_path.call_args_list[0].args[2]) == 1

        assert self.log_watcher.update_log_configs_on_path.call_args_list[0].args[2][0]["api_key"] == 'scalyr-api-key-team-3-value'

    def test_check_containers_with_api_key_annotations(self):
        WORKLOAD_POD_1_CONTAINER_3 = "workload-pod-1-container-3"
        WORKLOAD_POD_1_CONTAINER_2 = "workload-pod-1-container-2"
        WORKLOAD_POD_1_CONTAINER_1 = "workload-pod-1-container-1"
        WORKLOAD_POD_2_CONTAINER_1 = "workload-pod-2-container-1"
        WORKLOAD_POD_3_CONTAINER_1 = "workload-pod-3-container-1"

        k8s_namespace_1 = MockNamespace(
            name="namespace-1",
            annotations=process_annotations(
                {"log.config.scalyr.com/teams.1.secret": "scalyr-api-key-team-2"}
            )
        )

        k8s_pod_1_namespace_1 = MockPod(
            namespace=k8s_namespace_1.name,
            name="k8s_pod_1_namespace_1",
            node_name="test_node",
            uid="lkjsefr",
            annotations=process_annotations(
                {
                    "log.config.scalyr.com/teams.1.secret": "scalyr-api-key-team-3",
                    "log.config.scalyr.com/teams.5.secret": "scalyr-api-key-team-4",
                    "log.config.scalyr.com/workload-pod-1-container-1.teams.1.secret": "scalyr-api-key-team-5",
                    "log.config.scalyr.com/workload-pod-1-container-2.teams.1.secret": "scalyr-api-key-team-6",
                    "log.config.scalyr.com/workload-pod-1-container-2.teams.2.secret": "scalyr-api-key-team-7"
                }
            ),
            container_names=[
                WORKLOAD_POD_1_CONTAINER_1,
                WORKLOAD_POD_1_CONTAINER_2,
                WORKLOAD_POD_1_CONTAINER_3,
            ],
            controller = Controller(
                name = "controller_name_k8s_pod_1_namespace_1",
                kind = "controller_kind_k8s_pod_1_namespace_1",
                labels = {"controller_labels_k8s_pod_1_namespace_1": "value"}
            )
        )

        k8s_pod_2_namespace_1 = MockPod(
            namespace=k8s_namespace_1.name,
            name="k8s_pod_2_namespace_1",
            node_name="test_node",
            uid="opimon",
            annotations=process_annotations({}),
            container_names=[
                WORKLOAD_POD_2_CONTAINER_1,
            ],
            controller=Controller(
                name="controller_name_k8s_pod_2_namespace_1",
                kind="controller_kind_k8s_pod_2_namespace_1",
                labels={"controller_labels_k8s_pod_2_namespace_1": "value"}
            )
        )

        k8s_namespace_2 = MockNamespace(
            name="namespace-2",
            annotations=process_annotations({})
        )
        k8s_pod_3_namespace_2 = MockPod(
            namespace=k8s_namespace_2.name,
            name="k8s_pod_3_namespace_2",
            node_name="test_node",
            uid="fsdjlkh",
            annotations=process_annotations({}),
            container_names=[WORKLOAD_POD_3_CONTAINER_1],
            controller=Controller(
                name="controller_name_k8s_pod_3_namespace_2",
                kind="controller_kind_k8s_pod_3_namespace_2",
                labels={"controller_labels_k8s_pod_3_namespace_2": "value"}
            )
        )

        get_containers_value = self._set_mocked_k8s_objects([k8s_pod_1_namespace_1, k8s_pod_2_namespace_1, k8s_pod_3_namespace_2], [k8s_namespace_1, k8s_namespace_2])

        run_state, exception_holder = self._start_check_containers_thread()

        # Wait for ContainerChecker to complete at least one loop
        run_state.wait_for_next_loop_start()
        run_state.wait_for_next_loop_start()

        assert len(exception_holder) == 0, "Expected no exceptions"
        assert len(self.mock_logger.exception.mock_calls) == 0, "Some exceptions were logged: %s" % self.mock_logger.exception.mock_calls
        assert len(self.mock_logger.warn.mock_calls) == 0, "Some warnings were logged: %s" % self.mock_logger.warn.mock_calls
        assert len(self.mock_logger.error.mock_calls) == 0, "Some errors were logged: %s" % self.mock_logger.error.mock_calls

        def expected_log_config(pod: MockPod, container_name: str, api_key: str, teams: List[str]):
            log_config = {
                'parser': 'docker',
                'path': f'/var/log/scalyr-agent2/containers/{container_name}.log',
                'parse_format': 'test_parse_format',
                'rename_logfile': f'/unknown/{container_name}.log',
                'rename_no_original': None,
                'attributes': JsonObject({
                    'container_name': container_name,
                    'monitor': 'agentKubernetes',
                    'container_id': container_name,
                    'pod_name': pod.name,
                    'pod_namespace': pod.namespace,
                    '_k8s_cn': 'the-cluster-name',
                    'scalyr-category': 'log',
                    'pod_uid': pod.uid,
                    'k8s_node': 'test_node',
                    '_k8s_dn': pod.controller.name,
                    '_k8s_dl': self._flatten_labels(pod.controller.labels),
                    '_k8s_ck': pod.controller.kind
                }),
                'k8s_pod_glob': '*', 'k8s_namespace_glob': '*', 'k8s_container_glob': '*', 'lineGroupers': JsonArray(),
                'sampling_rules': JsonArray(), 'redaction_rules': JsonArray()
            }
            if teams:
                log_config['teams'] = JsonArray(*[JsonObject({'secret': team}) for team in teams])
            if api_key:
                log_config['api_key'] = api_key

            return log_config

        assert self.log_watcher.add_log_config.call_args_list == [
            call(
            'unittest_module',
                expected_log_config(k8s_pod_1_namespace_1, WORKLOAD_POD_1_CONTAINER_1, 'scalyr-api-key-team-5-value', ['scalyr-api-key-team-5']),
                force_add=True
            ),
            call(
                'unittest_module',
                expected_log_config(k8s_pod_1_namespace_1, WORKLOAD_POD_1_CONTAINER_2, 'scalyr-api-key-team-6-value',
                                    ['scalyr-api-key-team-6', 'scalyr-api-key-team-7']),
                force_add=True
            ),
            call(
                'unittest_module',
                expected_log_config(k8s_pod_1_namespace_1, WORKLOAD_POD_1_CONTAINER_2, 'scalyr-api-key-team-7-value',
                                    ['scalyr-api-key-team-6', 'scalyr-api-key-team-7']),
                force_add=True
            ),
            call(
                'unittest_module',
                expected_log_config(k8s_pod_1_namespace_1, WORKLOAD_POD_1_CONTAINER_3, 'scalyr-api-key-team-3-value',
                                    ['scalyr-api-key-team-3', 'scalyr-api-key-team-4']),
                force_add=True
            ),
            call(
                'unittest_module',
                expected_log_config(k8s_pod_1_namespace_1, WORKLOAD_POD_1_CONTAINER_3, 'scalyr-api-key-team-4-value',
                                    ['scalyr-api-key-team-3', 'scalyr-api-key-team-4']),
                force_add=True
            ),
            call(
                'unittest_module',
                expected_log_config(k8s_pod_2_namespace_1, WORKLOAD_POD_2_CONTAINER_1, 'scalyr-api-key-team-2-value', None),
                force_add=True
            ),
            call(
                'unittest_module',
                expected_log_config(k8s_pod_3_namespace_2, WORKLOAD_POD_3_CONTAINER_1, None,
                                    None),
                force_add=True
            )]

        self.log_watcher.add_log_config.reset_mock()

        # Wait for the loop to complete and pause it to change pod annotations.
        with run_state.running_lock as lock:
            run_state.wait_for_next_loop_start()

            k8s_pod_1_namespace_1.annotations = process_annotations(
                {
                    "log.config.scalyr.com/workload-pod-1-container-1.teams.3.secret": "scalyr-api-key-team-10",
                    "log.config.scalyr.com/workload-pod-1-container-1.teams.5.secret": "scalyr-api-key-team-11",
                    "log.config.scalyr.com/workload-pod-1-container-3.teams.1.secret": "scalyr-api-key-team-12",
                }
            )
            get_containers_value[WORKLOAD_POD_1_CONTAINER_1]["k8s_info"]["pod_info"].digest = "digest-2"
            get_containers_value[WORKLOAD_POD_1_CONTAINER_3]["k8s_info"]["pod_info"].digest = "digest-2"

        run_state.wait_for_next_loop_start()
        run_state.wait_for_next_loop_start()

        assert len(exception_holder) == 0, "Expected no exceptions"
        assert len(self.mock_logger.warn.mock_calls) == 0, "Some warnings were logged: %s" % self.mock_logger.warn.mock_calls
        assert len(self.mock_logger.error.mock_calls) == 0, "Some errors were logged: %s" % self.mock_logger.error.mock_calls

        self.log_watcher.add_log_config.assert_not_called()

        assert self.log_watcher.update_log_configs_on_path.call_args_list == [
            call(
                "/var/log/scalyr-agent2/containers/workload-pod-1-container-1.log",
                'unittest_module',
                [
                    expected_log_config(k8s_pod_1_namespace_1, WORKLOAD_POD_1_CONTAINER_1, 'scalyr-api-key-team-10-value',
                                        ['scalyr-api-key-team-10', 'scalyr-api-key-team-11']),
                    expected_log_config(k8s_pod_1_namespace_1, WORKLOAD_POD_1_CONTAINER_1,'scalyr-api-key-team-11-value',
                                        ['scalyr-api-key-team-10', 'scalyr-api-key-team-11']),
                ]
            ),
            call("/var/log/scalyr-agent2/containers/workload-pod-1-container-3.log", "unittest_module",
                 [
                        expected_log_config(k8s_pod_1_namespace_1, WORKLOAD_POD_1_CONTAINER_3, 'scalyr-api-key-team-12-value',
                                            ['scalyr-api-key-team-12']),
                 ]
             )
        ]


class ContainerCheckerFilterLabelsTest(ContainerCheckerTest):

    def _container_checker_config(self):
        config = super()._container_checker_config()

        config["k8s_label_include_globs"] = ["*include_this_label*", "wanted_label"]
        config["k8s_label_exclude_globs"] = ["*garbage*","*exclude*"]

        return config

    def test_included_labels(self):
        k8s_namespace = MockNamespace(
            name="namespace",
            annotations=process_annotations({}),
            digest=b"digest-1"
        )
        k8s_pod = MockPod(
            namespace=k8s_namespace.name,
            name="work-pod-name",
            node_name="test_node",
            uid="lkjsefr",
            annotations=process_annotations({}),
            labels={
                "pod_label_1": "pod_value_1",
                "pod_label_2": "pod_value_2",
                "pod_label_unwanted_label": "unwanted_value",
                "include_this_label": "include_this_value",
                "pod_include_this_label_exclude": "pod_include_this_value",
                "pod_include_this_label": "pod_include_this_value",
                "pod_include_this_label_garbage": "random_value",
                "pod_include_this_label_garbage_xxx": "random_value_2",
                "garbage_pod_include_this_label": "random_value_2",
                "wanted_label": "wanted_value",
                "unwanted_label": "unwanted_value"
            },
            container_names=[
                "work-container"
            ],
            controller=Controller(
                name="controller_name_k8s_pod_1_namespace_1",
                kind="controller_kind_k8s_pod_1_namespace_1",
                labels={
                    "controller_label_1": "controller_value_1",
                    "controller_label_2": "controller_value_2",
                    "controller_label_unwanted_label": "unwanted_value",
                    "include_this_label": "include_this_value",
                    "controller_include_this_label_exclude": "pod_include_this_value",
                    "controller_include_this_label": "controller_include_this_value",
                    "controller_include_this_label_garbage": "random_value",
                    "controller_include_this_label_garbage_xxx": "random_value_2",
                    "garbage_controller_include_this_label": "random_value_2",
                    "wanted_label": "wanted_value",
                    "unwanted_label": "unwanted_value"
                }
            )
        )

        INCLUDED_POD_LABELS = {
                "include_this_label": "include_this_value",
                "pod_include_this_label": "pod_include_this_value",
                "wanted_label": "wanted_value"
            }

        EXCLUDED_POD_LABELS = {
            "pod_label_1": "pod_value_1", # Not matching include glob
            "pod_label_2": "pod_value_2", # Not matching include glob
            "pod_label_unwanted_label": "unwanted_value", # Not matching include glob,
            "pod_include_this_label_exclude": "pod_include_this_value", # Matching exclude glob
            "pod_include_this_label_garbage": "random_value", # Matching exclude glob
            "pod_include_this_label_garbage_xxx": "random_value_2", # Matching exclude glob
            "garbage_pod_include_this_label": "random_value_2", # Matching exclude glob
            "unwanted_label": "unwanted_value" # Not matching include glob
        }

        INCLUDED_CONTROLLER_LABELS = self._flatten_labels(
            {
                "include_this_label": "include_this_value",
                "controller_include_this_label": "controller_include_this_value",
                "wanted_label": "wanted_value"
            }
        )

        get_containers_value = self._set_mocked_k8s_objects([k8s_pod], [k8s_namespace])

        run_state, exception_holder = self._start_check_containers_thread()

        # Wait for ContainerChecker to complete at least one loop
        run_state.wait_for_next_loop_start()
        run_state.wait_for_next_loop_start()

        assert len(exception_holder) == 0, "Expected no exceptions"
        self._assert_mock_logger_no_severe_messages()

        assert len(self.log_watcher.add_log_config.call_args_list) == 1

        assert self.log_watcher.add_log_config.call_args_list[0].args[1]["path"] == '/var/log/scalyr-agent2/containers/work-container.log'

        for label, value in INCLUDED_POD_LABELS.items():
            assert self.log_watcher.add_log_config.call_args_list[0].args[1]["attributes"].get(label) == value

        for label in EXCLUDED_POD_LABELS.keys():
            assert label not in self.log_watcher.add_log_config.call_args_list[0].args[1]["attributes"]

        assert self.log_watcher.add_log_config.call_args_list[0].args[1]["attributes"]["_k8s_dl"] == INCLUDED_CONTROLLER_LABELS

        self.log_watcher.add_log_config.reset_mock()

