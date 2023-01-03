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

import logging
import pathlib as pl
import subprocess
from typing import List, Dict

from agent_build_refactored.tools.constants import Architecture
from agent_build_refactored.tools.run_in_ec2.constants import EC2DistroImage

logger = logging.getLogger(__name__)

_SYSTEM_PYTHON_DISTROS = {}



# Collection of remote machine distro specifications for end to end remote tests.
DISTROS: Dict[str, Dict[str, Dict[Architecture, EC2DistroImage]]] = {
    "ubuntu2204": {
        "ec2": {
            Architecture.X86_64: EC2DistroImage(
                image_id="ami-09d56f8956ab235b3",
                image_name="Ubuntu Server 22.04 (HVM), SSD Volume Type",
                short_name="ubuntu2204",
                size_id="m1.small",
                ssh_username="ubuntu",
            ),
            Architecture.ARM64: EC2DistroImage(
                image_id="ami-0e2b332e63c56bcb5",
                image_name="Ubuntu Server 22.04 LTS (HVM), SSD Volume Type",
                short_name="ubuntu2204_ARM",
                size_id="c7g.small",
                ssh_username="ubuntu"
            )
        },
        "docker": "ubuntu:22.04",
    },
    "ubuntu2004": {
        "ec2": {
            Architecture.X86_64: EC2DistroImage(
                image_id="ami-0149b2da6ceec4bb0",
                image_name="Ubuntu Server 20.04 LTS (HVM), SSD Volume Type",
                short_name="ubuntu2004",
                size_id="m1.small",
                ssh_username="ubuntu",
            )
        },
        "docker": "ubuntu:20.04",
    },
    "ubuntu1804": {
        "ec2": {
            Architecture.X86_64: EC2DistroImage(
                image_id="ami-07ebfd5b3428b6f4d",
                image_name="Ubuntu Server 18.04 LTS (HVM), SSD Volume Type",
                short_name="ubuntu1804",
                size_id="m1.small",
                ssh_username="ubuntu",
            )
        },
        "docker": "ubuntu:18.04",
    },
    "ubuntu1604": {
        "ec2": {
            Architecture.X86_64: EC2DistroImage(
                image_id="ami-08bc77a2c7eb2b1da",
                image_name="Ubuntu Server 16.04 LTS (HVM), SSD Volume Type",
                short_name="ubuntu1604",
                size_id="m1.small",
                ssh_username="ubuntu",
            )
        },
        "docker": "ubuntu:16.04",
    },
    "ubuntu1404": {
        "ec2": {
            Architecture.X86_64: EC2DistroImage(
                image_id="ami-07957d39ebba800d5",
                image_name="Ubuntu Server 14.04 LTS (HVM)",
                short_name="ubuntu1404",
                size_id="t2.small",
                ssh_username="ubuntu",
            )
        },
        "docker": "ubuntu:14.04",
    },
    "debian11": {
        "ec2": {
            Architecture.X86_64: EC2DistroImage(
                image_id="ami-09a41e26df464c548",
                image_name="Debian 11 (HVM), SSD Volume Type",
                short_name="debian11",
                size_id="t2.small",
                ssh_username="ubuntu",
            )
        },
        "docker": "debian:11",
    },
    "debian10": {
        "ec2": {
            Architecture.X86_64: EC2DistroImage(
                image_id="ami-0b9a611a02047d3b1",
                image_name="Debian 10 Buster",
                short_name="debian10",
                size_id="t2.small",
                ssh_username="admin",
            )
        },
        "docker": "debian:10",
    },
    "centos8": {
        "ec2": {
            Architecture.X86_64: EC2DistroImage(
                image_id="ami-01ca03df4a6012157",
                image_name="CentOS 8 (x86_64) - with Updates HVM",
                short_name="centos8",
                size_id="t2.small",
                ssh_username="centos",
            )
        },
        "docker": "centos:8",
    },
    "centos7": {
        "ec2": {
            Architecture.X86_64: EC2DistroImage(
                image_id="ami-0affd4508a5d2481b",
                image_name="CentOS 7 (x86_64) - with Updates HVM",
                short_name="centos7",
                size_id="t2.small",
                ssh_username="centos",
            )
        },
        "docker": "centos:7",
    },
    "centos6": {
        "ec2": {
            Architecture.X86_64: EC2DistroImage(
                image_id="ami-03a941394ec9849de",
                image_name="CentOS 6 (x86_64) - with Updates HVM",
                short_name="centos7",
                size_id="t2.small",
                ssh_username="root",
            )
        },
        "docker": "centos:6",
    },
    "amazonlinux2": {
        "ec2": {
            Architecture.X86_64: EC2DistroImage(
                image_id="ami-09d95fab7fff3776c",
                image_name="Amazon Linux 2 AMI (HVM), SSD Volume Type",
                short_name="amazonlinux2",
                size_id="t2.small",
                ssh_username="ec2-user",
            )
        },
        "docker": "amazonlinux:2",
    },
    **{
        f"python3{ver}_deb": {"docker": f"python:3.{ver}-slim"}
        for ver in [6, 7, 8, 9, 10, 11]
    },
    **{
        f"python3{ver}_rpm": {"docker": f"registry.access.redhat.com/ubi8/python-3{ver}"}
        for ver in [6, 7, 8]
    }

}


def run_test_remotely(
    distro_name: str,
    remote_machine_type: str,
    command: List[str],
    architecture: Architecture,
    pytest_runner_path: pl.Path,
    file_mappings: Dict = None,
):
    """
    Run pytest tests in a remote machine, for example in ec2 or docker.
    :param distro_name: Name of the pre-defined distros where remote test can run.
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

    distro = DISTROS[distro_name][remote_machine_type]

    if remote_machine_type == "ec2":

        from agent_build_refactored.tools.run_in_ec2.boto3_tools import (
            create_and_deploy_ec2_instance,
            ssh_run_command,
            create_ssh_connection,
            AWSSettings,
        )

        distro_image = distro[architecture]

        file_mappings = file_mappings or {}
        file_mappings[pytest_runner_path] = "/tmp/test_runner"

        aws_settings = AWSSettings.create_from_env()
        boto3_session = aws_settings.create_boto3_session()

        instance = create_and_deploy_ec2_instance(
            boto3_session=boto3_session,
            ec2_image=distro_image,
            name_prefix=distro_image.short_name,
            aws_settings=aws_settings,
            files_to_upload=file_mappings,
        )

        final_command = ["/tmp/test_runner", "-s", *command]

        try:
            ssh = create_ssh_connection(
                instance.public_ip_address,
                username=distro_image.ssh_username,
                private_key_path=aws_settings.private_key_path,
            )

            ssh_run_command(ssh_connection=ssh, command=final_command, run_as_root=True)
        finally:
            logger.info("Terminating EC2 instance.")
            instance.terminate()
    else:
        mount_options = []

        for source, dst in file_mappings.items():
            mount_options.extend(["-v", f"{source}:{dst}"])

        subprocess.check_call(
            [
                "docker",
                "run",
                "-i",
                "-v",
                f"{pytest_runner_path}:/test_runner",
                *mount_options,
                "--platform",
                str(architecture.as_docker_platform.value),
                distro,
                "/test_runner",
                "-s",
                *command,
            ]
        )
