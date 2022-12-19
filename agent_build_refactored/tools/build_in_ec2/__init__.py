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

import dataclasses
import os
import logging
import time
import shlex
import random
import json
import datetime
from typing import List, Dict

logger = logging.getLogger(__name__)


# All the instances created by this script will use this string in the name.
INSTANCE_NAME_STRING = "automated-agent-ci-cd"

MAX_PREFIX_LIST_UPDATE_ATTEMPTS = 20

# Age of the prefix entry ofter which it can be cleaned up.
PREFIX_LIST_ENTRY_REMOVE_THRESHOLD = 60 * 7  # Minutes

# We delete any old automated test nodes which are older than 4 hours
DELETE_OLD_NODES_TIMEDELTA = datetime.timedelta(hours=4)
DELETE_OLD_NODES_THRESHOLD_DT = datetime.datetime.utcnow() - DELETE_OLD_NODES_TIMEDELTA


@dataclasses.dataclass
class EC2DistroImage:
    """
    Simple specification of the ec2 AMI image.
    """
    image_id: str
    image_name: str
    size_id: str
    ssh_username: str


@dataclasses.dataclass
class AWSSettings:
    """
    Dataclass that stores all settings that are required to manipulate AWS objects.
    """
    access_key: str
    secret_key: str
    private_key_path: str
    private_key_name: str
    region: str
    security_group: str
    security_groups_prefix_list_id: str
    ec2_objects_name_prefix: str

    @staticmethod
    def create_from_env():
        vars_name_prefix = os.environ.get("AWS_ENV_VARS_PREFIX", "")

        def _validate_setting(name):

            final_name = f"{vars_name_prefix}{name}"
            value = os.environ.get(final_name)
            if value is None:
                raise Exception(f"Env. variable '{final_name}' is not found.")

            return value

        return AWSSettings(
            access_key=_validate_setting("AWS_ACCESS_KEY"),
            secret_key=_validate_setting("AWS_SECRET_KEY"),
            private_key_path=_validate_setting("AWS_PRIVATE_KEY_PATH"),
            private_key_name=_validate_setting("AWS_PRIVATE_KEY_NAME"),
            region=_validate_setting("AWS_REGION"),
            security_group=_validate_setting("AWS_SECURITY_GROUP"),
            security_groups_prefix_list_id=_validate_setting("AWS_SECURITY_GROUPS_PREFIX_LIST_ID"),
            ec2_objects_name_prefix=_validate_setting("AWS_OBJECTS_NAME_PREFIX")
        )

    def create_libcloud_ec2_driver(self):
        from libcloud.compute.types import Provider
        from libcloud.compute.providers import get_driver

        driver_cls = get_driver(Provider.EC2)
        return driver_cls(
            self.access_key,
            self.secret_key,
            region=self.region
        )

    def create_boto3_ec2_client(self):
        import boto3
        return boto3.client(
            "ec2",
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
        )


