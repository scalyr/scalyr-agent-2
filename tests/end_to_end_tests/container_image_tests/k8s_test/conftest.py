import logging
import subprocess
import re
import pathlib as pl
import json
from typing import List

import pytest
import yaml

from agent_build_refactored.tools.constants import SOURCE_ROOT
from agent_build_refactored.tools import (
    check_call_with_log,
    check_output_with_log,
    check_output_with_log_debug,
)
from tests.end_to_end_tests.tools import TimeoutTracker, AgentCommander


log = logging.getLogger(__name__)


def pytest_addoption(parser):
    parser.addoption(
        "--kubernetes-version",
        dest="kubernetes_version",
        default="v1.24.3",
        help="Version of the Kubernetes for the image test.",
    )
    parser.addoption(
        "--minikube-driver",
        dest="minikube_driver",
        default="docker",
        help="Driver for the minikube (docker (default), virtualbox, hyperkit, etc).",
    )
    parser.addoption(
        "--container-runtime",
        dest="container_runtime",
        default="docker",
        choices=["docker", "containerd"],
        help="Kubernetes container runtime to test image on, e.g. docker, containerd.",
    )


@pytest.fixture(scope="session")
def kubernetes_version(request):
    """Version of the Kubernetes to test image on."""
    return request.config.option.kubernetes_version


@pytest.fixture(scope="session")
def minikube_driver(request):
    """Minikube driver (docker, virtualbox, hyperkit, etc.)"""
    return request.config.option.minikube_driver


@pytest.fixture(scope="session")
def container_runtime(request):
    """Kubernetes container runtime to test image on, e.g. docker, containerd."""
    return request.config.option.container_runtime


@pytest.fixture(scope="session")
def minikube_test_profile(kubernetes_version, minikube_driver, container_runtime):
    """
    Name of the cluster profile that has to be created by minikube in order to test the image.
    """
    profile_name = f"agent-end-to-end-test-{kubernetes_version}-{minikube_driver}-{container_runtime}".replace(
        ".", "-"
    )
    check_call_with_log(
        ["minikube", "delete", "-p", profile_name],
        description=f"Delete existing minikube cluster: {profile_name}.",
    )
    check_call_with_log(
        [
            "minikube",
            "start",
            "-p",
            profile_name,
            f"--driver={minikube_driver}",
            f"--kubernetes-version={kubernetes_version}",
            f"--container-runtime={container_runtime}",
        ],
        description=f"Start new Kubernetes cluster with profile '{profile_name}'.",
    )

    yield profile_name

    check_call_with_log(
        ["minikube", "delete", "-p", profile_name],
        description=f"Cleanup, deleteting minikube profile '{profile_name}'.",
    )


@pytest.fixture(scope="session")
def minikube_kubectl_args(minikube_test_profile) -> List[str]:
    """
    Fixture which returns list with command line arguments that can run kubectl for a current minikube
        cluster profile.
    """
    return [
        "minikube",
        "-p",
        minikube_test_profile,
        "kubectl",
        "--",
    ]


@pytest.fixture(scope="session")
def scalyr_namespace(minikube_kubectl_args, minikube_test_profile):
    """
    Create Scalyr namespace.
    """
    try:
        check_call_with_log(
            [*minikube_kubectl_args, "create", "namespace", "scalyr"],
            stderr=subprocess.PIPE,
            description="Create Scalyr namespace if not exists.",
        )
    except subprocess.CalledProcessError as e:
        if 'namespaces "scalyr" already exists' not in e.stderr.decode():
            log.exception(
                f"Can not create Scalyr namespace in minikube prufile cluster {minikube_test_profile}"
            )
            raise


