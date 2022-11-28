import dataclasses
import logging
import os
import pathlib as pl
import shlex
import time
from typing import List, Dict, Optional

from agent_build_refactored.tools.constants import Architecture
from tests.end_to_end_tests.run_in_remote_machine.ec2_prefix_lists import add_current_ip_to_prefix_list, remove_prefix_list_entry

logger = logging.getLogger(__name__)

# All the instances created by this script will use this string in the name.
INSTANCE_NAME_STRING = "automated-agent-tests-"
assert "-tests-" in INSTANCE_NAME_STRING


@dataclasses.dataclass
class EC2DistroImage:
    image_id: str
    image_name: str
    size_id: str
    ssh_username: str


@dataclasses.dataclass
class AwsSettings:
    access_key: str
    secret_key: str
    private_key_path: str
    private_key_name: str
    region: str
    security_groups: List[str]


def get_env_throw_if_not_set(name, default_value=None):
    # type: (str, Optional[str]) -> str
    """
    Return provided environment variable value and throw if it's not set.
    """
    value = os.environ.get(name, default_value)

    if value is None:
        raise ValueError(f"Environment variable '{name}' not set")

    return value


def destroy_node_and_cleanup(driver, node):
    """
    Destroy the provided node and cleanup any left over EBS volumes.
    """
    volumes = driver.list_volumes(node=node)

    assert (
            INSTANCE_NAME_STRING in node.name
    ), "Refusing to delete node without %s in the name" % (INSTANCE_NAME_STRING)

    print("")
    print(('Destroying node "%s"...' % (node.name)))

    try:
        node.destroy()
    except Exception as e:
        if "does not exist" in str(e):
            # Node already deleted, likely by another concurrent run. This error is not fatal so we
            # just ignore it.
            print(
                "Failed to delete node, likely node was already deleted, ignoring error..."
            )
            print(str(e))
        else:
            raise e

    assert len(volumes) <= 1
    print("Cleaning up any left-over EBS volumes for this node...")

    # Give it some time for the volume to become detached from the node
    if volumes:
        time.sleep(10)

    for volume in volumes:
        # Additional safety checks
        if volume.extra.get("instance_id", None) != node.id:
            continue

        if volume.size not in [8, 30]:
            # All the volumes we use are 8 GB EBS volumes
            # Special case is Windows 2019 with 30 GB volume
            continue

        destroy_volume_with_retry(driver=driver, volume=volume)


def destroy_volume_with_retry(driver, volume, max_retries=12, retry_sleep_delay=5):
    # type: (NodeDriver, StorageVolume, int, int) -> bool
    """
    Destroy the provided volume retrying up to max_retries time if destroy fails because the volume
    is still attached to the node.
    """
    retry_count = 0
    destroyed = False

    while not destroyed and retry_count < max_retries:
        try:
            try:
                driver.destroy_volume(volume=volume)
            except Exception as e:
                if "InvalidVolume.NotFound" in str(e):
                    pass
                else:
                    raise e
            destroyed = True
        except Exception as e:
            if "VolumeInUse" in str(e):
                # Retry in 5 seconds
                print(
                    "Volume in use, re-attempting destroy in %s seconds (attempt %s/%s)..."
                    % (retry_sleep_delay, retry_count + 1, max_retries)
                )

                retry_count += 1
                time.sleep(retry_sleep_delay)
            else:
                raise e

    if destroyed:
        print("Volume %s successfully destroyed." % (volume.id))
    else:
        print(
            "Failed to destroy volume %s after %s attempts." % (volume.id, max_retries)
        )

    return True


def run_test_in_ec2_instance(
        ec2_image: EC2DistroImage,
        test_runner_path: pl.Path,
        command: List[str],
        node_name_suffix: str,
        private_key_path: str,
        private_key_name: str,
        access_key: str,
        secret_key: str,
        region: str,
        security_group: str,
        security_groups_prefix_list_id: str,
        max_tries: int = 3,
        deploy_overall_timeout: int = 100,
        file_mappings: Dict = None,
        workflow_id: str = None
):
    import paramiko
    from libcloud.compute.types import Provider
    from libcloud.compute.base import NodeImage
    from libcloud.compute.base import NodeSize
    from libcloud.compute.base import DeploymentError
    from libcloud.compute.providers import get_driver
    from libcloud.compute.deployment import (
        FileDeployment,
        MultiStepDeployment,
    )
    import boto3

    def prepare_node():

        size = NodeSize(
            id=ec2_image.size_id,
            name=ec2_image.size_id,
            ram=0,
            disk=0,
            bandwidth=0,
            price=0,
            driver=driver,
        )
        image = NodeImage(
            id=ec2_image.image_id,
            name=ec2_image.image_name,
            driver=driver
        )

        name = f"{INSTANCE_NAME_STRING}-{node_name_suffix}-{ec2_image.image_name}"

        logger.info("Starting node provisioning ...")

        file_mappings[test_runner_path] = f"/tmp/test_runner"

        file_deployment_steps = []
        for source, dst in file_mappings.items():
            file_deployment_steps.append(
                FileDeployment(str(source), str(dst))
            )

        deployment = MultiStepDeployment(add=file_deployment_steps)

        try:
            node = driver.deploy_node(
                name=name,
                image=image,
                size=size,
                ssh_key=private_key_path,
                ex_keyname=private_key_name,
                ex_security_groups=[security_group],
                ssh_username=ec2_image.ssh_username,
                ssh_timeout=20,
                max_tries=max_tries,
                wait_period=15,
                timeout=deploy_overall_timeout,
                deploy=deployment,
                at_exit_func=destroy_node_and_cleanup,
            )
        except DeploymentError as e:
            print("Deployment failed: %s" % (str(e)))
            node = e.node
            stdout = getattr(e.original_error, "stdout", None)
            stderr = getattr(e.original_error, "stderr", None)
            raise Exception(f"Deployment is not successful.\nStdout: {stdout}\nStderr: {stderr}")

        return node

    def run_command():

        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=node.public_ips[0],
            port=22,
            username=ec2_image.ssh_username,
            key_filename=str(private_key_path)
        )

        final_command = [
            "/tmp/test_runner",
            "-s",
            *command
        ]

        command_str = shlex.join(final_command)
        stdin, stdout, stderr = ssh.exec_command(
            command=f"TEST_RUNS_REMOTELY=1 sudo -E {command_str} 2>&1",
        )

        print(f"stdout: {stdout.read().decode()}")

        ssh.close()

        assert stdout.channel.recv_exit_status() == 0, "Remote test execution has failed with."

    file_mappings = file_mappings or {}
    start_time = int(time.time())

    driver_cls = get_driver(Provider.EC2)
    driver = driver_cls(
        access_key,
        secret_key,
        region=region
    )

    boto_client = boto3.client(
        "ec2",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region
    )

    # Add current public IP to security group's prefix list.
    # We have to update that prefix list each time because there are to many GitHub actions public IPs, and
    # it is not possible to whitelist all of them in the AWS prefix list.
    add_current_ip_to_prefix_list(
        client=boto_client,
        prefix_list_id=security_groups_prefix_list_id,
        workflow_id=workflow_id
    )

    time.sleep(5)

    node = None
    try:
        node = prepare_node()
        run_command()
    finally:
        if node:
            destroy_node_and_cleanup(driver=driver, node=node)

    duration = int(time.time()) - start_time

    print(f"Succeeded! Duration: {duration} seconds")