def create_ec2_instance_node(
        ec2_image: EC2DistroImage,
        aws_settings: AWSSettings,
        file_mappings: Dict = None,
        deployment_script_content: str = None,
        max_tries: int = 3,
        deploy_overall_timeout: int = 100,
):
    """
    Create EC2 instance node.
    :param ec2_image: Image that has to be used to create instance node.
    :param aws_settings: AWS settings.
    :param file_mappings: Files that has to be copied to new instance.
    :param deployment_script_content: If not None, string with deployment script that has to be executed when node is
        created.
    :param max_tries: Max tried for node deployment.
    :param deploy_overall_timeout: Timeout in seconds for deployment.
    :return:
    """
    from libcloud.compute.base import NodeImage
    from libcloud.compute.base import NodeSize
    from libcloud.compute.base import DeploymentError
    from libcloud.compute.deployment import (
        FileDeployment,
        ScriptDeployment,
        MultiStepDeployment,
    )

    boto3_client = aws_settings.create_boto3_ec2_client()

    ec2_driver = aws_settings.create_libcloud_ec2_driver()

    cleanup_old_prefix_list_entries(
        boto3_client=boto3_client,
        prefix_list_id=aws_settings.security_groups_prefix_list_id,
    )
    cleanup_old_ec2_test_instance(
        libcloud_ec2_driver=ec2_driver,
    )

    add_current_ip_to_prefix_list(
        client=boto3_client,
        prefix_list_id=aws_settings.security_groups_prefix_list_id,
        ec2_objects_name_prefix=aws_settings.ec2_objects_name_prefix
    )

    size = NodeSize(
        id=ec2_image.size_id,
        name=ec2_image.size_id,
        ram=0,
        disk=16,
        bandwidth=0,
        price=0,
        driver=ec2_driver,
    )
    image = NodeImage(
        id=ec2_image.image_id, name=ec2_image.image_name, driver=ec2_driver
    )

    name = f"{INSTANCE_NAME_STRING}-{aws_settings.ec2_objects_name_prefix}-{ec2_image.image_name}"

    logger.info("Starting node provisioning ...")

    file_mappings = file_mappings or {}

    file_deployment_steps = []

    script_deployment = None
    if deployment_script_content:
        script_deployment = ScriptDeployment(deployment_script_content)
        file_deployment_steps.append(script_deployment)

    for source, dst in file_mappings.items():
        file_deployment_steps.append(FileDeployment(str(source), str(dst)))

    deployment = MultiStepDeployment(add=file_deployment_steps)

    try:
        return ec2_driver.deploy_node(
            name=name,
            image=image,
            size=size,
            ssh_key=aws_settings.private_key_path,
            ex_keyname=aws_settings.private_key_name,
            ex_security_groups=[aws_settings.security_group],
            ssh_username=ec2_image.ssh_username,
            ssh_timeout=20,
            max_tries=max_tries,
            wait_period=15,
            timeout=deploy_overall_timeout,
            deploy=deployment,
            at_exit_func=destroy_node_and_cleanup,
            # Set additional option for block devices to increase root volume size.
            ex_blockdevicemappings=[
                {
                    "DeviceName": "/dev/sda1",
                    "VirtualName": f"{name}_volume",
                    "Ebs": {
                        "DeleteOnTermination": True,
                        "VolumeSize": 32
                    }
                }
            ]
        )
    except DeploymentError as e:
        stdout = getattr(e.original_error, "stdout", None)
        stderr = getattr(e.original_error, "stderr", None)
        logger.exception(
            f"Deployment is not successful.\nStdout: {stdout}\nStderr: {stderr}"
        )
        raise
    finally:
        if script_deployment:
            logger.info(
                "Deployment script output:\n"
                f"STDOUT: {script_deployment.stdout}\n"
                f"STDERR: {script_deployment.stderr}\n"
            )
            if script_deployment.exit_status != 0:
                raise Exception(f"Deployment script has failed with exit code: {script_deployment.exit_status}")


def run_ssh_command_on_node(
        command: List[str],
        node,
        ssh_username: str,
        private_key_path: str,
        as_root: bool = False
):
    """
    Run command though SSH on EC2 node.
    :param command: Command to execute.
    :param node: EC2 instance node.
    :param ssh_username: Node username.
    :param private_key_path: Path to a private key.
    :param as_root: If True, run command as root.
    """
    import paramiko

    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=node.public_ips[0],
        port=22,
        username=ssh_username,
        key_filename=str(private_key_path),
    )

    command_str = shlex.join(command)  # pylint: disable=no-member

    if as_root:
        command_str = f"sudo -E {command_str}"

    stdin, stdout, stderr = ssh.exec_command(
        command=command_str,
    )

    logger.info(f"STDOUT: {stdout.read().decode()}")
    logger.info(f"STDERR: {stderr.read().decode()}")

    return_code = stdout.channel.recv_exit_status()

    ssh.close()

    if return_code != 0:
        raise Exception(
            f"SSH command '{command_str}' returned {return_code}."
        )


