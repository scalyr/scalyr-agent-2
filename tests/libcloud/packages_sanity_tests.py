# Copyright 2014-2020 Scalyr Inc.
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
Script which runs basic package fresh install or upgrade sanity tests on a fresh EC2 instance.

It depends on the following environment variables:

- ACCESS_KEY - AWS access key.
- SECRET_KEY - AWS secret key.
- REGION - AWS region to use.

- KEY_NAME - Name of the AWS key pair to use.
- PRIVATE_KEY_PATH - Path to the private key file used to authenticate. NOTE: The key shouldn't be
  password protected and needs to match the private key from the key pair used.
- SECURITY_GROUPS - Comma delimited list of security groups names to place the node into.

- SCALYR_API_KEY - Scalyr API key to use.

NOTE 1: You are recommended to use 2048 bit RSA key because CentOS 6 AMI we use doesn't support new
key types or RSA keys of size 4096 bits.

ssh-keygen -t rsa -b 2048 ...

NOTE 2: You can't run upgrade test on CentOS because it doesn't include "python" package our
scalyr-agent-2 2.0.x package depends on.

Usage:

1. Fresh install tests

python3 tests/libcloud/package_sanity_tests.py --distro=ubuntu1604 --type=install --to-version=2.1.1
python3 tests/libcloud/package_sanity_tests.py --distro=ubuntu1804 --type=install --to-version=2.1.1
python3 tests/libcloud/package_sanity_tests.py --distro=ubuntu1804 --type=install --to-version=2.1.1 --python-package=python3
python3 tests/libcloud/package_sanity_tests.py --distro=centos8 --type=install --to-version=2.1.1
python3 tests/libcloud/package_sanity_tests.py --distro=centos8 --type=install --to-version=2.1.1 --python-package=python3

2. Upgrade tests

