import pathlib as pl
import subprocess
from typing import List, Dict, Type, Union

from agent_build_refactored.tools.constants import Architecture, DockerPlatform
from agent_build_refactored.managed_packages.managed_packages_builders import ManagedPackagesBuilder
from tests.end_to_end_tests.run_in_remote_machine.ec2 import EC2DistroImage, run_test_in_ec2_instance, AwsSettings

DISTROS: Dict[str, Dict[Architecture, EC2DistroImage]] = {
    "ubuntu2204": {
        "ec2": {
            Architecture.X86_64: EC2DistroImage(
                image_id="ami-09d56f8956ab235b3",
                image_name="Ubuntu Server 22.04 (HVM), SSD Volume Type",
                size_id="m1.small",
                ssh_username="ubuntu",
            )
        },
    },
    "ubuntu2004": {
        "ec2": {
            Architecture.X86_64: EC2DistroImage(
                image_id="ami-0149b2da6ceec4bb0 ",
                image_name="Ubuntu Server 20.04 LTS (HVM), SSD Volume Type",
                size_id="m1.small",
                ssh_username="ubuntu"
            )
        },
    },
    "ubuntu1804": {
        "ec2": {
            Architecture.X86_64: EC2DistroImage(
                image_id="ami-07ebfd5b3428b6f4d",
                image_name="Ubuntu Server 18.04 LTS (HVM), SSD Volume Type",
                size_id="m1.small",
                ssh_username="ubuntu"
            )
        },
    },
    "ubuntu1604": {
        "ec2": {
        Architecture.X86_64: EC2DistroImage(
                image_id="ami-08bc77a2c7eb2b1da",
                image_name="Ubuntu Server 16.04 LTS (HVM), SSD Volume Type",
                size_id="m1.small",
                ssh_username="ubuntu",
            )
        },
    },
    "ubuntu1404": {
        "ec2": {
            Architecture.X86_64: EC2DistroImage(
                    image_id="ami-07957d39ebba800d5",
                    image_name="Ubuntu Server 14.04 LTS (HVM)",
                    size_id="t2.small",
                    ssh_username="ubuntu",
            )
        }
    },
    "debian11": {
        "ec2": {
            Architecture.X86_64: EC2DistroImage(
                image_id="ami-09a41e26df464c548",
                image_name="Debian 11 (HVM), SSD Volume Type",
                size_id="t2.small",
                ssh_username="ubuntu",
            )
        }
    },
    "debian10": {
        "ec2": {
            Architecture.X86_64: EC2DistroImage(
                image_id="ami-0b9a611a02047d3b1",
                image_name="Debian 10 Buster",
                size_id="t2.small",
                ssh_username="admin",
            )
        }
    },
    "centos8": {
        "ec2": {
            Architecture.X86_64: EC2DistroImage(
                image_id="ami-01ca03df4a6012157",
                image_name="CentOS 8 (x86_64) - with Updates HVM",
                size_id="t2.small",
                ssh_username="centos",
            )
        },
    },
    "centos7": {
        "ec2": {
            Architecture.X86_64: EC2DistroImage(
                image_id="ami-0affd4508a5d2481b",
                image_name="CentOS 7 (x86_64) - with Updates HVM",
                size_id="t2.small",
                ssh_username="centos",
            )
        }
    },
    "centos6": {
        "ec2": {
            Architecture.X86_64: EC2DistroImage(
                image_id="ami-03a941394ec9849de",
                image_name="CentOS 6 (x86_64) - with Updates HVM",
                size_id="t2.small",
                ssh_username="root",
            )
        },
    },
    "amazonlinux2": {
        "ec2": {
            Architecture.X86_64: EC2DistroImage(
                image_id="ami-09d95fab7fff3776c",
                image_name="Amazon Linux 2 AMI (HVM), SSD Volume Type",
                size_id="t2.small",
                ssh_username="ec2-user",
            )
        },
    },
}

def run_test_remotely(
        remote_distro_name: str,
        command: List[str],
        architecture: Architecture,
        pytest_runner_path: pl.Path,
        test_options,
        file_mappings: Dict = None,
):
    remote_machine_type, distro_name = remote_distro_name.split(":")

    file_mappings = file_mappings or {}

    distro = DISTROS[distro_name][remote_machine_type]

    if remote_machine_type == "ec2":

        def _validate_option(name: str):
            dest = name.replace("--", "").replace("-", "_")
            value = getattr(test_options, dest)
            if value is None:
                raise ValueError(f"Option '{name}' has to be provided with distro type 'ec2'.")

        _validate_option("--aws-access-key")
        _validate_option("--aws-secret-key")
        _validate_option("--aws-private-key-path")
        _validate_option("--aws-private-key-name")
        _validate_option("--aws-region")
        _validate_option("--aws-security-group")
        _validate_option("--aws-security-groups-prefix-list-id")

        distro_image = distro[architecture]

        run_test_in_ec2_instance(
            ec2_image=distro_image,
            test_runner_path=pytest_runner_path,
            command=command,
            file_mappings=file_mappings,
            node_name_suffix="arthur-test",
            access_key=test_options.aws_access_key,
            secret_key=test_options.aws_secret_key,
            private_key_path=test_options.aws_private_key_path,
            private_key_name=test_options.aws_private_key_name,
            region=test_options.aws_region,
            security_group=test_options.aws_security_group,
            security_groups_prefix_list_id=test_options.aws_security_groups_prefix_list_id
        )
    else:
        mount_options = []

        for source, dst in file_mappings.items():
            mount_options.extend([
                "-v",
                f"{source}:{dst}"
            ])

        subprocess.check_call([
            "docker",
            "run",
            "-i",
            "-v",
            f"{pytest_runner_path}:/test_runner",
            *mount_options,
            "-e",
            "TEST_RUNS_REMOTELY=1",
            "--platform",
            str(architecture.as_docker_platform),
            distro,
            "/test_runner",
            "-s",
            *command
        ])