@pytest.fixture(scope="session")
def agent_service_account_manifest_objects():
    """
    Parse all objects inside agent service account manifest.
    """
    service_account_manifest_source_path = (
        SOURCE_ROOT / "k8s/no-kustomize/scalyr-service-account.yaml"
    )

    return list(
        yaml.load_all(service_account_manifest_source_path.read_text(), yaml.FullLoader)
    )


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
    minikube_kubectl_args,
):
    """
    Fixture function which applies service account.
    :return:
    """

    def apply(
        service_account: dict = None,
        cluster_role: dict = None,
        cluster_role_binding: dict = None,
    ):
        service_account = service_account or default_service_account
        cluster_role = cluster_role or default_cluster_role
        cluster_role_binding = cluster_role_binding or default_cluster_role_binding

        for obj in [service_account, cluster_role, cluster_role_binding]:
            kind = obj["kind"]
            name = obj["metadata"]["name"]
            check_call_with_log(
                [
                    *minikube_kubectl_args,
                    "delete",
                    "--ignore-not-found",
                    kind,
                    name,
                ],
                description=f"Remove agent's service account {kind} with name '{name}'",
            )

        manifest_path = (
            tmp_path_factory.mktemp("serviceaccount-manifest") / "serviceaccount.yaml"
        )

        with manifest_path.open("w") as f:
            yaml.dump_all([service_account, cluster_role, cluster_role_binding], f)

        # Create agent's service account.
        check_call_with_log(
            [*minikube_kubectl_args, "apply", "-f", str(manifest_path)],
            description="Create agent's serviceaccount.",
        )

    yield apply

    # Do a cleanup.
    for obj in [
        default_service_account,
        default_cluster_role,
        default_cluster_role_binding,
    ]:
        check_call_with_log(
            [
                *minikube_kubectl_args,
                "delete",
                "--ignore-not-found",
                obj["kind"],
                obj["metadata"]["name"],
            ],
            description="Cleaning up, remove agent service account.",
        )


@pytest.fixture(scope="session")
def prepare_scalyr_api_key_secret(
    scalyr_api_key, scalyr_namespace, minikube_kubectl_args
):
    check_call_with_log(
        [
            *minikube_kubectl_args,
            "--namespace=scalyr",
            "delete",
            "--ignore-not-found",
            "secret",
            "scalyr-api-key",
        ],
        description="Remove existing scalyr API key secret.",
    )
    # Define API key
    check_call_with_log(
        [
            *minikube_kubectl_args,
            "--namespace=scalyr",
            "create",
            "secret",
            "generic",
            "scalyr-api-key",
            f"--from-literal=scalyr-api-key={scalyr_api_key}",
        ],
        description="Create new scalyr API key.",
    )
    yield
    check_call_with_log(
        [
            *minikube_kubectl_args,
            "--namespace=scalyr",
            "delete",
            "secret",
            "scalyr-api-key",
        ],
        description="Cleanup, remove scalyr api key.",
    )


@pytest.fixture
def cluster_name(
    image_name, minikube_test_profile, image_builder_name, test_session_suffix, request
):
    # Upload agent's image to minikube cluster.
    check_call_with_log(
        [
            "minikube",
            "-p",
            minikube_test_profile,
            "image",
            "load",
            "--overwrite=true",
            image_name,
        ],
        description=f"Load target agent image {image_name} to the minikube cluster with profile {minikube_test_profile}",
    )
    return f"agent-k8s-image-test-{image_builder_name}-{request.node.nodeid}-{test_session_suffix}"


