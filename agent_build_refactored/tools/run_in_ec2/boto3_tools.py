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
import sys
import time
import shlex
import random
import json
import datetime
import pathlib as pl
from typing import List, Dict

import boto3
import botocore.exceptions  # pylint: disable=import-error
import paramiko
import requests

from agent_build_refactored.tools.run_in_ec2.constants import EC2DistroImage

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
            security_groups_prefix_list_id=_validate_setting(
                "AWS_SECURITY_GROUPS_PREFIX_LIST_ID"
            ),
            ec2_objects_name_prefix=_validate_setting("AWS_OBJECTS_NAME_PREFIX"),
        )

    def create_boto3_session(self):
        return boto3.session.Session(
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
        )


def create_and_deploy_ec2_instance(
    boto3_session: boto3.session.Session,
    ec2_image: EC2DistroImage,
    name_prefix: str,
    aws_settings: AWSSettings,
    root_volume_size: int = None,
    files_to_upload: Dict = None,
    deployment_script: pl.Path = None,
):
    """
    Create AWS EC2 instance and additional deploy files or scripts.
    :param boto3_session: Boto3 session.
    :param ec2_image: AMI image which is used to start instance.
    :param name_prefix: Additional name prefix for instance.
    :param aws_settings: All required AWS settings and credentials.
    :param root_volume_size: Size of root volume on GB
    :param files_to_upload:
    :param deployment_script:
    :return:
    """
    add_current_ip_to_prefix_list(
        boto3_session=boto3_session,
        prefix_list_id=aws_settings.security_groups_prefix_list_id,
        ec2_objects_name_prefix=aws_settings.ec2_objects_name_prefix,
    )

    name = f"{INSTANCE_NAME_STRING}-{ec2_image.short_name}-{aws_settings.ec2_objects_name_prefix}-{name_prefix}"

    instance = create_ec2_instance(
        boto3_session=boto3_session,
        ec2_image=ec2_image,
        name=name,
        aws_settings=aws_settings,
        root_volume_size=root_volume_size,
    )

    try:
        # Try to establish SSH connection.
        attempts = 10
        while True:
            try:
                ssh = create_ssh_connection(
                    ip=instance.public_ip_address,
                    username=ec2_image.ssh_username,
                    private_key_path=aws_settings.private_key_path,
                )
                break
            except paramiko.ssh_exception.NoValidConnectionsError:
                logger.info(
                    f"Can not establish SSH connection with {instance.public_ip_address}"
                )
                if attempts == 0:
                    logger.exception("Giving up. Error: ")
                    raise

                attempts -= 1
                logger.info("    retry in 10 seconds.")
                time.sleep(10)

        files_to_upload = files_to_upload or {}

        deployment_command = None
        if deployment_script:
            remote_deployment_script_path = pl.Path("/tmp") / deployment_script.name
            files_to_upload[str(deployment_script)] = str(remote_deployment_script_path)
            deployment_command = ["bash", str(remote_deployment_script_path)]

        if files_to_upload:
            ssh_put_files(ssh_connection=ssh, files=files_to_upload)
            if deployment_command:
                ssh_run_command(ssh_connection=ssh, command=deployment_command)

        ssh.close()
    except Exception as e:
        logger.exception("Error occurred during instance deployment.")
        instance.terminate()
        raise e

    return instance


