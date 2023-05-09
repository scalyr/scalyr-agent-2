import dataclasses
import json
import pathlib as pl
import subprocess
import sys
import time
import tarfile
import logging
from typing import List, Dict

import pytest
import strictyaml
from strictyaml.ruamel.main import load_all, dump_all

from agent_build_refactored.tools.constants import SOURCE_ROOT

logger = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def minikube_profile_name():
    return "agent-end-to-end-test"


@pytest.fixture(scope="session")
def minikube_args(minikube_profile_name, agent_test_image, tmp_path_factory):
    """
    Common arguments for a minikube command that uses minikube profile that is freshly created for this test session.
    """

    # Delete existing profile, if needed.
    result = subprocess.run(
        ["minikube", "profile", "list", "-o", "json"],
        check=True,
        capture_output=True
    )
    profiles_json = result.stdout.decode()

    profiles = json.loads(profiles_json)
    exists = False

    for profile in [*profiles["invalid"], *profiles["valid"]]:
        if profile["Name"] == minikube_profile_name:
            exists = True
            break

    if exists:
        _remove_minikube_profile(
            profile_name=minikube_profile_name
        )

    # Start new minikube profile.
    subprocess.run(
        [
            "minikube",
            "-p",
            minikube_profile_name,
            "start",
            "--container-runtime=docker",
        ],
        check=True
    )

    command_args = [
        "minikube",
        "-p",
        minikube_profile_name,
    ]

    # Load agent test image to minikube cluster
    subprocess.run(
        [
            *command_args,
            "image",
            "load",
            agent_test_image
        ],
        check=True,
    )

    yield command_args

    # Cleanup, removing the profile.
    _remove_minikube_profile(
        profile_name=minikube_profile_name
    )


@pytest.fixture(scope="session")
def gather_coverage(minikube_args, request, tmp_path_factory):
    """
    This fixture writes result coverage data by extracting it from the minikube machine.
    :return:
    """
    yield

    # Only do this if ootput file for the result coverage file is specified.
    if not request.config.option.coverage_output_file:
        return

    output_file = pl.Path(request.config.option.coverage_output_file)

    coverage_tarball_dir = tmp_path_factory.mktemp("coverage_tarball")
    coverage_tarball = coverage_tarball_dir / "coverage.tar"

    # Retrieve tarball with all coverage files from the minikube machine.
    with coverage_tarball.open("wb") as f:
        try:
            subprocess.run(
                [
                    *minikube_args,
                    "ssh",
                    "--native-ssh=false",
                    "tar -v -c -f - -C /tmp/test_coverage ."
                ],
                check=True,
                stdout=f,
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as e:
            logger.exception(f"Can not get tarball with coverage files.\nStderr: {e.stderr.decode()}")
            raise

    coverage_file_to_merge_dir = tmp_path_factory.mktemp("coverage_file_to_merge")

    # Extract coverage files from the tarball.
    with tarfile.open(coverage_tarball) as tar:
        tar.extractall(coverage_file_to_merge_dir)

    # Combine all coverage retrieved coverage files in to a single result coverage file.
    coverage_files_to_merge = [str(p) for p in coverage_file_to_merge_dir.glob("*.coverage")]

    rc_file = SOURCE_ROOT / ".coveragerc"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "coverage",
            "combine",
            "--data-file",
            str(output_file),
            "--rcfile",
            str(rc_file),
            *coverage_files_to_merge
        ],
        check=True,
    )


def _remove_minikube_profile(
    profile_name: str
):
    """
    Delete minikube profile.
    :param profile_name: Name of the profile to delete
    """
    subprocess.run(
        ["minikube", "-p", profile_name, "delete"],
        check=True
    )


@pytest.fixture(scope="session")
def kubectl_args(minikube_args):
    """
    Common arguments for a kubectl CLI tool of the current minikube cluster.
    """
    return [
        *minikube_args,
        "kubectl",
        "--",
    ]


@pytest.fixture(scope="session")
def kubectl_args_with_scalyr_namespace(kubectl_args):
    """
    Common arguments for a kubectl CLI tool of the current minikube cluster but also with specified 'scalyr' namespace.
    """
    subprocess.run(
        [
            *kubectl_args,
            "create",
            "namespace",
            "scalyr"
        ],
        check=True
    )
    return [
        *kubectl_args,
        "--namespace",
        "scalyr",
    ]


