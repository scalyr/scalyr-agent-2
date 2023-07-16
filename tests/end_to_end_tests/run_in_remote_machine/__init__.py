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

"""
This module defines logic that allows to run end-to-end tests inside remote machines such as ec2 instance or docker
container.
"""
import dataclasses
import logging
import pathlib as pl
import subprocess
from typing import List, Dict, Union

# from agent_build_refactored.managed_packages.build_dependencies_versions import (
#     EMBEDDED_OPENSSL_VERSION_NUMBER,
# )
from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.managed_packages.managed_packages_builders import EMBEDDED_OPENSSL_VERSION_NUMBER
from agent_build_refactored.tools.aws.ami import StockAMIImage


logger = logging.getLogger(__name__)


@dataclasses.dataclass
class TargetDistro:
    name: str
    docker_image: str
    ec2_images: Dict[CpuArch, StockAMIImage]
    ec2_instance_size_id: str
    # Expected version (in int representation) of the OpenSSL library that has to be picked by the agent.
    # This is ineger representation of the OpenSSL version. More info https://docs.python.org/3/library/ssl.html#ssl.OPENSSL_VERSION_NUMBER,
    #   https://www.openssl.org/docs/man3.0/man3/OPENSSL_VERSION_NUMBER.html
    expected_openssl_version_number: Union[int, List[int]]


# Collection of remote machine distro specifications for end to end remote tests.

_EC2_INSTANCE_SIZE_X86_64 = "t2.small"

_DISTROS_LIST = [
        TargetDistro(
            name="ubuntu2204",
            ec2_images={
                CpuArch.x86_64: StockAMIImage(
                    image_id="ami-09d56f8956ab235b3",
                    name="Ubuntu Server 22.04 (HVM), SSD Volume Type",
                    short_name="ubuntu2204",
                    ssh_username="ubuntu",
                )
            },
            ec2_instance_size_id=_EC2_INSTANCE_SIZE_X86_64,
            docker_image="ubuntu:22.04",
            expected_openssl_version_number=0x30000020,
        ),
        TargetDistro(
            name="ubuntu2004",
            ec2_images={
                CpuArch.x86_64: StockAMIImage(
                    image_id="ami-0149b2da6ceec4bb0",
                    name="Ubuntu Server 20.04 LTS (HVM), SSD Volume Type",
                    short_name="ubuntu2004",
                    ssh_username="ubuntu",
                )
            },
            ec2_instance_size_id=_EC2_INSTANCE_SIZE_X86_64,
            docker_image="ubuntu:20.04",
            expected_openssl_version_number=0x1010106F,
        ),
        TargetDistro(
            name="ubuntu1804",
            ec2_images={
                CpuArch.x86_64: StockAMIImage(
                    image_id="ami-07ebfd5b3428b6f4d",
                    name="Ubuntu Server 18.04 LTS (HVM), SSD Volume Type",
                    short_name="ubuntu1804",
                    ssh_username="ubuntu",
                )
            },
            ec2_instance_size_id=_EC2_INSTANCE_SIZE_X86_64,
            docker_image="ubuntu:18.04",
            expected_openssl_version_number=0x1010100F,
        ),
        TargetDistro(
            name="ubuntu1604",
            ec2_images={
                CpuArch.x86_64: StockAMIImage(
                    image_id="ami-08bc77a2c7eb2b1da",
                    name="Ubuntu Server 16.04 LTS (HVM), SSD Volume Type",
                    short_name="ubuntu1604",
                    ssh_username="ubuntu",
                )
            },
            ec2_instance_size_id=_EC2_INSTANCE_SIZE_X86_64,
            docker_image="ubuntu:16.04",
            expected_openssl_version_number=EMBEDDED_OPENSSL_VERSION_NUMBER,
        ),
        TargetDistro(
            name="ubuntu1404",
            ec2_images={
                CpuArch.x86_64: StockAMIImage(
                    image_id="ami-07957d39ebba800d5",
                    name="Ubuntu Server 14.04 LTS (HVM)",
                    short_name="ubuntu1404",
                    ssh_username="ubuntu",
                )
            },
            ec2_instance_size_id=_EC2_INSTANCE_SIZE_X86_64,
            docker_image="ubuntu:14.04",
            expected_openssl_version_number=EMBEDDED_OPENSSL_VERSION_NUMBER,
        ),
        TargetDistro(
            name="debian11",
            ec2_images={
                CpuArch.x86_64: StockAMIImage(
                    image_id="ami-09a41e26df464c548",
                    name="Debian 11 (HVM), SSD Volume Type",
                    short_name="debian11",
                    ssh_username="admin",
                )
            },
            ec2_instance_size_id=_EC2_INSTANCE_SIZE_X86_64,
            docker_image="debian:11",
            expected_openssl_version_number=0x101010EF,
        ),
        TargetDistro(
            name="debian10",
            ec2_images={
                CpuArch.x86_64: StockAMIImage(
                    image_id="ami-0b9a611a02047d3b1",
                    name="Debian 10 Buster",
                    short_name="debian10",
                    ssh_username="admin",
                )
            },
            ec2_instance_size_id=_EC2_INSTANCE_SIZE_X86_64,
            docker_image="debian:10",
            expected_openssl_version_number=0x101010EF,
        ),
        TargetDistro(
            name="centos8",
            ec2_images={
                CpuArch.x86_64: StockAMIImage(
                    image_id="ami-01ca03df4a6012157",
                    name="CentOS 8 (x86_64) - with Updates HVM",
                    short_name="centos8",
                    ssh_username="centos",
                )
            },
            ec2_instance_size_id=_EC2_INSTANCE_SIZE_X86_64,
            docker_image="centos:8",
            # EC2 and docker openssl versions are different, so we need to track them all.
            expected_openssl_version_number=[0x101010BF, 0x1010107F],
        ),
        TargetDistro(
            name="centos7",
            ec2_images={
                CpuArch.x86_64: StockAMIImage(
                    image_id="ami-0affd4508a5d2481b",
                    name="CentOS 7 (x86_64) - with Updates HVM",
                    short_name="centos7",
                    ssh_username="centos",
                )
            },
            ec2_instance_size_id=_EC2_INSTANCE_SIZE_X86_64,
            docker_image="centos:7",
            expected_openssl_version_number=EMBEDDED_OPENSSL_VERSION_NUMBER,
        ),
        TargetDistro(
            name="centos6",
            ec2_images={
                CpuArch.x86_64: StockAMIImage(
                    image_id="ami-03a941394ec9849de",
                    name="CentOS 6 (x86_64) - with Updates HVM",
                    short_name="centos7",
                    ssh_username="root",
                )
            },
            ec2_instance_size_id=_EC2_INSTANCE_SIZE_X86_64,
            docker_image="centos:6",
            expected_openssl_version_number=EMBEDDED_OPENSSL_VERSION_NUMBER,
        ),
        TargetDistro(
            name="amazonlinux2",
            ec2_images={
                CpuArch.x86_64: StockAMIImage(
                    image_id="ami-09d95fab7fff3776c",
                    name="Amazon Linux 2 AMI (HVM), SSD Volume Type",
                    short_name="amazonlinux2",
                    ssh_username="ec2-user",
                )
            },
            ec2_instance_size_id=_EC2_INSTANCE_SIZE_X86_64,
            docker_image="amazonlinux:2",
            expected_openssl_version_number=EMBEDDED_OPENSSL_VERSION_NUMBER,
        ),
    ]