python3 tests/libcloud/packages_sanity_tests.py --distro=ubuntu1804 --type=upgrade --from-version=2.0.59 --to-version=2.1.1
python3 tests/libcloud/packages_sanity_tests.py --distro=centos7 --type=upgrade --from-version=2.0.59 --to-version=2.1.1
"""

from __future__ import absolute_import
from __future__ import print_function

if False:
    from typing import List

import os
import sys
import time

import random
import argparse
from io import open

from libcloud.compute.types import Provider
from libcloud.compute.types import StorageVolumeState
from libcloud.compute.base import NodeImage
from libcloud.compute.base import NodeSize
from libcloud.compute.base import DeploymentError
from libcloud.compute.providers import get_driver
from libcloud.compute.deployment import ScriptDeployment

from scalyr_agent import compat

BASE_DIR = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts/")

EC2_DISTRO_DETAILS_MAP = {
    "ubuntu1404": {
        "image_id": "ami-07957d39ebba800d5",
        "image_name": "Ubuntu Server 14.04 LTS (HVM)",
        "size_id": "t2.micro",
        "ssh_username": "ubuntu",
        "default_python_package_name": "python",
    },
    "ubuntu1604": {
        "image_id": "ami-08bc77a2c7eb2b1da",
        "image_name": "Ubuntu Server 16.04 LTS (HVM), SSD Volume Type",
        "size_id": "t1.micro",
        "ssh_username": "ubuntu",
        "default_python_package_name": "python",
    },
    "ubuntu1804": {
        "image_id": "ami-07ebfd5b3428b6f4d",
        "image_name": "Ubuntu Server 18.04 LTS (HVM), SSD Volume Type",
        "size_id": "t1.micro",
        "ssh_username": "ubuntu",
        "default_python_package_name": "python",
    },
    # NOTE: Currently doesn't work with 4096 RSA keys due to paramiko issues
    # Need to use 2048 bit key to test this one
    "centos6": {
        "image_id": "ami-03a941394ec9849de",
        "image_name": "CentOS 6 (x86_64) - with Updates HVM",
        "size_id": "t2.micro",
        "ssh_username": "root",
        "default_python_package_name": "python",
    },
    "centos7": {
        "image_id": "ami-0affd4508a5d2481b",
        "image_name": "CentOS 7 (x86_64) - with Updates HVM",
        "size_id": "t2.micro",
        "ssh_username": "centos",
        "default_python_package_name": "python",
    },
    "centos8": {
        "image_id": "ami-0e7ad70170b787201",
        "image_name": "CentOS 8 (x86_64) - with Updates HVM",
        "size_id": "t2.micro",
        "ssh_username": "centos",
        "default_python_package_name": "python2",
    },
}

ACCESS_KEY = compat.os_getenv_unicode("ACCESS_KEY", "")
SECRET_KEY = compat.os_getenv_unicode("SECRET_KEY", "")
REGION = compat.os_getenv_unicode("REGION", "us-east-1")

KEY_NAME = compat.os_getenv_unicode("KEY_NAME", "")
PRIVATE_KEY_PATH = compat.os_getenv_unicode("PRIVATE_KEY_PATH", "~")
PRIVATE_KEY_PATH = os.path.expanduser(PRIVATE_KEY_PATH)

SECURITY_GROUPS_STR = compat.os_getenv_unicode(
    "SECURITY_GROUPS", "allow-ssh"
)  # sg-02efe05c115d41622
SECURITY_GROUPS = SECURITY_GROUPS_STR.split(",")  # type: List[str]

SCALYR_API_KEY = compat.os_getenv_unicode("SCALYR_API_KEY", "")


def main(
    distro, test_type, from_version, to_version, python_package, destroy_node=False
):
    # type: (str, str, str, str, str, bool) -> None
    distro_details = EC2_DISTRO_DETAILS_MAP[distro]

    if test_type == "install":
        script_filename = "fresh_install_%s.sh"
    else:
        script_filename = "upgrade_install_%s.sh"

    script_filename = script_filename % (
        "deb" if distro.startswith("ubuntu") else "rpm"
    )
    script_file_path = os.path.join(SCRIPTS_DIR, script_filename)

    with open(script_file_path, "r") as fp:
        script_content = fp.read()

    format_values = distro_details.copy()
    format_values["scalyr_api_key"] = SCALYR_API_KEY
    format_values["python_package"] = (
        python_package or distro_details["default_python_package_name"]
    )
    format_values["package_from_version"] = from_version
    format_values["package_to_version"] = to_version
    script_content = script_content.format(**format_values)

    cls = get_driver(Provider.EC2)
    driver = cls(ACCESS_KEY, SECRET_KEY, region=REGION)

    size = NodeSize(
        distro_details["size_id"], distro_details["size_id"], 0, 0, 0, 0, driver,
    )
    image = NodeImage(
        distro_details["image_id"], distro_details["image_name"], driver, None
    )
    name = "%s-automated-agent-%s-test-%s" % (
        distro,
        test_type,
        random.randint(0, 1000),
    )
    step = ScriptDeployment(script_content)

    try:
        node = driver.deploy_node(
            name=name,
            image=image,
            size=size,
            ssh_key=PRIVATE_KEY_PATH,
            ex_keyname=KEY_NAME,
            ex_security_groups=SECURITY_GROUPS,
            ssh_username=distro_details["ssh_username"],
            ssh_alternate_usernames=["root", "ec2-user"],
            ssh_timeout=10,
            timeout=120,
            deploy=step,
            at_exit_func=destroy_node_and_cleanup,
        )
    except DeploymentError as e:
        print("Deployment failed: %s" % (str(e)))
        node = e.node
        step.exit_status = 1

    success = step.exit_status == 0

    # We don't destroy node if destroy_node is False (e.g. to aid with troubleshooting on failure
    # and similar)
    if node and destroy_node:
        destroy_node_and_cleanup(driver=driver, node=node)

    if success:
        print("Script successfully completed.")
    else:
        print("Script failed.")

    print(("stdout: %s" % (step.stdout)))
    print(("stderr: %s" % (step.stderr)))
    print(("exit_code: %s" % (step.exit_status)))
    print(("succeeded: %s" % (str(success))))

    if not success:
        sys.exit(1)


def destroy_node_and_cleanup(driver, node):
    """
    Destroy the provided node and cleanup any left over EBS volumes.
    """
    volumes = driver.list_volumes(node=node)

    print(('Destroying node "%s"...' % (node.name)))
    node.destroy()

    assert len(volumes) <= 1
    print("Cleaning up any left-over EBS volumes for this node...")

    # Give it some time for the volume to become detached from the node
    time.sleep(5)

    for volume in volumes:
        # Additional safety checks
        if volume.extra.get("instance_id", None) != node.id:
            continue

        if volume.size != 8:
            # All the volumes we use are 8 GB EBS volumes
            continue

        if volume.state != StorageVolumeState.AVAILABLE:
            continue

        driver.destroy_volume(volume=volume)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=("Run basic agent installer sanity tests on EC2 instance")
    )
    parser.add_argument(
        "--distro",
        help=("Distribution to use."),
        required=True,
        choices=list(EC2_DISTRO_DETAILS_MAP.keys()),
    )
    parser.add_argument(
        "--type",
        help=("Test type (install / upgrade)."),
        required=True,
        choices=["install", "upgrade"],
    )
    parser.add_argument(
        "--from-version",
        help=("Package version to use for upgrade tests."),
        default=None,
        required=False,
    )
    parser.add_argument(
        "--to-version",
        help=("Package version to use for fresh install and upgrade tests."),
        required=True,
    )
    parser.add_argument(
        "--python-package",
        help=(
            "Name of the python package to use. If not provided, it defaults to distro default."
        ),
        required=False,
    )
    parser.add_argument(
        "--no-destroy-node",
        help=("True to not destroy the node at the end."),
        action="store_true",
        default=False,
    )
    args = parser.parse_args(sys.argv[1:])

    if args.distro == "centos8" and args.type == "upgrade":
        raise ValueError(
            "upgrade test is not supported on CentOS 8, because scalyr-agent-2 "
            '2.0.x package depends on "python" package which is not available on '
            "CentOS 8."
        )

    main(
        distro=args.distro,
        test_type=args.type,
        from_version=args.from_version,
        to_version=args.to_version,
        python_package=args.python_package,
        destroy_node=not args.no_destroy_node,
    )
