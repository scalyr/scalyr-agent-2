# Copyright 2014-2023 Scalyr Inc.
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


import collections
import datetime
import random
import subprocess
import pathlib as pl
import time
import logging
from typing import List, Optional, Dict

import botocore.exceptions
import requests

from agent_build_refactored.tools.aws.common import COMMON_TAG_NAME, AWSSettings

from agent_build_refactored.tools.docker.common import delete_container, get_docker_container_host_port
from agent_build_refactored.tools.toolset_image import build_toolset_image

logger = logging.getLogger(__name__)

_existing_security_group_id = None


class EC2InstanceWrapper:
    def __init__(
        self,
        boto3_instance,
        private_key_path: pl.Path,
        username: str,
        ec2_client,
    ):
        self.ec2_client = ec2_client
        self.id = boto3_instance.id.lower()
        self.boto3_instance = boto3_instance
        self.private_key_path = private_key_path
        self.username = username

        self._ssh_client_container_in_docker_private_key_path = pl.Path("/tmp/mounts/private_key.pem")

        self._ssh_container_names = []
        self._main_ssh_connection_container_name: Optional[str] = None

    @property
    def ssh_hostname(self):
        return f"{self.username}@{self.boto3_instance.public_ip_address}"

    def _create_ssh_container(
        self,
        name_suffix: str,
        additional_cmd_args: List[str],
        port: str = None,

    ):
        container_name = f"agent_build_ec2_instance{self.boto3_instance.id}_ssh_container_{name_suffix}"

        toolset_image_name = build_toolset_image()

        cmd_args = [
            "docker",
            "run",
            "-d",
            f"--name={container_name}",
            f"--volume={self.private_key_path}:{self._ssh_client_container_in_docker_private_key_path}",
        ]

        if port:
            cmd_args.append(
                f"-p=0:{port}"
            )

        cmd_args.append(
            toolset_image_name
        )

        cmd_args.extend(
            additional_cmd_args
        )

        subprocess.run(
            cmd_args,
            check=True
        )

        self._ssh_container_names.append(container_name)
        return container_name

    @property
    def _common_ssh_options(self):
        return [
            "-i",
            str(self._ssh_client_container_in_docker_private_key_path),
            "-o",
            "StrictHostKeyChecking=no",
            self.ssh_hostname,
        ]

    @property
    def common_ssh_command_args(self):
        if not self._main_ssh_connection_container_name:
            self.init_ssh_connection_in_container()

        return [
            "docker",
            "exec",
            "-i",
            self._main_ssh_connection_container_name,
            "ssh",
            *self._common_ssh_options
        ]

    def init_ssh_connection_in_container(self):
        logger.info(f"Establish ssh connection with ec2 instance '{self.boto3_instance.id}'")
        self._main_ssh_connection_container_name = self._create_ssh_container(
            name_suffix="main",
            additional_cmd_args=[
                "/bin/bash",
                "-c",
                "while true; do sleep 86400; done"
            ]
        )

        retry_counts = 10
        retry_delay = 5
        while True:
            try:
                subprocess.run(
                    [
                        *self.common_ssh_command_args,
                        "echo",
                        "test",
                    ],
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError as e:
                stderr = e.stderr.decode()
                logger.info(f"    SSH connection is not established. Reason: {stderr}")
                if retry_counts == 0:
                    logger.error("    Can not establish SSH connection. Give up.")
                    raise

                retry_counts -= 1
                logger.info(f"    Retry in {retry_delay} sec.")
                time.sleep(retry_delay)
                if retry_delay < 10:
                    retry_delay += 1

            else:
                logger.info("    SSH connection has been established.")
                break

    def open_ssh_tunnel(
        self,
        remote_port: int,
        local_port: int = None

    ):

        local_port = local_port or remote_port
        full_local_port = f"{local_port}/tcp"

        container_name = self._create_ssh_container(
            name_suffix=f"tunnel_port_{local_port}",
            additional_cmd_args=[
                "ssh",
                *self._common_ssh_options,
                "-N",
                "-L",
                f"0.0.0.0:{local_port}:localhost:{remote_port}",
            ],
            port=full_local_port,
        )

        host_port = get_docker_container_host_port(
            container_name=container_name,
            container_port=full_local_port,
        )

        return host_port

    def ssh_put_files(self, src: pl.Path, dest: pl.Path):
        """
        Put files to server.
        """

        if not self._main_ssh_connection_container_name:
            self.init_ssh_connection_in_container()


        mode = src.stat().st_mode
        oct_str = oct(mode)
        a=10

        cmd = [
            "docker",
            "exec",
            "-i",
            self._main_ssh_connection_container_name,
            "ssh",
            *self._common_ssh_options,
            "dd",
            f"of={dest}",
        ]

        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
        )

        with src.open(mode="rb") as f:
            chunk_size = 1024**2
            while True:
                data = f.read(chunk_size)
                if data == b"":
                    break

                process.stdin.write(data)

        process.stdin.close()

        process.communicate()

        process.wait()

        if process.returncode != 0:
            raise subprocess.CalledProcessError(
                returncode=process.returncode,
                cmd=cmd,
            )

        final_mode = "".join(list(oct_str)[-3:])
        subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                self._main_ssh_connection_container_name,
                "ssh",
                *self._common_ssh_options,
                "chmod",
                final_mode,
                str(dest)

            ],
            check=True,
        )

    def terminate(self):

        for container_name in self._ssh_container_names:
            delete_container(
                container_name=container_name,
            )

        terminate_ec2_instances_and_security_groups(
            instances=[self.boto3_instance],
            ec2_client=self.ec2_client,
        )

    @classmethod
    def create_and_deploy_ec2_instance(
        cls,
        ec2_client,
        ec2_resource,
        image_id: str,
        size_id: str,
        ssh_username: str,
        aws_settings: AWSSettings,
        root_volume_size: int = None,
        files_to_upload: Dict = None,
        deployment_script: pl.Path = None,
    ):
        """
        Create AWS EC2 instance and additional deploy files or scripts.
        :param ec2_client: boto3 ec2 client.
        :param ec2_resource: boto3 ec2 resource instance.
        :param image_id: Id of the  AWS AMI image.
        :param size_id: Size ID for the new instance.
        :param ssh_username: Username to use within the instance3.
        :param aws_settings: All required AWS settings and credentials.
        :param root_volume_size: Size of root volume on GB
        :param files_to_upload: Additional files to upload during the deployment.
        :param deployment_script: Path to a script to run after instance is created.
        """

        global _existing_security_group_id

        name = f"cicd(disposable)-dataset-agent-{aws_settings.cicd_workflow}"

        if aws_settings.cicd_job:
            name = f"{name}-{aws_settings.cicd_job}"

        if not _existing_security_group_id:
            security_group_name = name

            resp = ec2_client.create_security_group(
                Description='Created by the dataset agent Github Actions Ci/CD to access ec2 instance that '
                            'are created during workflows. ',
                GroupName=security_group_name,
                TagSpecifications=[
                    {
                        "ResourceType": "security-group",
                        "Tags": [
                            {
                                "Key": COMMON_TAG_NAME,
                                "Value": "",
                            },
                            {
                                "Key": "CreationTime",
                                "Value": datetime.datetime.utcnow().isoformat()
                            }
                        ],
                    },
                ],
            )

            security_group_id = resp["GroupId"]
            _existing_security_group_id = security_group_id

            ip_address = _get_current_ip_address()

            # Create new security group for new instance.
            ec2_client.authorize_security_group_ingress(
                GroupId=security_group_id,
                IpPermissions=[
                    {
                        'FromPort': 22,
                        'IpProtocol': 'tcp',
                        'IpRanges': [
                            {
                                'CidrIp':  f"{ip_address}/32",
                                'Description': 'SSH access from GitHub Actions Runner',
                            },
                        ],
                        'ToPort': 22,
                    },
                ],
            )

        else:
            security_group_id = _existing_security_group_id


        if aws_settings.cicd_workflow:
            additional_tags = {
                "cicd_workflow": aws_settings.cicd_workflow
            }
        else:
            additional_tags = None
        try:
            boto3_instance = _create_ec2_instance(
                ec2_resource=ec2_resource,
                image_id=image_id,
                size_id=size_id,
                instance_name=name,
                security_group_id=security_group_id,
                private_key_name=aws_settings.private_key_name,
                root_volume_size=root_volume_size,
                additional_tags=additional_tags,
            )
        except Exception:
            ec2_client.delete_security_group(
                GroupId=security_group_id
            )
            raise
        try:
            instance = cls(
                boto3_instance=boto3_instance,
                private_key_path=aws_settings.private_key_path,
                username=ssh_username,
                ec2_client=ec2_client,
            )
        except Exception:
            boto3_instance.terminate()
            raise

        try:
            files_to_upload = files_to_upload or {}

            deployment_command_args = None
            if deployment_script:
                remote_deployment_script_path = pl.Path("/tmp") / deployment_script.name
                files_to_upload[deployment_script] = remote_deployment_script_path
                deployment_command_args = ["/bin/bash", str(remote_deployment_script_path)]

            for src, dest in files_to_upload.items():
                instance.ssh_put_files(src=pl.Path(src), dest=pl.Path(dest))

            if deployment_command_args:

                logger.info("Run initial deployment script.")
                subprocess.run(
                    [
                        *instance.common_ssh_command_args,
                        *deployment_command_args,
                    ],
                    check=True
                )
        except Exception as e:
            logger.exception("Error occurred during instance deployment.")
            instance.terminate()
            raise e

        return instance


