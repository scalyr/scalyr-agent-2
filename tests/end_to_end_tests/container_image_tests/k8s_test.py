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
import subprocess
import pathlib as pl
import time
import logging
from typing import List

import pytest
import yaml

from agent_build.tools.common import check_output_with_log, check_call_with_log
from agent_build.tools.constants import SOURCE_ROOT
from tests.end_to_end_tests.tools import get_testing_logger
from tests.end_to_end_tests.log_verify import check_agent_log_for_errors, check_requests_stats_in_agent_log, verify_test_log_file_upload, verify_logs


log = get_testing_logger(__name__)


def pytest_generate_tests(metafunc):
    """
    parametrize test case according to which image has to be tested.
    """
    image_builder_name = metafunc.config.getoption("image_builder_name")
    metafunc.parametrize(
        ["image_builder_cls"], [[image_builder_name]], indirect=True
    )


def _run_kubectl(cmd_args: List[str]):
    check_output_with_log([
        "kubectl", *cmd_args
    ])


@pytest.fixture(scope="session")
def minikube(agent_image, full_image_name):
    check_call_with_log(["minikube", "image", "rm", full_image_name])
    check_call_with_log(["minikube", "image", "load", "--overwrite=true", full_image_name])

    yield
    check_call_with_log(["minikube", "image", "rm", full_image_name])


@pytest.fixture(scope="session")
def scalyr_namespace(minikube):
    try:
        check_output_with_log(
            ["kubectl", "create", "namespace", "scalyr"],
            stderr=subprocess.PIPE
        )
    except subprocess.CalledProcessError as e:
        if 'namespaces "scalyr" already exists' not in e.stderr.decode():
            raise


@pytest.fixture(scope="session")
def prepare_scalyr_agent_service_account(scalyr_namespace):
    scalyr_agent_service_account_manifest_path = (
            SOURCE_ROOT / "k8s/no-kustomize/scalyr-service-account.yaml"
    )
    _run_kubectl([
        "delete", "--ignore-not-found", "-f", str(scalyr_agent_service_account_manifest_path)
    ])

    # Create agent's service account.
    check_output_with_log(
        ["kubectl", "apply", "-f", str(scalyr_agent_service_account_manifest_path)]
    )
    yield
    _run_kubectl([
        "delete", "-f", str(scalyr_agent_service_account_manifest_path)
    ])


@pytest.fixture(scope="session")
def prepare_scalyr_api_key_secret(scalyr_api_key, scalyr_namespace):

    _run_kubectl(["--namespace=scalyr", "delete", "--ignore-not-found", "secret", "scalyr-api-key"])
    # Define API key
    _run_kubectl(
        [
            "--namespace=scalyr",
            "create",
            "secret",
            "generic",
            "scalyr-api-key",
            f"--from-literal=scalyr-api-key={scalyr_api_key}",
        ]
    )
    yield
    _run_kubectl(["--namespace=scalyr", "delete", "secret", "scalyr-api-key"])


@pytest.fixture(scope="session")
def cluster_name(image_name, test_session_suffix):
    return f"{image_name}-test-{test_session_suffix}"


@pytest.fixture(scope="session")
def prepare_agent_configmap(cluster_name, tmp_path_factory, scalyr_namespace):
    # Create configmap

    _run_kubectl([
        "--namespace=scalyr", "delete", "--ignore-not-found", "configmap", "scalyr-config",
    ])

    configmap_source_manifest_path = SOURCE_ROOT / "k8s/no-kustomize/scalyr-agent-2-configmap.yaml"

    with configmap_source_manifest_path.open("r") as f:
        manifest = yaml.load(f)

    # Slightly modify default config map.
    manifest["data"]["SCALYR_K8S_CLUSTER_NAME"] = cluster_name
    manifest["data"]["SCALYR_K8S_VERIFY_KUBELET_QUERIES"] = "false"
    config_map_path = tmp_path_factory.mktemp("agent-configmap") / configmap_source_manifest_path.name

    with config_map_path.open("w") as f:
        yaml.dump(manifest, f)

    _run_kubectl([
        "apply",
        "-f",
        str(config_map_path)
    ])

    yield
    _run_kubectl([
        "--namespace=scalyr", "delete", "-f", str(config_map_path),
    ])


