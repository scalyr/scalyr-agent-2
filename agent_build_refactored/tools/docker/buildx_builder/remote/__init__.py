import dataclasses
import logging
import pathlib as pl
import subprocess
from typing import Any, List, Optional


from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.tools.aws.boto3_tools import AWSSettings, create_and_deploy_ec2_instance
from agent_build_refactored.tools.aws.constants import EC2DistroImage

from agent_build_refactored.tools.docker.common import get_docker_container_host_port, delete_container, ContainerWrapper
from agent_build_refactored.tools.docker.buildx_builder import BuildxBuilderWrapper, BUILDKIT_VERSION
from agent_build_refactored.tools.docker.buildx_builder.remote.buildx_builder_ami import (
    get_buildx_builder_ami_image,
)

from agent_build_refactored.tools.aws.ec2 import EC2InstanceWrapper

logger = logging.getLogger(__name__)


BUILDX_BUILDER_PORT = 1234

REMOTE_DOCKER_ENGINE_IMAGE_ARM = EC2DistroImage(
    image_id="ami-0e2b332e63c56bcb5",
    image_name="Ubuntu Server 22.04 LTS (HVM), SSD Volume Type",
    short_name="ubuntu2204_ARM",
    size_id="c7g.medium",
    ssh_username="ubuntu",
)


REMOTE_DOCKER_ENGINE_IMAGES = {
    CpuArch.AARCH64: REMOTE_DOCKER_ENGINE_IMAGE_ARM,
    CpuArch.ARMV7: REMOTE_DOCKER_ENGINE_IMAGE_ARM
}


class EC2BackedRemoteBuildxBuilderWrapper(BuildxBuilderWrapper):

    def __init__(
        self,
        name: str,
        architecture: CpuArch,
        ssh_client_image_name: str,
    ):
        super(EC2BackedRemoteBuildxBuilderWrapper, self).__init__(
            name=name
        )

        self.architecture = architecture
        self.ssh_client_image_name = ssh_client_image_name

        self.buildkit_builder_container: Optional[ContainerWrapper] = None
        self.ec2_instance: Optional[EC2InstanceWrapper] = None

    def initialize(self):

        try:
            subprocess.run(
                ["docker", "buildx", "rm", "-f", self.name],
                check=True,
                capture_output=True,
                timeout=60,
            )
        except subprocess.SubprocessError as e:
            stderr = e.stderr.decode()
            if stderr != f'ERROR: no builder "{self.name}" found\n':
                raise Exception(f"Can not inspect builder. Stderr: {stderr}")

        buildkit_tunneled_local_port = self.start_buildkit_container()

        create_builder_args = [
            "docker",
            "buildx",
            "create",
            "--name",
            self.name,
            "--driver",
            "remote",
            "--bootstrap",
            f"tcp://localhost:{buildkit_tunneled_local_port}",
        ]

        subprocess.run(
            create_builder_args,
            check=True
        )

    def start_ec2_instance(
        self,
        boto3_session,
        aws_settings,
        base_ec2_image,
    ):

        remote_docker_engine_ami_image = get_buildx_builder_ami_image(
            base_ec2_image=base_ec2_image,
            boto3_session=boto3_session,
            aws_settings=aws_settings,

        )

        remote_docker_engine_image = EC2DistroImage(
            image_id=remote_docker_engine_ami_image.id,
            image_name=remote_docker_engine_ami_image.name,
            short_name=base_ec2_image.short_name,
            size_id=base_ec2_image.size_id,
            ssh_username=base_ec2_image.ssh_username,
        )

        boto3_instance = create_and_deploy_ec2_instance(
            boto3_session=boto3_session,
            ec2_image=remote_docker_engine_image,
            name_prefix="remote_docker",
            aws_settings=aws_settings,
            root_volume_size=32,
        )

        self.ec2_instance = EC2InstanceWrapper(
            boto3_instance=boto3_instance,
            ssh_client_docker_image=self.ssh_client_image_name,
            private_key_path=aws_settings.private_key_path,
            username=remote_docker_engine_image.ssh_username,
        )

    def start_buildkit_container(self):
        base_ec2_image = REMOTE_DOCKER_ENGINE_IMAGES[self.architecture]

        aws_settings = AWSSettings.create_from_env()
        boto3_session = aws_settings.create_boto3_session()

        self.start_ec2_instance(
            boto3_session=boto3_session,
            aws_settings=aws_settings,
            base_ec2_image=base_ec2_image,
        )

        buildkit_container_name = f"{self.name}_container"

        delete_container(
            container_name=buildkit_container_name,
            initial_cmd_args=self.ec2_instance.common_ssh_command_args
        )

        full_buildkit_builder_port = f"{BUILDX_BUILDER_PORT}/tcp"

        self.buildkit_builder_container = ContainerWrapper(
            name=buildkit_container_name,
            image=f"moby/buildkit:{BUILDKIT_VERSION}",
            rm=True,
            ports={0: full_buildkit_builder_port},
            privileged=True,
            prefix_command_args=self.ec2_instance.common_ssh_command_args,
            command_args=[
                "--addr",
                f"tcp://0.0.0.0:{BUILDX_BUILDER_PORT}",
            ]
        )

        self.buildkit_builder_container.run()

        buildkit_container_host_port = self.buildkit_builder_container.get_host_port(
            container_port=full_buildkit_builder_port
        )

        buildkit_tunneled_local_port = self.ec2_instance.open_ssh_tunnel(
            remote_port=buildkit_container_host_port,
        )

        return buildkit_tunneled_local_port

    def close(self):
        if self.buildkit_builder_container:
            self.buildkit_builder_container.remove(force=True)

        if self.ec2_instance:
            logger.info(f"Terminate EC2 instance '{self.ec2_instance.id}'")
            self.ec2_instance.terminate()
