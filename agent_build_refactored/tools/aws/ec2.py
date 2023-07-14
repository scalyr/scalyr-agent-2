import collections
import datetime
import json
import random
import shlex
import subprocess
import sys
import threading
import pathlib as pl
import time
from typing import List, Optional, Dict

import boto3
import botocore.exceptions
import paramiko
import requests

from agent_build_refactored.tools.aws.constants import COMMON_TAG_NAME, CURRENT_SESSION_TAG_NAME
from agent_build_refactored.tools.aws.boto3_tools import AWSSettings, logger, get_prefix_list_version, \
    MAX_PREFIX_LIST_UPDATE_ATTEMPTS
from agent_build_refactored.tools.aws.constants import EC2DistroImage

from agent_build_refactored.tools.docker.common import delete_container, ContainerWrapper


INSTANCE_NAME_STRING = "automated-agent-ci-cd"


class EC2InstanceWrapper:
    def __init__(
        self,
        boto3_instance,
        private_key_path: pl.Path,
        username: str,
        security_group_id: str,
        ec2_client,
    ):
        self.ec2_client = ec2_client
        self.id = boto3_instance.id.lower()
        self.boto3_instance = boto3_instance
        self.private_key_path = private_key_path
        self.username = username
        self.security_group_id = security_group_id

        self._ssh_container: Optional[ContainerWrapper] = None
        self._ssh_tunnel_containers: Dict[int, ContainerWrapper] = {}

        self._ssh_client_container_name = f"ec2_instance_{boto3_instance.id}_ssh_client"
        self._ssh_client_container_host_port = f"ec2_instance_{boto3_instance.id}_ssh_client"
        self._ssh_client_container_in_docker_private_key_path = pl.Path("/tmp/mounts/private_key.pem")

        #self.ssh_client_container_thread = threading.Thread(target=self.start_ssh_client_container)
        #self.ssh_client_container_thread.start()

        #self._ssh_container: Optional[ContainerWrapper] = self.start_ssh_client_container()

        self.ssh_client_docker_image_name: Optional[str] = None

        # self._ssh_containers: List[ContainerWrapper] = []
        #
        # self._ssh_container = self.start_ssh_client_container()

        self._paramiko_ssh_connection: Optional[paramiko.SSHClient] = None

    # def start_ssh_client_container(
    #     self,
    #     #ssh_client_docker_image_name: str,
    # ):
    #
    #     delete_container(
    #         self._ssh_client_container_name
    #     )
    #
    #     # if port:
    #     #     other_kwargs["ports"] = f"{port}/{port_protocol}"
    #     from agent_build_refactored.tools.toolset_image import build_toolset_image
    #
    #     toolset_image_name = build_toolset_image()
    #
    #     container = ContainerWrapper(
    #         name=self._ssh_client_container_name,
    #         image=toolset_image_name,
    #         volumes={self.private_key_path: self._ssh_client_container_in_docker_private_key_path},
    #         rm=True,
    #         command_args=[
    #             "/bin/bash",
    #             "-c",
    #             "while true; do sleep 86400; done"
    #         ],
    #     )
    #
    #     container.run()
    #
    #     return container

    @property
    def ssh_hostname(self):
        return f"{self.username}@{self.boto3_instance.public_ip_address}"

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
        return [
            "docker",
            "exec",
            "-i",
            self._ssh_container.name,
            "ssh",
            *self._common_ssh_options
        ]

    def open_ssh_tunnel(
        self,
        remote_port: int,
        ssh_client_docker_image_name: str,
        local_port: int = None

    ):

        local_port = local_port or remote_port
        full_local_port = f"{local_port}/tcp"

        container = ContainerWrapper(
            name=f"{self.id}_{local_port}-{remote_port}",
            image=ssh_client_docker_image_name,
            rm=False,
            ports={0: full_local_port},
            volumes={self.private_key_path: self._ssh_client_container_in_docker_private_key_path},
            command_args=[
                "ssh",
                *self._common_ssh_options,
                "-N",
                "-L",
                f"0.0.0.0:{local_port}:localhost:{remote_port}",
            ]
        )

        container.run(interactive=False)

        host_port = container.get_host_port(container_port=full_local_port)

        self._ssh_tunnel_containers[host_port] = container

        return host_port

    @property
    def paramiko_ssh_connection(self) -> paramiko.SSHClient:

        if self._paramiko_ssh_connection is not None:
            return self._paramiko_ssh_connection

        attempts = 10
        while True:
            try:
                self._paramiko_ssh_connection = paramiko.SSHClient()
                self._paramiko_ssh_connection.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                self._paramiko_ssh_connection.connect(
                    hostname=self.boto3_instance.public_ip_address,
                    username=self.username,
                    key_filename=str(self.private_key_path),
                    timeout=100
                )
                break
            except paramiko.ssh_exception.NoValidConnectionsError:
                logger.info(
                    f"Can not establish SSH connection with {self.boto3_instance.public_ip_address}"
                )
                if attempts == 0:
                    logger.exception("Giving up. Error: ")
                    raise

                attempts -= 1
                logger.info("    retry in 10 seconds.")
                time.sleep(10)

        return self._paramiko_ssh_connection

    def run_ssh_command(
        self,
        command: List[str],
        run_as_root: bool = False,
        env: Dict[str, str] = None,
    ):

        """
        Run command though SSH.
        :param command: Command to execute.
        :param run_as_root: If True, run command as root.
        :param env: Additional environment variables
        """

        command_str = shlex.join(command)
        if run_as_root:
            command_str = f"sudo -E {command_str}"

        stdin, stdout, sterr = self.paramiko_ssh_connection.exec_command(
            command_str,
            environment=env,
        )

        while True:
            data = stdout.channel.recv(1024)
            if data == b"":
                break
            sys.stdout.buffer.write(data)

        logger.info(f"STDERR: {sterr.read().decode()}")

        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            raise Exception(f"SSH command '{command_str}' returned {exit_status}.")

    def ssh_put_files(self, files: Dict):
        """
        Put files to server.
        """
        sftp = self.paramiko_ssh_connection.open_sftp()
        try:
            for src, dst in files.items():
                logger.info(f"SSH put file {src} to {dst}")
                sftp.put(str(src), str(dst))

                # also set file permissions, since it seems that they are not preserved.
                mode = pl.Path(src).stat().st_mode
                sftp.chmod(str(dst), mode)
        finally:
            sftp.close()


    def terminate(self):
        # delete_container(
        #     container_name=self._ssh_client_container_name
        # )

        for container in self._ssh_tunnel_containers.values():
            container.remove(force=True)

        if self.paramiko_ssh_connection is not None:
            self.paramiko_ssh_connection.close()

        self.boto3_instance.terminate()
        self.boto3_instance.wait_until_stopped()

        for ni in self.boto3_instance.network_interfaces:
            self.ec2_client.delete_network_interface(
                NetworkInterfaceId=ni.id
            )

        self.ec2_client.delete_security_group(
            self.security_group_id
        )


    @classmethod
    def create_and_deploy_ec2_instance(
        cls,
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

        ec2_client = boto3_session.client("ec2")

        int_time = int(time.time())
        name = f"dataset-agent-cicd(disposable)-{int_time}"
        security_group_name = f"dataset-agent-cicd(disposable)-{int_time}"

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

        ip_address = _get_current_ip_address()

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

        try:
            boto3_instance = _create_ec2_instance(
                boto3_session=boto3_session,
                ec2_image=ec2_image,
                instance_name=name,
                security_group_id=security_group_id,
                aws_settings=aws_settings,
                root_volume_size=root_volume_size,
                additional_tags=aws_settings.additional_ec2_instances_tags.copy(),
            )
        except Exception:
            ec2_client.delete_security_group(
                security_group_id
            )
            raise
        try:
            instance = cls(
                boto3_instance=boto3_instance,
                private_key_path=aws_settings.private_key_path,
                username=ec2_image.ssh_username,
                security_group_id=security_group_id,
                ec2_client=ec2_client,
            )
        except Exception:
            boto3_instance.terminate()
            raise

        try:
            files_to_upload = files_to_upload or {}

            deployment_command = None
            if deployment_script:
                remote_deployment_script_path = pl.Path("/tmp") / deployment_script.name
                files_to_upload[str(deployment_script)] = str(remote_deployment_script_path)
                deployment_command = ["bash", str(remote_deployment_script_path)]

            if files_to_upload:
                instance.ssh_put_files(files=files_to_upload)
                if deployment_command:
                    instance.run_ssh_command(command=deployment_command)
        except Exception as e:
            logger.exception("Error occurred during instance deployment.")
            instance.terminate()
            raise e

        return instance


def _create_ec2_instance(
    boto3_session: boto3.session.Session,
    ec2_image: EC2DistroImage,
    instance_name: str,
    security_group_id: str,
    aws_settings: AWSSettings,
    root_volume_size: int = None,
    additional_tags: Dict[str, str] = None
):
    """
    Create AWS EC2 instance.
    """

    additional_tags = additional_tags or []
    ec2 = boto3_session.resource("ec2")

    # security_groups = list(
    #     ec2.security_groups.filter(GroupNames=[aws_settings.security_group])
    # )

    # if len(security_groups) != 1:
    #     raise Exception(
    #         f"Number of security groups has to be 1, got '{security_groups}'"
    #     )

    #security_group = security_groups[0]

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

    instance_tags = []
    volume_tags = []

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


def create_security_group(
        boto3_session,
        cidr: str
):
    ec2_client = boto3_session.client("ec2")

    name = f"(disposable)dataset-agent-ci-cd-{int(time.time())}"

    resp = ec2_client.create_security_group(
        Description='Created by the dataset agent Github Actions Ci/CD to access ec2 instance that '
                    'are created during workflows',
        GroupName=name,
        TagSpecifications=[
            {
                "ResourceType": "security-group",
                "Tags": [
                    {
                        "Key": COMMON_TAG_NAME,
                        "Value": "",
                    },
                ],
            },
        ],
    )

    return resp["GroupId"]


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