def _create_ec2_instance(
    ec2_resource,
    image_id: str,
    size_id: str,
    instance_name: str,
    security_group_id: str,
    private_key_name: str,
    root_volume_size: int = None,
    additional_tags: Dict[str, str] = None
):
    """
    Create AWS EC2 instance.
    :param ec2_resource: boto3 ec2 resource instance.
    :param image_id: Id of the  AWS AMI image.
    :param size_id: Size ID for the new instance.
    :param instance_name: Name of the new instance.
    :param security_group_id: ID of the security group to use with new instance.
    :param private_key_name: Name of the AWS EC2 private key to use with new instance.
    :param root_volume_size: Size of root volume on GB
    :param additional_tags: Additional tags to apply to new instance.
    """

    additional_tags = additional_tags or {}

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

    resource_tags = collections.defaultdict(list)

    def _add_tag(key: str, value: str, resource_type: str):
        resource_tags[resource_type].append(
            {"Key": key, "Value": value}
        )

    _add_tag(key="Name", value=instance_name, resource_type="instance",)
    _add_tag(key="Name", value=f"{instance_name}_volume", resource_type="volume")
    _add_tag(key="Name", value=f"{instance_name}_ni", resource_type="network-interface")

    _add_tag(key=COMMON_TAG_NAME, value="", resource_type="instance")
    _add_tag(key=COMMON_TAG_NAME, value="", resource_type="volume")
    _add_tag(key=COMMON_TAG_NAME, value="", resource_type="network-interface")

    for key, value in additional_tags.items():
        _add_tag(key=key, value=value, resource_type="instance")

    tag_specifications = []
    for resource_type, tags in resource_tags.items():
        tag_specifications.append(
            {
                "ResourceType": resource_type,
                "Tags": tags,
            },
        )

    kwargs.update(dict(TagSpecifications=tag_specifications))

    logger.info(
        f"Start new EC2 instance using image '{image_id}', size '{size_id}'"
    )
    attempts = 10
    while True:
        try:
            instances = ec2_resource.create_instances(
                ImageId=image_id,
                MinCount=1,
                MaxCount=1,
                InstanceType=size_id,
                KeyName=private_key_name,
                SecurityGroupIds=[security_group_id],
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
                f"We currently do not have sufficient {size_id} capacity in zones with "
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


def _get_current_ip_address():
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
    return public_ip


def terminate_ec2_instances_and_security_groups(
    instances: List,
    ec2_client,

):
    security_groups_ids_to_remove = set()

    for instance in instances:
        for security_group in instance.security_groups:
            security_groups_ids_to_remove.add(
                security_group["GroupId"]
            )

        logger.info(f"Terminate ec2 instance {instance.id}")
        instance.terminate()

    for instance in instances:
        instance.wait_until_terminated()

        for security_group_id in security_groups_ids_to_remove:
            logger.info(f"Delete Security group '{security_group_id}'.")
            attempts = 5
            delay = 20
            while True:
                try:
                    ec2_client.delete_security_group(
                        GroupId=security_group_id,
                    )
                except botocore.exceptions.ClientError as e:
                    if "has a dependent object" in str(e):
                        logger.info("    Security group still has dependent objects.")
                        if attempts == 0:
                            logger.exception("    Give up")
                            raise

                        logger.info(f"    Retry in {delay} sec.")
                        attempts -= 1
                        time.sleep(delay)
                        continue
                    elif "InvalidGroup.NotFound" in str(e):
                        logger.info("    Security group does not exists. Ignore.")
                        break
                    else:
                        raise