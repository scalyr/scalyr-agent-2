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
import argparse
import functools
import json
import re
import time
import logging

import pytest

from tests.end_to_end_tests.verify import verify_logs, ScalyrQueryRequest
from tests.end_to_end_tests.tools import TimeTracker

from agent_build.docker_image_builders import (
    DOCKER_IMAGE_BUILDERS,
)

log = logging.getLogger(__name__)

pytestmark = [
    # Add timeout for all tests
    pytest.mark.timeout(60 * 1000),
    pytest.mark.usefixtures("dump_info"),
]

DEFAULT_KUBERNETES_VERSION = {
    "kubernetes_version": "v1.22.7",
    "minikube_driver": "",
    "container_runtime": "docker",
}

KUBERNETES_VERSIONS = [
    {
        "kubernetes_version": "v1.20.15",
        "minikube_driver": "",
        "container_runtime": "docker",
    },
    {
        "kubernetes_version": "v1.21.10",
        "minikube_driver": "",
        "container_runtime": "docker",
    },
    DEFAULT_KUBERNETES_VERSION,
    {
        "kubernetes_version": "v1.23.4",
        "minikube_driver": "docker",
        "container_runtime": "containerd",
    },
    {
        "kubernetes_version": "v1.24.0",
        "minikube_driver": "docker",
        "container_runtime": "containerd",
    },
    {
        "kubernetes_version": "v1.17.17",
        "minikube_driver": "",
        "container_runtime": "docker",
    },
]

PARAMS = []
EXTENDED_PARAMS = []

for builder_name, builder_cls in DOCKER_IMAGE_BUILDERS.items():

    base_distro = builder_cls.BASE_IMAGE_BUILDER_STEP.base_distro
    if base_distro.name == "debian":
        kubernetes_versions_to_test = KUBERNETES_VERSIONS[:]
    else:
        kubernetes_versions_to_test = [DEFAULT_KUBERNETES_VERSION]

    if "k8s" not in builder_name:
        continue

    builder_params = {
        "image_builder_name": builder_name,
        **DEFAULT_KUBERNETES_VERSION,
    }

    if builder_name == f"k8s-{base_distro.name}" and base_distro.name == "debian":
        # If this is a "main build", aka 'k8s-debian' then also apply different platform testing
        # in extended test mode.
        for k_v in KUBERNETES_VERSIONS:
            EXTENDED_PARAMS.append({"image_builder_name": builder_name, **k_v})
        PARAMS.append(builder_params)
    else:
        EXTENDED_PARAMS.append(builder_params)
        PARAMS.append(builder_params)


def pytest_generate_tests(metafunc):
    param_names = [
        "image_builder_name",
        "kubernetes_version",
        "minikube_driver",
        "container_runtime",
    ]

    final_params = []
    for p in EXTENDED_PARAMS:
        final_params.append([p[name] for name in param_names])

    metafunc.parametrize(param_names, final_params, indirect=True)


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
    timeout = TimeTracker(150)

    log.info(
        f"Starting test. Scalyr logs can be found by the cluster name: {cluster_name}"
    )
    apply_agent_service_account()

    agent_pod_name = create_agent_daemonset(time_tracker=timeout)

    test_writer_pod_name = start_test_log_writer_pod(time_tracker=timeout)

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
        time_tracker=timeout,
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

    timeout = TimeTracker(150)

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


def main():
    """
    This function generates GitHub Actions tests job matrix.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--extended", action="store_true", help="Return extended test job matrix"
    )

    args = parser.parse_args()

    if args.extended:
        params = EXTENDED_PARAMS[:]
    else:
        params = PARAMS[:]

    matrix = {"include": []}

    for p in params:
        image_builder_name = p["image_builder_name"]
        image_builder_cls = DOCKER_IMAGE_BUILDERS[image_builder_name]
        kubernetes_version = p["kubernetes_version"]
        minikube_driver = p["minikube_driver"]
        container_runtime = p["container_runtime"]

        matrix["include"].append(
            {
                "pytest-params": f"{image_builder_name}-{kubernetes_version}-{minikube_driver}-{container_runtime}",
                "builder-name": image_builder_name,
                "distro-name": image_builder_cls.BASE_IMAGE_BUILDER_STEP.base_distro.name,
                "os": "ubuntu-20.04",
                "python-version": "3.8.13",
            }
        )

    print(json.dumps(matrix))


if __name__ == "__main__":
    main()