def create_ec2_instance(
    boto3_session: boto3.session.Session,
    ec2_image: EC2DistroImage,
    name: str,
    aws_settings: AWSSettings,
    root_volume_size: int = None,
):
    """
    Create AWS EC2 instance.
    """
    ec2 = boto3_session.resource("ec2")

    security_groups = list(
        ec2.security_groups.filter(GroupNames=[aws_settings.security_group])
    )

    if len(security_groups) != 1:
        raise Exception(
            f"Number of security groups has to be 1, got '{security_groups}'"
        )

    security_group = security_groups[0]

    kwargs = {}

    if root_volume_size:
        block_device_mappings = [
            {
                "DeviceName": "/dev/sda1",
                "Ebs": {
                    "VolumeSize": root_volume_size,
                    "DeleteOnTermination": True,
                },
            }
        ]
        kwargs.update(dict(BlockDeviceMappings=block_device_mappings))

    tag_specifications = [
        {
            "ResourceType": "instance",
            "Tags": [
                {"Key": "Name", "Value": name},
            ],
        },
        {
            "ResourceType": "volume",
            "Tags": [
                {"Key": "Name", "Value": name},
            ],
        },
    ]

    kwargs.update(dict(TagSpecifications=tag_specifications))

    logger.info(
        f"Start new EC2 instance using image '{ec2_image.image_id}', size '{ec2_image.size_id}'"
    )
    attempts = 10
    while True:
        try:
            instances = ec2.create_instances(
                ImageId=ec2_image.image_id,
                MinCount=1,
                MaxCount=1,
                InstanceType=ec2_image.size_id,
                KeyName=aws_settings.private_key_name,
                SecurityGroupIds=[security_group.id],
                **kwargs,
            )
            break
        except botocore.exceptions.ClientError as e:
            if attempts == 0:
                logger.exception("    Giving up.")
                raise

            message = str(e)
            # We may catch capacity limit error from AWS, so just retry.
            no_capacity_error = (
                f"We currently do not have sufficient {ec2_image.size_id} capacity in zones with "
                f"support for 'gp2' volumes. Our system will be working on provisioning additional "
                f"capacity."
            )
            if no_capacity_error not in message:
                logger.exception("Unrecoverable error has occurred.")
                raise

            logger.info(f"    {e}")
            logger.info("    Retry...")
            attempts -= 1
            time.sleep(random.randint(10, 20))

    try:
        instance = instances[0]

        instance.wait_until_running()
        instance.reload()
    except Exception as e:
        logger.exception("Cat not create EC2 instance.")
        for ins in instances:
            ins.terminate()
        raise e

    return instance


def create_ssh_connection(
    ip: str, username: str, private_key_path: str
) -> paramiko.SSHClient:
    """
    Create SSH connection with host.
    """

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(ip, username=username, key_filename=str(private_key_path), timeout=100)
    return ssh


def ssh_put_files(ssh_connection: paramiko.SSHClient, files: Dict):
    """
    Put files to server.
    """
    sftp = ssh_connection.open_sftp()
    for src, dst in files.items():
        logger.info(f"SSH put file {src} to {dst}")
        sftp.put(str(src), str(dst))

        # also set file permissions, since it seems that they are not preserved.
        mode = pl.Path(src).stat().st_mode
        sftp.chmod(str(dst), mode)
    sftp.close()


def ssh_run_command(
    ssh_connection: paramiko.SSHClient, command: List[str], run_as_root: bool = False
):
    """
    Run command though SSH.
    :param command: Command to execute.
    :param run_as_root: If True, run command as root.
    """

    command_str = shlex.join(command)
    if run_as_root:
        command_str = f"sudo -E {command_str}"

    stdin, stdout, sterr = ssh_connection.exec_command(command_str)

    while True:
        data = stdout.channel.recv(1024)
        if data == b"":
            break
        sys.stdout.buffer.write(data)

    logger.info(f"STDERR: {sterr.read().decode()}")

    exit_status = stdout.channel.recv_exit_status()
    if exit_status != 0:
        raise Exception(f"SSH command '{command_str}' returned {exit_status}.")


def add_current_ip_to_prefix_list(
    boto3_session: boto3.Session,
    prefix_list_id: str,
    ec2_objects_name_prefix: str = None,
):
    """
    Add new CIDR entry with current public IP in to the prefix list. We also additionally store json object in the
        Description of the prefix list entry. This json object has required field called 'time' with timestamp
        which is used by the cleanup script to remove old prefix lists.

    We have to add current IP to the prefix list in order to provide access for the runner to ec2 instances and have
        to do it every time because there are too many IPs for the GitHub actions and AWS prefix lists can not store
        so many.
    :param boto3_session: ec2 boto3 client.
    :param prefix_list_id: ID of the prefix list.
    :param ec2_objects_name_prefix: Optional filed to add to the json object that is stored in the Description
        filed of the entry.
    """

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

    boto3_client = boto3_session.client("ec2")

    attempts = 0
    # Since there may be multiple running ec2 tests, we have to add the retry
    # logic to overcome the prefix list concurrent access issues.
    while True:
        try:
            version = get_prefix_list_version(
                client=boto3_client, prefix_list_id=prefix_list_id
            )

            boto3_client.modify_managed_prefix_list(
                PrefixListId=prefix_list_id,
                CurrentVersion=version,
                AddEntries=[
                    {
                        "Cidr": new_cidr,
                        "Description": json.dumps(
                            {
                                "time": time.time(),
                                "workflow_id": ec2_objects_name_prefix,
                            }
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