@pytest.fixture(scope="session")
def default_agent_daemonset_manifest(agent_test_image) -> Dict:
    """
    Default dict that is parsed from the agent's daemonset manifest.
    """
    manifest_source_path = SOURCE_ROOT / "k8s/no-kustomize/scalyr-agent-2.yaml"

    daemonset_manifest = strictyaml.load(
        yaml_string=manifest_source_path.read_text()
    ).data

    template_specs = daemonset_manifest["spec"]["template"]["spec"]
    containers = template_specs["containers"]
    names_to_containers = {c["name"]: c for c in containers}

    agent_container = names_to_containers["scalyr-agent"]

    # We modify container image to a test variant of the image.
    agent_container["image"] = agent_test_image

    # We pull image from the local cache.
    agent_container["imagePullPolicy"] = "Never"

    # We also add new mount node directory to the agent container to persist
    # coverage files that are produced during the run of the container.
    coverage_dir = pl.Path("/tmp/test_coverage")

    coverage_output_mount_name = "test-coverage"

    volumes = daemonset_manifest["spec"]["template"]["spec"]["volumes"]

    volumes.append({
        "hostPath": {
            "path": str(coverage_dir),
            "type": ""
        },
        "name": coverage_output_mount_name
    })

    volume_mounts = agent_container["volumeMounts"]
    volume_mounts.append({
        "mountPath": str(coverage_dir),
        "name": coverage_output_mount_name
    })

    coverage_file_path = coverage_dir / f"{time.time_ns()}.coverage"

    # Also specify this env. variable that is expected by the container in order to save coverage file.
    agent_container["env"].append({
        "name": "TEST_COVERAGE_FILE_PATH",
        "value": str(coverage_file_path)
    })

    return daemonset_manifest


@pytest.fixture(scope="session")
def default_agent_config_map_manifest() -> Dict:
    """
    Default dict that is parsed from agent's config_map manifest.
    """
    config_map_source_path = SOURCE_ROOT / "k8s/no-kustomize/scalyr-agent-2-configmap.yaml"

    config_map = strictyaml.load(
        yaml_string=config_map_source_path.read_text()
    ).data

    config_map["data"]["SCALYR_K8S_CLUSTER_NAME"] = "TEST_CLUSTER"

    return config_map


@pytest.fixture(scope="session")
def service_account_objects():
    """List with objects that are defined in the agent's service account manifest file."""
    manifest_source_path = SOURCE_ROOT / "k8s/no-kustomize/scalyr-service-account.yaml"
    with manifest_source_path.open("r") as f:
        manifests = list(load_all(stream=f))

    return manifests


@pytest.fixture(scope="session")
def default_service_account_manifest(service_account_objects):
    return service_account_objects[0]


@pytest.fixture(scope="session")
def default_cluster_role_manifest(service_account_objects):
    return service_account_objects[1]


@pytest.fixture(scope="session")
def default_cluster_role_binding_manifest(service_account_objects):
    return service_account_objects[2]