@pytest.fixture(scope="session")
def agent_manifest_path(full_image_name, tmp_path_factory):
    # Modify the manifest for the agent's daemonset.
    scalyr_agent_manifest_source_path = SOURCE_ROOT / "k8s/no-kustomize/scalyr-agent-2.yaml"
    scalyr_agent_manifest = scalyr_agent_manifest_source_path.read_text()

    # Change the production image name to the local one.
    scalyr_agent_manifest = re.sub(
        r"image: scalyr/scalyr-k8s-agent:\d+\.\d+\.\d+",
        f"image: {full_image_name}",
        scalyr_agent_manifest,
    )
    # Change image pull policy to be able to pull the local image.
    scalyr_agent_manifest = re.sub(
        r"imagePullPolicy: \w+", "imagePullPolicy: Never", scalyr_agent_manifest
    )

    tmp_dir = tmp_path_factory.mktemp("agent_manifest")

    # Create new manifest file for the agent daemonset.
    scalyr_agent_manifest_path = tmp_dir / "scalyr-agent-2.yaml"

    scalyr_agent_manifest_path.write_text(scalyr_agent_manifest)

    yield scalyr_agent_manifest_path


@pytest.fixture(scope="session")
def start_test_log_writer_pod(minikube):
    """
    Return function which created pod that writes counter messages which are needed to verify ingestion to Scalyr server.
    """
    manifest_path = pl.Path(__file__).parent / "fixtures/log_writer_pod.yaml"

    _run_kubectl([
        "delete", "--ignore-not-found", "deployment", "test-log-writer"
    ])

    def start():
        _run_kubectl([
            "apply", "-f", str(manifest_path)
        ])

        # Get name of the created pod.
        pod_name = (
            check_output_with_log([
                "kubectl",
                "get",
                "pods",
                "--selector=app=test-log-writer",
                "--sort-by=.metadata.creationTimestamp",
                "-o",
                "jsonpath={.items[-1].metadata.name}",
            ]).decode().strip()
        )
        return pod_name

    yield start
    _run_kubectl([
        "delete", "--ignore-not-found", "-f", str(manifest_path)
    ])


@pytest.fixture(scope="session")
def create_agent_daemonset(
    agent_manifest_path, minikube
):
    """
    Return function which starts agent daemonset.
    """

    _run_kubectl([
        "--namespace=scalyr", "delete", "--ignore-not-found", "daemonset", "scalyr-agent-2"
    ])

    # Create agent's daemonset.
    def create():
        check_output_with_log(["kubectl", "apply", "-f", str(agent_manifest_path)])

        # Get name of the created pod.
        pod_name = (
            check_output_with_log([
                "kubectl",
                "--namespace=scalyr",
                "get",
                "pods",
                "--selector=app=scalyr-agent-2",
                "--sort-by=.metadata.creationTimestamp",
                "-o",
                "jsonpath={.items[-1].metadata.name}",
            ]).decode().strip()
        )
        return pod_name

    yield create

    # Cleanup
    _run_kubectl([
        "--namespace=scalyr", "delete", "-f", str(agent_manifest_path)
    ])


def _get_agent_log_content(pod_name: str):
    """
    Read content of the agent log file in the agent pod.
    """

    return  subprocess.check_output([
        "kubectl",
        "--namespace=scalyr",
        "exec",
        "-i",
        pod_name,
        "--container",
        "scalyr-agent",
        "--",
        "cat",
        "/var/log/scalyr-agent-2/agent.log"
    ]).decode()


@pytest.mark.usefixtures(
    "minikube",
    "prepare_scalyr_agent_service_account",
    "prepare_scalyr_api_key_secret",
    "prepare_agent_configmap",
)
def test(
    agent_manifest_path,
    scalyr_api_read_key,
    scalyr_server,
    cluster_name,
    create_agent_daemonset,
    start_test_log_writer_pod,

):

    log.info(f"Starting test. Scalyr logs can be found by the cluster name: {cluster_name}")

    agent_pod_name = create_agent_daemonset()
    # Wait a little.
    time.sleep(5)

    test_writer_pod_name = start_test_log_writer_pod()

    time.sleep(5)

    log.info("Verify pod logs.")
    verify_logs(
        scalyr_api_read_key=scalyr_api_read_key,
        scalyr_server=scalyr_server,
        get_agent_log_content=functools.partial(_get_agent_log_content, pod_name=agent_pod_name),
        # Since the test writer pod writes plain text counters, set this count getter.
        counter_getter=lambda e: int(e["message"].rstrip("\n")),
        counters_verification_query_filters=[
            f"$pod_name=='{test_writer_pod_name}'",
            "$app=='test-log-writer'",
            f"$k8s-cluster=='{cluster_name}'",
        ],
    )

    logging.info("Test passed!")