def add_current_ip_to_prefix_list(client, prefix_list_id: str, ec2_objects_name_prefix: str = None):
    """
    Add new CIDR entry with current public IP in to the prefix list. We also additionally store json object in the
        Description of the prefix list entry. This json object has required field called 'time' with timestamp
        which is used by the cleanup script to remove old prefix lists.

    We have to add current IP to the prefix list in order to provide access for the runner to ec2 instances and have
        to do it every time because there are too many IPs for the GitHub actions and AWS prefix lists can not store
        so many.
    :param client: ec2 boto3 client.
    :param prefix_list_id: ID of the prefix list.
    :param ec2_objects_name_prefix: Optional filed to add to the json object that is stored in the Description
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
                            {"time": time.time(), "workflow_id": ec2_objects_name_prefix}
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


def cleanup_old_prefix_list_entries(
    boto3_client,
    prefix_list_id: str,
    ec2_objects_name_prefix: str = None
):
    """
    Cleanup ec2 test related prefix lists entries.
    :param boto3_client: boto3 client.
    :param prefix_list_id: Prefix list ID.
    :param ec2_objects_name_prefix: Workflow id to filter workflow related entries.
    :return:
    """
    resp = boto3_client.get_managed_prefix_list_entries(PrefixListId=prefix_list_id)
    entries = resp["Entries"]

    entries_to_remove = {}

    current_time = time.time()

    # Remove old prefix list entries.
    for entry in entries:
        timestamp = _parse_entry_timestamp(entry)
        if timestamp <= current_time - PREFIX_LIST_ENTRY_REMOVE_THRESHOLD:
            entries_to_remove[entry["Cidr"]] = entry

    # If workflow provided, then we also remove entries that have matching workflow_id field in
    # their Description field.
    if ec2_objects_name_prefix:
        for entry in entries:
            description = _parse_entry_description(entry)
            if description["workflow_id"] and description["workflow_id"] == ec2_objects_name_prefix:
                entries_to_remove[entry["Cidr"]] = entry

    if not entries_to_remove:
        return

    print(f"Removing entries: {entries_to_remove}")
    _remove_entries(
        client=boto3_client,
        entries=list(entries_to_remove.values()),
        prefix_list_id=prefix_list_id,
    )


def cleanup_old_ec2_test_instance(libcloud_ec2_driver, ec2_objects_name_prefix: str = None):
    """
    Cleanup old ec2 test instances.
    """
    from libcloud.utils.iso8601 import parse_date

    nodes = libcloud_ec2_driver.list_nodes()

    print("Looking for and deleting old running automated test nodes...")

    nodes_to_delete = []

    for node in nodes:
        if INSTANCE_NAME_STRING not in node.name:
            continue

        # Re remove instances which are created by the current workflow immediately.
        if ec2_objects_name_prefix and ec2_objects_name_prefix in node.name:
            nodes_to_delete.append(node)
            continue

        launch_time = node.extra.get("launch_time", None)

        if not launch_time:
            continue

        launch_time_dt = parse_date(launch_time).replace(tzinfo=None)
        if launch_time_dt >= DELETE_OLD_NODES_THRESHOLD_DT:
            continue

        print(('Found node "%s" for deletion.' % (node.name)))

        nodes_to_delete.append(node)

    # TODO: For now we only print the node names to ensure script doesn't incorrectly delete
    # wrong nodes. We should uncomment out deletion once we are sure the script is correct.
    for node in nodes_to_delete:
        assert INSTANCE_NAME_STRING in node.name
        print("")
        destroy_node_and_cleanup(driver=libcloud_ec2_driver, node=node)

    print("")
    print("Destroyed %s old nodes" % (len(nodes_to_delete)))


def _parse_entry_description(entry: Dict):
    """
    Parse json object from the description of the prefix list entry.
    Conventionally, we store useful information in it.
    """
    return json.loads(entry["Description"])


def _parse_entry_timestamp(entry: Dict) -> float:
    """
    Parse creation timestamp of the prefix list entry.
    """
    return float(_parse_entry_description(entry)["time"])


def _remove_entries(client, entries: List, prefix_list_id: str):
    """
    Remove specified entries from prefix list.
    :param client: boto3 client.
    :param entries: List of entries to remove.
    :param prefix_list_id: Prefix list ID.
    :return:
    """
    import botocore.exceptions
    attempts = 20
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
                RemoveEntries=[{"Cidr": e["Cidr"]} for e in entries],
            )
            break
        except botocore.exceptions.ClientError as e:
            keep_trying = False
            if "The prefix list has the incorrect version number" in str(e):
                keep_trying = True

            if "The request cannot be completed while the prefix" in str(e):
                keep_trying = True

            if attempts == 0 or not keep_trying:
                raise

            attempts -= 1
            print(f"Can not modify prefix list, retry. Reason: {str(e)}")
            time.sleep(random.randint(1, 5))