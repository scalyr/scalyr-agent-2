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
import pprint
import re
import subprocess
import pathlib as pl
import time
import logging
from typing import List

import pytest
import yaml

from agent_build.tools.common import check_output_with_log, check_call_with_log
from agent_build.tools.constants import SOURCE_ROOT, DockerPlatform
from tests.end_to_end_tests.verify import verify_logs, ScalyrQueryRequest

from agent_build.docker_image_builders import DOCKER_IMAGE_BUILDERS, ContainerImageBaseDistro, BULK_DOCKER_IMAGE_BUILDERS


log = logging.getLogger(__name__)


# parametrize test cases for each kubernetes builder.
# pytestmark = [
#     pytest.mark.parametrize(
#         ["image_builder_name"],
#         [
#             [builder_name] for builder_name in DOCKER_IMAGE_BUILDERS.keys() if "k8s" in builder_name
#         ],
#         indirect=True
#     ),
#     pytest.mark.parametrize(
#         ["kubernetes_version", "minikube_driver"],
#         [["v1.17.17", "docker"]],
#         #[[{"version": "v1.17.17", "driver": "docker", "runtime": "docker"}]],
#         indirect=True
#     )
# ]

pytestmark = [
    pytest.mark.usefixtures("dump_info")
]


DEFAULT_KUBERNETES_VERSION = {
        "kubernetes_version": "v1.22.7",
        "minikube_driver": "",
        "container_runtime": "docker"
}

KUBERNETES_VERSIONS = [
    {
        "kubernetes_version": "v1.17.17",
        "minikube_driver": "",
        "container_runtime": "docker"
    },
    {
        "kubernetes_version": "v1.20.15",
        "minikube_driver": "",
        "container_runtime": "docker"
    },
    {
        "kubernetes_version": "v1.21.10",
        "minikube_driver": "",
        "container_runtime": "docker"
    },
    DEFAULT_KUBERNETES_VERSION,
    {
        "kubernetes_version": "v1.23.4",
        "minikube_driver": "docker",
        "container_runtime": "containerd"
    },
    {
        "kubernetes_version": "v1.24.0",
        "minikube_driver": "docker",
        "container_runtime": "containerd"
    }
]

PARAMS = []
EXTENDED_PARAMS = []

for bulk_builder_name, bulk_builder in BULK_DOCKER_IMAGE_BUILDERS.items():
    if bulk_builder.DISTRO_TYPE == ContainerImageBaseDistro.DEBIAN:
        kubernetes_versions_to_test = KUBERNETES_VERSIONS[:]
    else:
        kubernetes_versions_to_test = [DEFAULT_KUBERNETES_VERSION]

    base_distro = bulk_builder.DISTRO_TYPE

    for image_builder in bulk_builder.IMAGE_BUILDERS:
        builder_name = image_builder.BUILDER_NAME
        if "k8s" not in builder_name:
            continue

        builder_params = {
                "image_builder_name": builder_name,
                **DEFAULT_KUBERNETES_VERSION
            }

        if builder_name == f"k8s-{base_distro.value}" and base_distro == ContainerImageBaseDistro.DEBIAN:
            # If this is a "main build", aka 'k8s-debian' then also apply different platform testing
            # in extended test mode.
            for k_v in KUBERNETES_VERSIONS:
                EXTENDED_PARAMS.append({
                    "image_builder_name": builder_name,
                    **k_v
                })
            PARAMS.append(builder_params)
        else:
            EXTENDED_PARAMS.append(builder_params)
            PARAMS.append(builder_params)








# Use debian based image as default image for extended tests.
# DEFAULT_IMAGE_BUILDER = f"k8s-{ContainerImageBaseDistro.DEBIAN.value}"
#
# BUILDERS_TO_TEST = [builder_name for builder_name in DOCKER_IMAGE_BUILDERS.keys() if "k8s" in builder_name]
#
# for k_v in KUBERNETES_VERSIONS:
#     PARAMS.append({
#         "image_builder_name": DEFAULT_IMAGE_BUILDER,
#         **k_v
#     })
#
# BUILDERS_TO_TEST.remove(DEFAULT_IMAGE_BUILDER)
#
# for builder_name in BUILDERS_TO_TEST:
#     m = re.match(r"^k8s(?P<modification>-*.*)-(?P<distro>[^-]+)$", builder_name)
#     modification = m.group("modification")
#     distro = m.group("distro")
#
#     if modification:
#         continue
#
#     # Image modifications such as 'k8s-with-openmetrics' are only tested for a "default" distribution "debian"
#     # images based on another distributions (such alpine) are tested only with their general image (e.g. k8s-alpine)
#     if modification and distro != ContainerImageBaseDistro.DEBIAN.value:
#         continue
#
#     PARAMS.append({
#         "image_builder_name": builder_name,
#         **DEFAULT_KUBERNETES_VERSION
#     })


