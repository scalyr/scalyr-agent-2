import atexit
import dataclasses
import logging
import pathlib as pl
import subprocess
from typing import Any, List, Optional, Dict


from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.tools.aws.constants import EC2DistroImage

from agent_build_refactored.tools.docker.common import delete_container, ContainerWrapper
from agent_build_refactored.tools.aws.boto3_tools import AWSSettings

from agent_build_refactored.tools.aws.ec2 import EC2InstanceWrapper

logger = logging.getLogger(__name__)


BUILDKIT_VERSION = "v0.11.6"
BUILDX_BUILDER_PORT = 1234


REMOTE_DOCKER_ENGINE_INSTANCE_SIZES = {
    CpuArch.x86_64: "c6i.2xlarge",
    CpuArch.AARCH64: "c7g.2xlarge",
    CpuArch.ARMV7: "c7g.2xlarge",
}


class EC2BackedRemoteBuildxBuilderWrapper:
    def __init__(
        self,
        name: str,
        architecture: CpuArch,
        ssh_client_image_name: str,
    ):
        self.name = name

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
            architecture=self.architecture,
            boto3_session=boto3_session,
            aws_settings=aws_settings,

        )

        remote_docker_engine_image = EC2DistroImage(
            image_id=remote_docker_engine_ami_image.id,
            image_name=remote_docker_engine_ami_image.name,
            short_name=base_ec2_image.short_name,
            size_id=REMOTE_DOCKER_ENGINE_INSTANCE_SIZES[self.architecture],
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

        try:
            subprocess.run(
                [
                    "docker",
                    "buildx",
                    "rm",
                    self.name,
                ],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            logger.exception(f"Can not remove docker buildx builder '{self.name}'. Stderr: {e.stderr.decode()}")
            raise

        if self.buildkit_builder_container:
            self.buildkit_builder_container.remove(force=True)

        if self.ec2_instance:
            logger.info(f"Terminate EC2 instance '{self.ec2_instance.id}'")
            self.ec2_instance.terminate()



_existing_remote_builders: Dict[CpuArch, EC2BackedRemoteBuildxBuilderWrapper] = {}


def get_remote_builder(
    architecture: CpuArch,
):
    global _existing_remote_builders

    builder = _existing_remote_builders.get(architecture)

    if builder:
        return builder

    from agent_build_refactored.tools.toolset_image import build_toolset_image

    toolset_image_name = build_toolset_image()

    builder = EC2BackedRemoteBuildxBuilderWrapper(
        name=f"agent_build_ec2_backed_remote_builder_{architecture.value}",
        architecture=architecture,
        ssh_client_image_name=toolset_image_name
    )

    builder.initialize()

    _existing_remote_builders[architecture] = builder
    return builder


def _cleanup():
    global _existing_remote_builders

    for builder in _existing_remote_builders.values():
        builder.close()


atexit.register(_cleanup)