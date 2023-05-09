import subprocess
import time

import pytest

from tests.end_to_end_tests.containerized_agent_tests.k8s_test.conftest import AgentDeployer


@pytest.mark.usefixtures("gather_coverage")
def test(
    create_agent_deployer,
    default_agent_daemonset_manifest,
    default_agent_config_map_manifest,
    test_images_registry_host,
    kubectl_args_with_scalyr_namespace
):

    agent_deployer = create_agent_deployer()

    agent_deployer.create_daemonset_and_required_objects()

    pod_name = agent_deployer.get_daemonset_pod_name()

    agent_deployer.delete_daemonset_and_required_objects()

    a=10
