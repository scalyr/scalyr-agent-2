import dataclasses
import logging
import pathlib as pl
import shlex
import time
import random
import json
from typing import List, Dict

"""
This module defines main logic that is responsible for manipulating with ec2 instances to run end to end tests
inside them.
"""

logger = logging.getLogger(__name__)

# All the instances created by this script will use this string in the name.
INSTANCE_NAME_STRING = "automated-agent-tests-"

MAX_PREFIX_LIST_UPDATE_ATTEMPTS = 20


@dataclasses.dataclass
class EC2DistroImage:
    """
    Simple specification of the ec2 AMI image.
    """

    image_id: str
    image_name: str
    size_id: str
    ssh_username: str


def destroy_node_and_cleanup(driver, node):
    """
    Destroy the provided node and cleanup any left over EBS volumes.
    """

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

    volumes = driver.list_volumes(node=node)

    assert len(volumes) <= 1
    print("Cleaning up any left-over EBS volumes for this node...")

    # Wait for the volumes to become detached from the node
    remaining_volumes = volumes[:]

    timeout = time.time() + 100
    while remaining_volumes:
        if time.time() >= timeout:
            raise TimeoutError("Could not wait for all volumes being detached")
        time.sleep(1)
        remaining_volumes = driver.list_volumes(node=node)

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
    workflow_id: str = None,
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
    import boto3  # pylint: disable=import-error

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
            id=ec2_image.image_id, name=ec2_image.image_name, driver=driver
        )

        workflow_suffix = workflow_id or ""
        name = f"{INSTANCE_NAME_STRING}-{workflow_suffix}-{ec2_image.image_name}"

        logger.info("Starting node provisioning ...")

        file_mappings[test_runner_path] = "/tmp/test_runner"

        file_deployment_steps = []
        for source, dst in file_mappings.items():
            file_deployment_steps.append(FileDeployment(str(source), str(dst)))

        deployment = MultiStepDeployment(add=file_deployment_steps)

        try:
            return driver.deploy_node(
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
            stdout = getattr(e.original_error, "stdout", None)
            stderr = getattr(e.original_error, "stderr", None)
            logger.exception(
                f"Deployment is not successful.\nStdout: {stdout}\nStderr: {stderr}"
            )
            raise

    def run_command():

        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=node.public_ips[0],
            port=22,
            username=ec2_image.ssh_username,
            key_filename=str(private_key_path),
        )

        final_command = ["/tmp/test_runner", "-s", *command]

        command_str = shlex.join(final_command)  # pylint: disable=no-member
        stdin, stdout, stderr = ssh.exec_command(
            command=f"TEST_RUNS_REMOTELY=1 sudo -E {command_str} 2>&1",
        )

        logger.info(f"stdout: {stdout.read().decode()}")

        return_code = stdout.channel.recv_exit_status()

        ssh.close()

        if return_code != 0:
            raise Exception(f"Remote execution of test in ec2 instance has failed and returned {return_code}.")

    file_mappings = file_mappings or {}
    start_time = int(time.time())

    driver_cls = get_driver(Provider.EC2)
    driver = driver_cls(access_key, secret_key, region=region)

    # Add current public IP to security group's prefix list.
    # We have to update that prefix list each time because there are to many GitHub actions public IPs, and
    # it is not possible to whitelist all of them in the AWS prefix list.
    # NOTE: Take in mind that you may want to remove that IP in order to prevent prefix list from reaching its
    # size limit. For GitHub actions end-to-end tests we run a finalizer job that clears prefix list.
    boto_client = boto3.client(
        "ec2",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    )
    add_current_ip_to_prefix_list(
        client=boto_client,
        prefix_list_id=security_groups_prefix_list_id,
        workflow_id=workflow_id,
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


def get_prefix_list_version(client, prefix_list_id: str):
    """
    Get version of the prefix list.
    :param client: ec2 boto3 client.
    :param prefix_list_id: ID of the prefix list.
    """
    resp = client.describe_managed_prefix_lists(
        Filters=[
            {"Name": "prefix-list-id", "Values": [prefix_list_id]},
        ],
    )
    found = resp["PrefixLists"]
    assert (
        len(found) == 1
    ), f"Number of found prefix lists has to be 1, got {len(found)}"
    prefix_list = found[0]
    return int(prefix_list["Version"])


def add_current_ip_to_prefix_list(client, prefix_list_id: str, workflow_id: str = None):
    """
    Add new CIDR entry with current public IP in to the prefix list. We also additionally store json object in the
        Description of the prefix list entry. This json object has required field called 'time' with timestamp
        which is used by the cleanup script to remove old prefix lists.

    We have to add current IP to the prefix list in order to provide access for the runner to ec2 instances and have
        to do it every time because there are too many IPs for the GitHub actions and AWS prefix lists can not store
        so many.
    :param client: ec2 boto3 client.
    :param prefix_list_id: ID of the prefix list.
    :param workflow_id: Optional filed to add to the json object that is stored in the Description
        filed of the entry.
    """

    import botocore.exceptions  # pylint: disable=import-error
    import requests

    # Get current public IP.
    with requests.Session() as s:
        attempts = 10
        while True:
            try:
                resp = s.get("https://api.ipify.org")
                resp.raise_for_status()
                break
            except requests.HTTPError:
                if attempts == 0:
                    raise
                attempts -= 1
                time.sleep(1)

    public_ip = resp.content.decode()

    new_cidr = f"{public_ip}/32"

    attempts = 0
    # Since there may be multiple running ec2 tests, we have to add the retry
    # logic to overcome the prefix list concurrent access issues.
    while True:
        try:
            version = get_prefix_list_version(
                client=client, prefix_list_id=prefix_list_id
            )

            client.modify_managed_prefix_list(
                PrefixListId=prefix_list_id,
                CurrentVersion=version,
                AddEntries=[
                    {
                        "Cidr": new_cidr,
                        "Description": json.dumps(
                            {"time": time.time(), "workflow_id": workflow_id}
                        ),
                    },
                ],
            )
            break
        except botocore.exceptions.ClientError as e:
            if attempts >= MAX_PREFIX_LIST_UPDATE_ATTEMPTS:
                logger.exception(
                    f"Can not add new entry to the prefix list {prefix_list_id}"
                )
                raise e

            attempts += 1
            print(f"Can not modify prefix list, retry. Reason: {str(e)}")
            time.sleep(random.randint(1, 5))

    return new_cidr