@dataclasses.dataclass
class AgentDeployer:
    """
    Helper abstraction that allows to control deployment of the agent daemonset and related objects.
    """
    daemonset_manifest: Dict
    config_map_manifest: Dict
    service_account_manifest: Dict
    cluster_role_manifest: Dict
    cluster_role_binding_manifest: Dict
    scalyr_api_key: str
    kubectl_args: List[str]
    kubectl_args_with_scalyr_namespace: List[str]

    daemonset_manifest_yaml: str = dataclasses.field(init=False)
    config_map_manifest_yaml: str = dataclasses.field(init=False)
    service_account_manifest_yaml: str = dataclasses.field(init=False)
    daemonset_name: str = dataclasses.field(init=False)

    def __post_init__(self):
        self.daemonset_name = self.daemonset_manifest["metadata"]["name"]
        self.daemonset_manifest_yaml = strictyaml.as_document(
            data=self.daemonset_manifest
        ).as_yaml()

        self.config_map_manifest_yaml = strictyaml.as_document(
            data=self.config_map_manifest
        ).as_yaml()

        self.service_account_manifest_yaml = dump_all(
            documents=[
                self.service_account_manifest,
                self.cluster_role_manifest,
                self.cluster_role_binding_manifest
            ]
        )

    def create_daemonset_and_required_objects(self):
        """
        Create agent's daemonset by applying all needed manifests.
        :return:
        """

        # Create secret with scalyr API key.
        subprocess.run(
            [
                *self.kubectl_args_with_scalyr_namespace,
                "create",
                "secret",
                "generic",
                "scalyr-api-key",
                f"--from-literal=scalyr-api-key={self.scalyr_api_key}"
            ],
            check=True
        )

        def _apply_manifest(
            manifest_input: str,
        ):
            subprocess.run(
                [
                    *self.kubectl_args,
                    "apply",
                    "-f",
                    "-",
                ],
                check=True,
                input=manifest_input.encode()

            )

        # Apply config map
        _apply_manifest(manifest_input=self.config_map_manifest_yaml)
        # Apply service account objects manifests.
        _apply_manifest(manifest_input=self.service_account_manifest_yaml)
        # Finally apply manifest for agent's daemonset.
        _apply_manifest(manifest_input=self.daemonset_manifest_yaml)
        self.wait_for_deamonset_is_ready()

    def wait_for_deamonset_is_ready(self):
        """Wait for the agent daemonset is ready"""
        subprocess.run(
            [
                *self.kubectl_args_with_scalyr_namespace,
                "rollout",
                "status",
                "daemonset",
                self.daemonset_name,
                "--timeout",
                "60s"
            ],
            check=True
        )

    def get_daemonset_pod_name(self):
        """Get name of the agent pod from the agent's daemonset."""
        try:
            result = subprocess.run(
                [
                    *self.kubectl_args_with_scalyr_namespace,
                    "get",
                    "pods",
                    "-l",
                    "app=scalyr-agent-2",
                    "--sort-by=.metadata.creationTimestamp",
                    "-o=jsonpath={.items..metadata.name}"
                ],
                check=True,
                capture_output=True
            )
        except subprocess.CalledProcessError as e:
            logger.exception(f"Can not get pod agent pod name.\nStderr: {e.stderr.decode()}")
            raise

        pod_name = result.stdout.decode()
        return pod_name

    def delete_daemonset_and_required_objects(self):
        """
        Delete agent's daemonset and all related objects.
        """
        def _delete_manifest(manifest_input: str):
            subprocess.run(
                [
                    *self.kubectl_args,
                    "delete",
                    "-f",
                    "-",
                ],
                check=True,
                input=manifest_input.encode()
            )

        # Delete agent's daemonset.
        _delete_manifest(manifest_input=self.daemonset_manifest_yaml)
        # Wait for agent's pod is deleted.
        self.wait_for_daemonset_pod_is_deleted()
        # Delete service account objects.
        _delete_manifest(manifest_input=self.service_account_manifest_yaml)
        # Delete config map.
        _delete_manifest(manifest_input=self.config_map_manifest_yaml)

        # Delete scalyr API key secret.
        subprocess.run(
            [
                *self.kubectl_args_with_scalyr_namespace,
                "delete",
                "secret",
                "scalyr-api-key",
            ],
            check=True
        )

    def wait_for_daemonset_pod_is_deleted(self):
        """Wait for agent's pod is deleted"""
        subprocess.run(
            [
                *self.kubectl_args_with_scalyr_namespace,
                "wait",
                "pod",
                self.get_daemonset_pod_name(),
                "--for=delete",
                "--timeout=60s",
            ],
            check=True
        )


@pytest.fixture(scope="session")
def create_agent_deployer(
    kubectl_args,
    kubectl_args_with_scalyr_namespace,
    default_agent_daemonset_manifest,
    default_agent_config_map_manifest,
    default_service_account_manifest,
    default_cluster_role_manifest,
    default_cluster_role_binding_manifest,
    scalyr_api_key,
):
    """
    Fixture function that creates instance of the 'AgentDeployer' helper class which is
    already set up for the current minikube profile cluster.
    """

    def _create(
        daemonset_manifest: Dict = None,
        config_map_manifest:  Dict = None,
    ) -> AgentDeployer:
        """
        :param daemonset_manifest: Manifest for the agent daemonset
        :param config_map_manifest: Manifest for the agent's config_map
        :return: New instance of the deployer.
        """

        if daemonset_manifest is None:
            daemonset_manifest = default_agent_daemonset_manifest.copy()

        if config_map_manifest is None:
            config_map_manifest = default_agent_config_map_manifest.copy()

        return AgentDeployer(
            daemonset_manifest=daemonset_manifest,
            config_map_manifest=config_map_manifest,
            service_account_manifest=default_service_account_manifest,
            cluster_role_manifest=default_cluster_role_manifest,
            cluster_role_binding_manifest=default_cluster_role_binding_manifest,
            scalyr_api_key=scalyr_api_key,
            kubectl_args=kubectl_args,
            kubectl_args_with_scalyr_namespace=kubectl_args_with_scalyr_namespace
        )

    return _create
