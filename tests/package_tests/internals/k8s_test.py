#!/usr/bin/env python3
# Copyright 2014-2021 Scalyr Inc.
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

import os
import re
import subprocess
import pathlib as pl
import tempfile
import time
import sys
import logging


from agent_build.tools import constants
from tests.package_tests.internals.common import SOURCE_ROOT
from tests.package_tests.internals.common import AgentLogRequestStatsLineCheck, AssertAgentLogLineIsNotAnErrorCheck, LogVerifier


_SCALYR_SERVICE_ACCOUNT_MANIFEST_PATH = SOURCE_ROOT / "k8s" / "scalyr-service-account.yaml"


def _delete_k8s_objects():
    # Delete previously created objects, if presented.

    # Suppress output for the delete commands, unless it not DEBUG mode.
    if logging.root.level == logging.DEBUG:
        stdout = sys.stdout
        stderr = sys.stderr
    else:
        stdout = subprocess.DEVNULL
        stderr = subprocess.DEVNULL
    try:
        subprocess.check_call(
            "kubectl delete daemonset scalyr-agent-2", shell=True, stdout=stdout, stderr=stderr
        )
    except subprocess.CalledProcessError:
        pass
    try:
        subprocess.check_call(
            "kubectl delete secret scalyr-api-key", shell=True, stdout=stdout, stderr=stderr
        )
    except subprocess.CalledProcessError:
        pass
    try:
        subprocess.check_call(
            "kubectl delete configmap scalyr-config", shell=True, stdout=stdout, stderr=stderr
        )
    except subprocess.CalledProcessError:
        pass
    try:
        subprocess.check_call(
            ["kubectl", "delete", "-f", str(_SCALYR_SERVICE_ACCOUNT_MANIFEST_PATH)], stdout=stdout, stderr=stderr
        ),
    except subprocess.CalledProcessError:
        pass


def _test(
    image_name: str,
    architecture: constants.Architecture,
    scalyr_api_key: str
):
    # Create agent's service account.
    subprocess.check_call(
        ["kubectl", "create", "-f", str(_SCALYR_SERVICE_ACCOUNT_MANIFEST_PATH)]
    )

    # Define API key
    subprocess.check_call(
        ["kubectl", "create", "secret", "generic", "scalyr-api-key", f"--from-literal=scalyr-api-key={scalyr_api_key}"]
    )

    # Create configmap
    subprocess.check_call(
        [
            "kubectl", "create", "configmap", "scalyr-config",
            "--from-literal=SCALYR_K8S_CLUSTER_NAME=ci-agent-k8s-",
        ]
    )

    # Modify the manifest for the agent's daemonset.
    scalyr_agent_manifest_source_path = SOURCE_ROOT / "k8s/scalyr-agent-2.yaml"
    scalyr_agent_manifest = scalyr_agent_manifest_source_path.read_text()

    # Change the production image name to the local one.
    scalyr_agent_manifest = re.sub(
        r"image: scalyr/scalyr-k8s-agent:\d+\.\d+\.\d+",
        f"image: {image_name}",
        scalyr_agent_manifest
    )

    # Change image pull policy to be able to pull the local image.
    scalyr_agent_manifest = re.sub(
        r"imagePullPolicy: \w+", "imagePullPolicy: Never", scalyr_agent_manifest
    )

    # Create new manifest file for the agent daemonset.
    tmp_dir = tempfile.TemporaryDirectory(prefix="scalyr-agent-k8s-test")

    scalyr_agent_manifest_path = pl.Path(tmp_dir.name) / "scalyr-agent-2.yaml"

    scalyr_agent_manifest_path.write_text(scalyr_agent_manifest)

    # Create agent's daemonset.
    subprocess.check_call([
        "kubectl", "create", "-f", str(scalyr_agent_manifest_path)
    ])

    # Get name of the created pod.
    pod_name = subprocess.check_output(
        "kubectl get pods --sort-by=.metadata.creationTimestamp -o jsonpath=\"{.items[-1].metadata.name}\"", shell=True
    ).decode().strip()

    # Wait a little.
    time.sleep(3)

    # Execute tail -f command on the agent.log inside the pod to read its content.
    agent_log_tail_process = subprocess.Popen(
        ["kubectl", "exec", pod_name, "--container", "scalyr-agent", "--", "tail", "-f", "-n+1",
         "/var/log/scalyr-agent-2/agent.log"],
        stdout=subprocess.PIPE
    )
    # Read lines from agent.log. Create pipe reader to read lines from the previously created tail process.

    # Also set the mode for the process' std descriptor as non-blocking.
    os.set_blocking(agent_log_tail_process.stdout.fileno(), False)

    try:
        logging.info("Start verifying the agent.log file.")
        # Create verifier object for the agent.log file.
        agent_log_tester = LogVerifier()

        # set the 'read' method of the 'stdout' pipe of the previously created tail process as a "content getter" for
        # the log verifier, so it can fetch new data from the pipe when it is available.
        agent_log_tester.set_new_content_getter(agent_log_tail_process.stdout.read)

        # Add check for any ERROR messages to the verifier.
        agent_log_tester.add_line_check(AssertAgentLogLineIsNotAnErrorCheck())
        # Add check for the request stats message.
        agent_log_tester.add_line_check(AgentLogRequestStatsLineCheck(), required_to_pass=True)

        # Start agent.log file verification.
        agent_log_tester.verify(timeout=300)
    finally:
        agent_log_tail_process.terminate()
        tmp_dir.cleanup()

    logging.info("Test passed!")


def run(
    image_name: str,
    architecture: constants.Architecture,
    scalyr_api_key: str
):
    """
    :param image_name: Full name of the image to test.
    :param architecture: Architecture of the image to test.
    :param scalyr_api_key: Scalyr API key.
    """

    _delete_k8s_objects()

    # Make image visible for the munikube cluster.
    subprocess.check_call(
        ["minikube", "image", "load", image_name]
    )

    try:
        _test(
            image_name,
            architecture,
            scalyr_api_key
        )
    finally:
        logging.info("Clean up. Removing all kubernetes objects...")
        _delete_k8s_objects()