# for builder_name in DOCKER_IMAGE_BUILDERS.keys():
#     if "k8s" not in builder_name:
#         continue
#     if builder_name == "k8s-debian":
#         kubernetes_versions = KUBERNETES_VERSIONS[:]
#     else:
#         kubernetes_versions = [DEFAULT_KUBERNETES_VERSION]
#
#     for k_v in kubernetes_versions:
#         MATRIX.append({
#             "image_builder_name": builder_name,
#             "kubernetes_version": k_v,
#         })


def pytest_generate_tests(metafunc):

    param_names =  ["image_builder_name", "kubernetes_version", "minikube_driver", "container_runtime"]

    final_params = []
    for p in EXTENDED_PARAMS:
        final_params.append(
            [p[name] for name in param_names]
        )



    metafunc.parametrize(
        param_names,
        final_params,
        indirect=True
    )


@pytest.fixture
def dump_info(run_kubectl_output, minikube_test_profile):
    info = f"""
    minikube version: {check_output_with_log(["minikube", "version"]).decode()} 
    kubectl version: {run_kubectl_output(["version"])}
    
    """
    log.info(f"TEST INFO: {info}")
    """
        echo "kubectl version"
        kubectl version
        echo ""
        echo "minikube addions"
        echo ""
        minikube addons list
        echo ""
        echo "kubectl get nodes"
        echo ""
        kubectl get nodes
        echo ""
        echo "kubectl cluster-info"
        echo ""
        kubectl cluster-info
        echo ""
        echo "kubectl get pods -A"
        echo ""
        kubectl get pods -A

        export NODE_NAME=$(kubectl get nodes -o jsonpath="{.items[0].metadata.name}")
        echo ""
        echo "kubectl describe node"
        echo ""
        kubectl describe node ${NODE_NAME}
    :return: 
    """

@pytest.fixture(scope="session")
def kubernetes_version(request):
    return request.param


@pytest.fixture(scope="session")
def minikube_driver(request):
    return request.param

@pytest.fixture(scope="session")
def container_runtime(request):
    return request.param


# @pytest.fixture(scope="session")
# def minikube_test_profile_name(kubernetes_version, minikube_driver, container_runtime):
#     return


@pytest.fixture(scope="session")
def minikube_test_profile(kubernetes_version, minikube_driver, container_runtime):
    profile_name = f"agent-end-to-end-test-{kubernetes_version}-{minikube_driver}-{container_runtime}".replace(".", "-")
    check_call_with_log([
        "minikube", "delete", "-p", profile_name
    ])
    check_call_with_log([
        "minikube",
        "start",
        "-p", profile_name,
        f"--driver={minikube_driver}",
        f"--kubernetes-version={kubernetes_version}",
        f"--container-runtime={container_runtime}"
    ])

    yield profile_name

    check_call_with_log([
        "minikube", "delete", "-p", profile_name
    ])


# @pytest.fixture
# def minikube_test_cluster(minikube_test_profile):
#     check_call_with_log([
#         "minikube",
#         "start",
#         "-p", minikube_test_profile_name,
#     ])
#     return


@pytest.fixture(scope="session")
def run_kubectl(minikube_test_profile):
    def run(cmd_args: List[str]):
        check_call_with_log([
            "minikube",
            "-p",
            minikube_test_profile,
            "kubectl",
            "--",
            *cmd_args
        ])

    return run


@pytest.fixture(scope="session")
def run_kubectl_output(minikube_test_profile):
    def run(
            cmd_args: List[str],
            stderr=None
    ):
        return check_output_with_log(
            [
                "minikube",
                "-p",
                minikube_test_profile,
                "kubectl",
                "--",
                *cmd_args
            ],
            stderr=stderr
        )

    return run


@pytest.fixture(scope="session")
def scalyr_namespace(run_kubectl_output):
    try:
        run_kubectl_output(
            ["create", "namespace", "scalyr"],
            stderr=subprocess.PIPE
        )
    except subprocess.CalledProcessError as e:
        if 'namespaces "scalyr" already exists' not in e.stderr.decode():
            raise