@pytest.fixture
def prepare_agent_configmap(
    prepare_scalyr_api_key_secret,
    cluster_name: str,
    tmp_path: pl.Path,
    scalyr_namespace: str,
    minikube_kubectl_args,
):
    """
    Creates config map for the agent pod.
    """
    # Cleanup existing configmap.
    check_call_with_log(
        [
            *minikube_kubectl_args,
            "--namespace=scalyr",
            "delete",
            "--ignore-not-found",
            "configmap",
            "scalyr-config",
        ],
        description="Remove existing agent's configmap.",
    )

    configmap_source_manifest_path = (
        SOURCE_ROOT / "k8s/no-kustomize/scalyr-agent-2-configmap.yaml"
    )

    with configmap_source_manifest_path.open("r") as f:
        manifest = yaml.load(f, yaml.Loader)

    # Slightly modify default config map.
    manifest["data"]["SCALYR_K8S_CLUSTER_NAME"] = cluster_name
    manifest["data"]["SCALYR_K8S_VERIFY_KUBELET_QUERIES"] = "false"

    manifest_output_path = tmp_path / configmap_source_manifest_path.name

    with manifest_output_path.open("w") as f:
        yaml.dump(manifest, f, yaml.Dumper)

    check_call_with_log(
        [*minikube_kubectl_args, "apply", "-f", str(manifest_output_path)],
        description="Apply new config map for agent pod.",
    )

    yield

    check_call_with_log(
        [
            *minikube_kubectl_args,
            "--namespace=scalyr",
            "delete",
            "--ignore-not-found",
            "-f",
            str(manifest_output_path),
        ],
        description="Cleanup, remove agent's configmap.",
    )


@pytest.fixture
def agent_manifest_path(image_name, tmp_path):
    # Modify the manifest for the agent's daemonset.
    scalyr_agent_manifest_source_path = (
        SOURCE_ROOT / "k8s/no-kustomize/scalyr-agent-2.yaml"
    )
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
def start_test_log_writer_pod(minikube_kubectl_args):
    """
    Return function which created pod that writes counter messages which are needed to verify ingestion to Scalyr server.
    """
    manifest_path = pl.Path(__file__).parent / "fixtures/log_writer_pod.yaml"

    check_call_with_log(
        [
            *minikube_kubectl_args,
            "delete",
            "--ignore-not-found",
            "deployment",
            "test-log-writer",
        ],
        description="Remove existing counter messages writer pod.",
    )

    def start(timeout_tracker: TimeoutTracker):
        check_call_with_log(
            [*minikube_kubectl_args, "apply", "-f", str(manifest_path)],
            description="Create new deployment with counter messages writer pod.",
        )

        def get_pod_name():
            output = check_output_with_log(
                [
                    *minikube_kubectl_args,
                    "get",
                    "pods",
                    "--selector=app=test-log-writer",
                    "--sort-by=.metadata.creationTimestamp",
                    "-o",
                    "jsonpath={.items[-1].metadata.name}",
                ],
                description="Get name of the counter messages writer pod.",
            )
            return output.decode().strip()

        # Get name of the created pod.
        with timeout_tracker(20):
            while True:
                try:
                    return get_pod_name()
                except subprocess.CalledProcessError:
                    timeout_tracker.sleep(5)
                    continue

    yield start
    check_call_with_log(
        [
            *minikube_kubectl_args,
            "delete",
            "--ignore-not-found",
            "-f",
            str(manifest_path),
        ],
        description="Cleanup, Delete counter messages writer pod.",
    )


@pytest.fixture(scope="session")
def get_agent_log_content(minikube_kubectl_args):
    def get(pod_name: str):
        """
        Read content of the agent log file in the agent pod.
        """

        return check_output_with_log_debug(
            [
                *minikube_kubectl_args,
                "--namespace=scalyr",
                "exec",
                "-i",
                pod_name,
                "--container",
                "scalyr-agent",
                "--",
                "cat",
                "/var/log/scalyr-agent-2/agent.log",
            ],
            description=f"Get log content of the agent pod '{pod_name}'",
        ).decode()

    return get


@pytest.fixture
def create_agent_commander(
    container_agent_paths, minikube_kubectl_args, scalyr_namespace
):
    """
    Fixture function which creates AgentCommander instance that can operate
    with agent that runs inside Kubernetes pod.
    """

    def create(agent_pod_name: str):
        return AgentCommander(
            executable_args=[
                *minikube_kubectl_args,
                "--namespace",
                "scalyr",
                "exec",
                "-i",
                agent_pod_name,
                "--container",
                "scalyr-agent",
                "--",
                "scalyr-agent-2",
            ],
            agent_paths=container_agent_paths,
        )

    return create


