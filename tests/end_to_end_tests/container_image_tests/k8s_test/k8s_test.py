#!/usr/bin/env python3
# Copyright 2014-2022 Scalyr Inc.
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

import functools
import re
import time
import logging

import pytest

from agent_build_refactored.tools import check_output_with_log_debug
from tests.end_to_end_tests.verify import verify_logs
from tests.end_to_end_tests.tools import TimeoutTracker


log = logging.getLogger(__name__)

pytestmark = [
    # Add timeout for all tests
    pytest.mark.timeout(60 * 10),
    pytest.mark.usefixtures("dump_info"),
]


@pytest.fixture(scope="session")
def dump_info(minikube_kubectl_args, minikube_test_profile):
    """Dump useful environment information before/after the test case."""
    minikube_version_output = check_output_with_log_debug(["minikube", "version"])
    minikube_addons_output = check_output_with_log_debug(["minikube", "addons", "list"])
    kubectl_version_output = check_output_with_log_debug(
        [*minikube_kubectl_args, "version", "--output=json"]
    )
    kubectl_get_nodes_output = check_output_with_log_debug(
        [*minikube_kubectl_args, "get", "nodes"]
    )
    kubectl_cluster_info_output = check_output_with_log_debug(
        [*minikube_kubectl_args, "cluster-info"]
    )
    kubernetes_get_pods_output = check_output_with_log_debug(
        [*minikube_kubectl_args, "get", "pods", "-A"]
    )

    node_name = check_output_with_log_debug(
        [
            *minikube_kubectl_args,
            "get",
            "nodes",
            "-o",
            "jsonpath={.items[0].metadata.name}",
        ]
    )

    describe_node_output = check_output_with_log_debug(
        [*minikube_kubectl_args, "describe", "node", node_name.decode().strip()]
    )

    info = (
        f"minikube version: {minikube_version_output.decode()}\n"
        f"minikube addons: {minikube_addons_output.decode()}\n"
        f"kubectl version: {kubectl_version_output.decode()}\n"
        f"kubectl get nodes: {kubectl_get_nodes_output.decode()}\n"
        f"kubectl  cluster-info: {kubectl_cluster_info_output.decode()}\n"
        f"kubectl  get pods -A: {kubernetes_get_pods_output.decode()}\n"
        f"kubectl describe node: {describe_node_output.decode()}\n"
    )
    log.info(f"CLUSTER INFO:\n{info}")


def test_nothing(cluster_name):
    """
    Dummy test cases which does nothing but initialise all session fixtures in it, so the first
        real test is not polluted by fixture outputs.
    """


def test_basic(
    scalyr_api_read_key,
    scalyr_server,
    cluster_name,
    create_agent_daemonset,
    apply_agent_service_account,
    start_test_log_writer_pod,
    get_agent_log_content,
):
    timeout = TimeoutTracker(150)

    log.info(
        f"Starting test. Scalyr logs can be found by the cluster name: {cluster_name}"
    )
    apply_agent_service_account()

    agent_pod_name = create_agent_daemonset(time_tracker=timeout)

    test_writer_pod_name = start_test_log_writer_pod(time_tracker=timeout)

    def ignore_k8s_api_temporary_host_resolution_error(message, additional_lines):
        if (
            "[monitor:kubernetes_events_monitor]" not in message
            and "[monitor:kubernetes_monitor]" not in message
        ):
            return False
        if "Temporary error seen while accessing api" not in message:
            return False

        for additional_line in additional_lines:
            if "[Errno -3] Temporary failure in name resolution" in additional_line:
                return True

        return False

    verify_logs(
        scalyr_api_read_key=scalyr_api_read_key,
        scalyr_server=scalyr_server,
        get_agent_log_content=functools.partial(
            get_agent_log_content, pod_name=agent_pod_name
        ),
        # Since the test writer pod writes plain text counters, set this count getter.
        counter_getter=lambda e: int(e["message"].rstrip("\n")),
        counters_verification_query_filters=[
            f"$pod_name=='{test_writer_pod_name}'",
            "$app=='test-log-writer'",
            f"$k8s-cluster=='{cluster_name}'",
        ],
        timeout_tracker=timeout,
        ignore_agent_errors_predicates=[ignore_k8s_api_temporary_host_resolution_error],
    )

    logging.info("Test passed!")


@pytest.mark.timeout(20000)
def test_agent_pod_fails_on_k8s_monitor_fail(
    image_builder_name,
    scalyr_api_read_key,
    scalyr_server,
    cluster_name,
    create_agent_daemonset,
    apply_agent_service_account,
    default_cluster_role,
    get_pod_status_container_statuses,
    get_agent_log_content,
):
    """
    Tests that agent exits on Kubernetes monitor's failure.
    We emulate failure of the kubernetes monitor by revoking permissions from the agent's service account.
    """
    if not image_builder_name.startswith("k8s-restart-agent-on-monitor-death"):
        pytest.skip(
            f"This test now only for a special preview build '{image_builder_name}'"
        )

    timeout = TimeoutTracker(150)

    cluster_role = default_cluster_role.copy()

    log.info(
        "Removing permissions from the agent's serviceaccount to simulate Kubernetes monitor fail."
    )
    cluster_role["rules"] = []

    apply_agent_service_account(cluster_role=cluster_role)

    log.info("Starting agent daemonset.")
    agent_pod_name = create_agent_daemonset(time_tracker=timeout)
    time.sleep(10)

    agent_log = get_agent_log_content(pod_name=agent_pod_name)

    assert (
        "Kubernetes monitor not started yet (will retry) due to error in cache initialization"
        in agent_log
    )
    assert (
        "Please ensure you have correctly configured the RBAC permissions for the scalyr-agent's service account"
        in agent_log
    )

    while True:
        log.info("Wait for agent container crash...")
        container_statuses = get_pod_status_container_statuses(pod_name=agent_pod_name)
        agent_cont_status = container_statuses["scalyr-agent"]

        last_state = agent_cont_status.get("lastState")
        if not last_state:
            timeout.sleep(10)
            continue

        terminated_state = last_state.get("terminated")
        if not terminated_state:
            timeout.sleep(10)
            continue

        log.info("Agent container terminated.")
        expected_error = (
            "Kubernetes monitor failed to start due to cache initialization error: "
            "Unable to initialize runtime in K8s cache due to \"K8s API error You don't have permission "
            f"to access /api/v1/namespaces/scalyr/pods/{agent_pod_name}.  "
            "Please ensure you have correctly configured the RBAC permissions for the scalyr-agent's "
            'service account"'
        )
        assert expected_error == terminated_state["message"]
        break

    log.info(
        "Agent pod restarted as expected, returning back normal serviceaccount permissions."
    )
    apply_agent_service_account(cluster_role=default_cluster_role)
    timeout.sleep(5)
    agent_log = get_agent_log_content(pod_name=agent_pod_name)

    assert re.search(r"Kubernetes cache initialized in \d+\.\d+ seconds", agent_log)
    assert "kubernetes_monitor is using docker for listing containers" in agent_log
    assert (
        "Cluster name detected, enabling k8s metric reporting and controller information"
        in agent_log
    )

    log.info("Test passed!")