@pytest.fixture(scope="session")
def agent_service_account_manifest_objects():
    """
    Parse all objects inside agent service account manifest.
    :return:
    """
    service_account_manifest_source_path = (
            SOURCE_ROOT / "k8s/no-kustomize/scalyr-service-account.yaml"
    )

    return list(yaml.load_all(
        service_account_manifest_source_path.read_text(), yaml.FullLoader
    ))


@pytest.fixture
def default_service_account(agent_service_account_manifest_objects):
    return agent_service_account_manifest_objects[0].copy()


@pytest.fixture
def default_cluster_role(agent_service_account_manifest_objects):
    return agent_service_account_manifest_objects[1].copy()


@pytest.fixture
def default_cluster_role_binding(agent_service_account_manifest_objects):
    return agent_service_account_manifest_objects[2].copy()


@pytest.fixture
def apply_agent_service_account(
        default_service_account,
        default_cluster_role,
        default_cluster_role_binding,
        tmp_path_factory,
        run_kubectl
):

    def apply(
            service_account: dict = None,
            cluster_role: dict = None,
            cluster_role_binding: dict = None
    ):
        service_account = service_account or default_service_account
        cluster_role = cluster_role or default_cluster_role
        cluster_role_binding = cluster_role_binding or default_cluster_role_binding

        # Do a cleanup in case if there are existing serviceaccount related objects.
        for obj in [service_account, cluster_role, cluster_role_binding]:
            run_kubectl([
                "delete", "--ignore-not-found", obj["kind"], obj["metadata"]["name"]
            ])

        manifest_path = tmp_path_factory.mktemp("serviceaccount-manifest") / "serviceaccount.yaml"

        with manifest_path.open("w") as f:
            yaml.dump_all([service_account, cluster_role, cluster_role_binding], f)

        # Create agent's service account.
        run_kubectl(
            ["apply", "-f", str(manifest_path)]
        )

    yield apply

    # Do a cleanup.
    for obj in [default_service_account, default_cluster_role, default_cluster_role_binding]:
        run_kubectl([
            "delete", "--ignore-not-found", obj["kind"], obj["metadata"]["name"]
        ])