DISTROS = {distro.name: distro for distro in _DISTROS_LIST}



def run_test_remotely(
    target_distro: TargetDistro,
    remote_machine_type: str,
    command: List[str],
    architecture: CpuArch,
    pytest_runner_path: pl.Path,
    source_tarball_path: pl.Path,
    file_mappings: Dict = None,
):
    """
    Run pytest tests in a remote machine, for example in ec2 or docker.
    :param target_distro: Pre-defined distro where remote test can run.
    :param remote_machine_type: Type of the remote machine. Can be ec2 or docker.
    :param command: pytest command to execute in the remote machine.
    :param architecture: Architecture of the remote machine.
    :param pytest_runner_path: Path to the  pytest executable. For now, it has to be
        a pytest runner that was "frozen" into a single binary by PyInstaller.
        This executable is convenient because we don't have to have any pre-installations
        in remote machines.
    :param test_options: Current test run command line options.
    :param file_mappings: Dict where key is a file that has to be presented in the remote machine,
        and value is the path in the remote machine.
    """

    file_mappings = file_mappings or {}
    file_mappings[pytest_runner_path] = "/tmp/test_runner"
    file_mappings[source_tarball_path] = "/tmp/source.tar.gz"

    common_command_args = [
        "/tmp/test_runner",
        "/tmp/source.tar.gz",
        "--set-env=IN_REMOTE_MACHINE=1",
        "-s",
        *command
    ]

    if remote_machine_type == "ec2":

        distro_image = target_distro.ec2_images[architecture]

        instance = distro_image.deploy_ec2_instance(
            size_id=target_distro.ec2_instance_size_id,
            files_to_upload=file_mappings,
        )

        try:
            subprocess.run(
                [
                    *instance.common_ssh_command_args,
                    "sudo",
                    *common_command_args,
                ],
                check=True,
            )
            # instance.run_ssh_command(
            #     command=final_command,
            #     run_as_root=True,
            # )
        finally:
            logger.info("Terminating EC2 instance.")
            instance.terminate()
    else:
        mount_options = []

        for source, dst in file_mappings.items():
            mount_options.extend(["-v", f"{source}:{dst}"])

        subprocess.run(
            [
                "docker",
                "run",
                "-i",
                "-v",
                f"{pytest_runner_path}:/test_runner",
                *mount_options,
                "--platform",
                architecture.as_docker_platform(),
                target_distro.docker_image,
                *common_command_args,
            ],
            check=True
        )