@pytest.fixture
def create_agent_daemonset(
    agent_manifest_path,
    prepare_agent_configmap,
    prepare_scalyr_api_key_secret,
    cluster_name,
    scalyr_namespace,
    minikube_kubectl_args,
    get_agent_log_content,
    create_agent_commander,
    get_pod_status,
    start_collecting_agent_logs,
):
    """
    Return function which starts agent daemonset.
    """

    check_call_with_log(
        [
            *minikube_kubectl_args,
            "--namespace=scalyr",
            "delete",
            "--ignore-not-found",
            "daemonset",
            "scalyr-agent-2",
        ],
        description="Cleanup previous agent daemonset, if exists.",
    )

    # Create agent's daemonset.
    def create(timeout_tracker: TimeoutTracker):
        check_call_with_log(
            [*minikube_kubectl_args, "apply", "-f", str(agent_manifest_path)],
            description="Create agent daemonset.",
        )

        def get_pod_name():
            output = check_output_with_log_debug(
                [
                    *minikube_kubectl_args,
                    "--namespace=scalyr",
                    "get",
                    "pods",
                    "--selector=app=scalyr-agent-2",
                    "--sort-by=.metadata.creationTimestamp",
                    "-o",
                    "jsonpath={.items[-1].metadata.name}",
                ],
                description="Get name of the created agent daemonset.",
            )
            return output.decode().strip()

        # Wait until agent pod is created.
        with timeout_tracker(20):
            while True:
                try:
                    # Get name of the created pod.
                    pod_name = get_pod_name()
                    break
                except subprocess.CalledProcessError:
                    timeout_tracker.sleep(
                        5, message="Can not get agent pod name in time."
                    )

        # Check that pod is in "Running" phase.
        with timeout_tracker(20):
            while True:
                status = get_pod_status(pod_name=pod_name)
                if status["phase"] == "Running":
                    break
                timeout_tracker.sleep(5, message="Agent pod's phase is not running.")

        agent_commander = create_agent_commander(agent_pod_name=pod_name)

        # Also check that agent inside that pod is running.
        with timeout_tracker(20):
            while not agent_commander.is_running:
                timeout_tracker.sleep(
                    5, message="Agent hasn't started in a given time."
                )

        # Create a function which reads content of the log file of the started agent inside the pod.
        def collect_agent_logs():
            try:
                return check_output_with_log(
                    [
                        *minikube_kubectl_args,
                        "--namespace=scalyr",
                        "exec",
                        "-i",
                        pod_name,
                        "--container",
                        "scalyr-agent",
                        "--",
                        "tail",
                        "-f",
                        "/var/log/scalyr-agent-2/agent.log",
                    ]
                )
            except subprocess.CalledProcessError as e:
                return e.stdout

        # This function will be executed by a special log collector fixture to collect logs and dump them at the end.
        start_collecting_agent_logs(log_collector_func=collect_agent_logs)

        return pod_name

    yield create

    # Cleanup
    check_call_with_log(
        [
            *minikube_kubectl_args,
            "--namespace=scalyr",
            "delete",
            "--ignore-not-found",
            "-f",
            str(agent_manifest_path),
        ],
        description="Cleanup, delete agent's daemonset.",
    )


@pytest.fixture(scope="session")
def get_pod_metadata(minikube_kubectl_args):
    def get(pod_name: str):
        pod_metadata_output = check_output_with_log(
            [
                *minikube_kubectl_args,
                "-n=scalyr",
                "get",
                "pods",
                "--selector=app=scalyr-agent-2",
                "--field-selector",
                f"metadata.name={pod_name}",
                "-o",
                "jsonpath={.items[-1]}",
            ],
            description=f"Get metadata of the pod: {pod_name}",
        ).decode()

        try:
            decoded_metadata = json.loads(pod_metadata_output)
        except json.JSONDecodeError:
            log.error(f"Error while decoding pod metadata JSON. Original metadata string: {pod_metadata_output}.")
            raise

        return decoded_metadata

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
        return {s["name"]: s for s in status["containerStatuses"]}

    return get