@pytest.fixture(scope="session")
def prepare_scalyr_api_key_secret(scalyr_api_key, scalyr_namespace, run_kubectl):

    run_kubectl(["--namespace=scalyr", "delete", "--ignore-not-found", "secret", "scalyr-api-key"])
    # Define API key
    run_kubectl(
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
    run_kubectl(["--namespace=scalyr", "delete", "secret", "scalyr-api-key"])


@pytest.fixture
def cluster_name(image_name, minikube_test_profile,image_builder_name, test_session_suffix, request):
    # Upload agent's image to minikube cluster.
    check_call_with_log(["minikube", "-p", minikube_test_profile, "image", "load", "--overwrite=true", image_name])
    return f"agent-image-test-{image_builder_name}-{request.node.nodeid}-{test_session_suffix}"


@pytest.fixture
def prepare_agent_configmap(prepare_scalyr_api_key_secret, cluster_name: str, tmp_path: pl.Path, scalyr_namespace: str, run_kubectl):
    """
    Creates config map for the agent pod.
    """
    # Cleanup existing configmap.
    run_kubectl([
        "--namespace=scalyr", "delete", "--ignore-not-found", "configmap", "scalyr-config",
    ])

    configmap_source_manifest_path = SOURCE_ROOT / "k8s/no-kustomize/scalyr-agent-2-configmap.yaml"

    with configmap_source_manifest_path.open("r") as f:
        manifest = yaml.load(f, yaml.Loader)

    # Slightly modify default config map.
    manifest["data"]["SCALYR_K8S_CLUSTER_NAME"] = cluster_name
    manifest["data"]["SCALYR_K8S_VERIFY_KUBELET_QUERIES"] = "false"

    manifest_output_path = tmp_path / configmap_source_manifest_path.name

    with manifest_output_path.open("w") as f:
        yaml.dump(manifest, f, yaml.Dumper)

    run_kubectl([
        "apply",
        "-f",
        str(manifest_output_path)
    ])

    yield

    # Cleanup
    run_kubectl([
        "--namespace=scalyr", "delete", "--ignore-not-found", "-f", str(manifest_output_path)
    ])


@pytest.fixture
def agent_manifest_path(image_name, tmp_path):
    # Modify the manifest for the agent's daemonset.
    scalyr_agent_manifest_source_path = SOURCE_ROOT / "k8s/no-kustomize/scalyr-agent-2.yaml"
    scalyr_agent_manifest = scalyr_agent_manifest_source_path.read_text()

    # Change the production image name to the local one.
    scalyr_agent_manifest = re.sub(
        r"image: scalyr/scalyr-k8s-agent:\d+\.\d+\.\d+",
        f"image: {image_name}",
        scalyr_agent_manifest,
    )
    # Change image pull policy to be able to pull the local image.
    scalyr_agent_manifest = re.sub(
        r"imagePullPolicy: \w+", "imagePullPolicy: Never", scalyr_agent_manifest
    )

    # Create new manifest file for the agent daemonset.
    scalyr_agent_manifest_path = tmp_path / "scalyr-agent-2.yaml"

    scalyr_agent_manifest_path.write_text(scalyr_agent_manifest)

    yield scalyr_agent_manifest_path


@pytest.fixture
def start_test_log_writer_pod(run_kubectl, run_kubectl_output):
    """
    Return function which created pod that writes counter messages which are needed to verify ingestion to Scalyr server.
    """
    manifest_path = pl.Path(__file__).parent / "fixtures/log_writer_pod.yaml"

    run_kubectl([
        "delete", "--ignore-not-found", "deployment", "test-log-writer"
    ])

    def start():
        run_kubectl([
            "apply", "-f", str(manifest_path)
        ])

        # Get name of the created pod.
        pod_name = (
            run_kubectl_output([
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
    run_kubectl([
        "delete", "--ignore-not-found", "-f", str(manifest_path)
    ])



@pytest.fixture
def create_agent_daemonset(
    agent_manifest_path, prepare_agent_configmap, prepare_scalyr_api_key_secret, cluster_name, scalyr_namespace, run_kubectl, run_kubectl_output
):
    """
    Return function which starts agent daemonset.
    """

    run_kubectl([
        "--namespace=scalyr", "delete", "--ignore-not-found", "daemonset", "scalyr-agent-2"
    ])

    # Create agent's daemonset.
    def create():
        run_kubectl(["apply", "-f", str(agent_manifest_path)])

        attempt = 0
        while True:
            try:
                # Get name of the created pod.
                return run_kubectl_output([
                    "--namespace=scalyr",
                    "get",
                    "pods",
                    "--selector=app=scalyr-agent-2",
                    "--sort-by=.metadata.creationTimestamp",
                    "-o",
                    "jsonpath={.items[-1].metadata.name}",
                ]).decode().strip()
            except:
                if attempt < 3:
                    log.info("New pod is not found, retry")
                    attempt += 1
                    continue
                else:
                    log.error("Could not find new agent pod name.")
                    raise


    yield create

    # Cleanup
    run_kubectl([
        "--namespace=scalyr", "delete", "--ignore-not-found", "-f", str(agent_manifest_path)
    ])


@pytest.fixture(scope="session")
def get_agent_log_content(run_kubectl_output):
    def get(pod_name: str):
        """
        Read content of the agent log file in the agent pod.
        """
        return run_kubectl_output([
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

    return get


@pytest.mark.timeout(20000)
def test_basiceeeee(
    scalyr_namespace,
    cluster_name

):
    a=10

@pytest.mark.timeout(20000)
def test_basic(
    scalyr_api_read_key,
    scalyr_server,
    cluster_name,
    create_agent_daemonset,
    apply_agent_service_account,
    start_test_log_writer_pod,
    get_agent_log_content

):

    log.info(f"Starting test. Scalyr logs can be found by the cluster name: {cluster_name}")
    apply_agent_service_account()

    agent_pod_name = create_agent_daemonset()
    # Wait a little.

    test_writer_pod_name = start_test_log_writer_pod()

    time.sleep(5)

    log.info("Verify pod logs.")
    verify_logs(
        scalyr_api_read_key=scalyr_api_read_key,
        scalyr_server=scalyr_server,
        get_agent_log_content=functools.partial(get_agent_log_content, pod_name=agent_pod_name),
        # Since the test writer pod writes plain text counters, set this count getter.
        counter_getter=lambda e: int(e["message"].rstrip("\n")),
        counters_verification_query_filters=[
            f"$pod_name=='{test_writer_pod_name}'",
            "$app=='test-log-writer'",
            f"$k8s-cluster=='{cluster_name}'",
        ],
    )

    logging.info("Test passed!")


@pytest.fixture(scope="session")
def get_pod_metadata(run_kubectl_output):
    def get(pod_name: str):
        pod_metadata_output = run_kubectl_output([
            "-n=scalyr", "get", "pods", "--selector=app=scalyr-agent-2", "--field-selector", f"metadata.name={pod_name}", "-o", "jsonpath={.items[-1]}"
        ]).decode()

        return json.loads(pod_metadata_output)

    return get


@pytest.fixture(scope="session")
def get_pod_status(get_pod_metadata):
    def get(pod_name: str):
        metadata = get_pod_metadata(pod_name=pod_name)
        return metadata["status"]

    return get


@pytest.fixture(scope="session")
def get_pod_status_container_statuses(get_pod_status):
    def get(pod_name: str):
        status = get_pod_status(pod_name=pod_name)
        return{s["name"]: s for s in status["containerStatuses"]}

    return get


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
    get_agent_log_content

):

    """
    Tests that agent exits on Kubernetes monitor's failure.
    We emulate failure of the kubernetes monitor by revoking permissions from the agent's service account.
    """
    if not image_builder_name.startswith("k8s-restart-agent-on-monitor-death"):
        pytest.skip(f"This test now only for a special preview build '{image_builder_name}'")

    cluster_role = default_cluster_role.copy()

    log.info("Removing permissions from the agent's serviceaccount to simulate Kubernetes monitor fail.")
    cluster_role["rules"] = []

    apply_agent_service_account(
        cluster_role=cluster_role
    )

    log.info("Starting agent daemonset.")
    agent_pod_name = create_agent_daemonset()
    time.sleep(10)

    agent_log = get_agent_log_content(pod_name=agent_pod_name)

    assert "Kubernetes monitor not started yet (will retry) due to error in cache initialization" in agent_log
    assert "Please ensure you have correctly configured the RBAC permissions for the scalyr-agent's service account" in agent_log

    while True:
        log.info("Wait for agent container crash...")
        container_statuses = get_pod_status_container_statuses(pod_name=agent_pod_name)
        agent_cont_status = container_statuses["scalyr-agent"]

        last_state = agent_cont_status.get("lastState")
        if not last_state:
            time.sleep(10)
            continue

        terminated_state = last_state.get("terminated")
        if not terminated_state:
            time.sleep(10)
            continue

        log.info("Agent container terminated.")
        expected_error = 'Kubernetes monitor failed to start due to cache initialization error: ' \
                         'Unable to initialize runtime in K8s cache due to "K8s API error You don\'t have permission ' \
                         f'to access /api/v1/namespaces/scalyr/pods/{agent_pod_name}.  ' \
                         'Please ensure you have correctly configured the RBAC permissions for the scalyr-agent\'s ' \
                         'service account"'
        assert expected_error == terminated_state["message"]
        break

    log.info("Agent pod restarted as expected, returning back normal serviceaccount permissions.")
    apply_agent_service_account(
        cluster_role=default_cluster_role
    )
    time.sleep(5)
    agent_log = get_agent_log_content(pod_name=agent_pod_name)

    assert re.search(r"Kubernetes cache initialized in \d+\.\d+ seconds", agent_log)
    assert "kubernetes_monitor is using docker for listing containers" in agent_log
    assert "Cluster name detected, enabling k8s metric reporting and controller information" in agent_log

    log.info("Test passed!")


def main():
    """
    This function generates GitHub Actions tests job matrix.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--extended",
        action="store_true",
        help="Return extended test job matrix"
    )

    args = parser.parse_args()

    if args.extended:
        params = EXTENDED_PARAMS[:]
    else:
        params = PARAMS[:]

    matrix = {
        "include": []
    }

    for p in params:
        image_builder_name = p["image_builder_name"]
        image_builder_cls = DOCKER_IMAGE_BUILDERS[image_builder_name]
        kubernetes_version = p["kubernetes_version"]
        minikube_driver = p["minikube_driver"]
        container_runtime = p["container_runtime"]

        matrix["include"].append({
            "pytest-params": f"{image_builder_name}-{kubernetes_version}-{minikube_driver}-{container_runtime}",
            "distro-name": image_builder_cls.DISTRO_TYPE.value,
            "os": "ubuntu-20.04",
            "python-version": "3.8.13",
        })

    print(json.dumps(matrix))


if __name__ == '__main__':
    main()
