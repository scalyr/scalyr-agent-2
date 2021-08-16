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

import argparse
import datetime
import os
import re
import subprocess
import pathlib as pl
import tempfile
import time
import sys
from typing import Union

__SOURCE_ROOT__ = pl.Path(__file__).absolute().parent.parent.parent
sys.path.append(str(__SOURCE_ROOT__))


# Timeout 5 minutes.
from tests.package_tests.common import PipeReader, check_agent_log_request_stats_in_line, assert_and_throw_if_line_an_error
from tests.package_tests.common import COMMON_TIMEOUT




def build_agent_image(builder_path: pl.Path):
    # Get the information about minikube's docker environment.
    output = subprocess.check_output(
        "minikube docker-env", shell=True
    ).decode()

    # Parse environment variables from the 'minikube docker-env' output
    env = os.environ.copy()
    for e in re.findall(r'export (\w+=".+")', output):
        (n, v), = re.findall(r'(\w+)="(.+)"', e)
        env[n] = v

    # Call the image builder script. We also pass previously parsed docker-env variables to build this image
    # within the minikube's docker, so the result agent's image is available for kubernetes.
    subprocess.check_call(
        [str(builder_path), "--tags", "k8s_test"],
        env=env
    )


_SCALYR_SERVICE_ACCOUNT_MANIFEST_PATH = __SOURCE_ROOT__ / "k8s" / "scalyr-service-account.yaml"


def _delete_k8s_objects():
    # Delete previously created objects, if presented.
    try:
        subprocess.check_call(
            "kubectl delete daemonset scalyr-agent-2", shell=True
        )
    except subprocess.CalledProcessError:
        pass
    try:
        subprocess.check_call(
            "kubectl delete secret scalyr-api-key", shell=True,
        )
    except subprocess.CalledProcessError:
        pass
    try:
        subprocess.check_call(
            "kubectl delete configmap scalyr-config", shell=True,
        )
    except subprocess.CalledProcessError:
        pass
    try:
        subprocess.check_call(
            ["kubectl", "delete", "-f", str(_SCALYR_SERVICE_ACCOUNT_MANIFEST_PATH)],
        )
    except subprocess.CalledProcessError:
        pass


def _test(scalyr_api_key: str):
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
    scalyr_agent_manifest_source_path = __SOURCE_ROOT__ / "k8s/scalyr-agent-2.yaml"
    scalyr_agent_manifest = scalyr_agent_manifest_source_path.read_text()

    # Change the production image name to the local one.
    scalyr_agent_manifest = re.sub(
        r"image: scalyr/scalyr-k8s-agent:\d+\.\d+\.\d+",
        "image: scalyr/scalyr-k8s-agent:k8s_test",
        scalyr_agent_manifest
    )

    # Change image pull policy to be able to bull the local image.
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
    pipe_reader = PipeReader(pipe=agent_log_tail_process.stdout)

    timeout_time = datetime.datetime.now() + datetime.timedelta(seconds=COMMON_TIMEOUT)

    try:
        while True:
            seconds_until_timeout = (timeout_time - datetime.datetime.now()).seconds
            if seconds_until_timeout <= 0:
                raise TimeoutError("Test has timed out.")
            line = pipe_reader.next_line(timeout=seconds_until_timeout)
            # Look for any ERROR message.
            assert_and_throw_if_line_an_error(line)

            # TODO: add more checks.

            if check_agent_log_request_stats_in_line(line):
                # The requests status message is found. Stop the loop.
                break
    finally:
        agent_log_tail_process.terminate()
        pipe_reader.close()

    print("Test passed!")

    tmp_dir.cleanup()


def main(
        builder_path: Union[str, pl.Path],
        scalyr_api_key: str
):
    builder_path = pl.Path(builder_path)

    build_agent_image(builder_path)

    _delete_k8s_objects()

    try:
        _test(scalyr_api_key)
    finally:
        _delete_k8s_objects()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-path", required=True)
    parser.add_argument("--scalyr-api-key", required=True)

    args = parser.parse_args()
    main(
        builder_path=args.package_path,
        scalyr_api_key=args.scalyr_api_key
    )
