#!/usr/bin/env python
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
Script which runs basic package fresh install or upgrade sanity tests on a fresh short lived
EC2 instance.

It depends on the following environment variables being set:

- ACCESS_KEY - AWS access key.
- SECRET_KEY - AWS secret key.
- REGION - AWS region to use.

- KEY_NAME - Name of the AWS key pair to use.
- PRIVATE_KEY_PATH - Path to the private key file used to authenticate. NOTE: The key shouldn't be
  password protected and needs to match the private key from the key pair used.
- SECURITY_GROUPS - Comma delimited list of security groups names to place the node into.

- SCALYR_API_KEY - Scalyr API key to use.

- LIBCLOUD_DEBUG=libcloud.log - Optionally set this variable to write Libcloud debug log into
  libcloud.log file.

  Keep in mind that you should never enable this on Circle CI since it will leak API keys into the
  debug log.

NOTE 1: You are recommended to use 2048 bit RSA key because CentOS 6 AMI we use doesn't support new
key types or RSA keys of size 4096 bits.

ssh-keygen -t rsa -b 2048 ...

NOTE 2: You can't run upgrade test on CentOS because it doesn't include "python" package our
scalyr-agent-2 2.0.x package depends on.

Usage:

1. Fresh install tests

Installation from stable apt repo:

python3 package_sanity_tests.py --distro=ubuntu1604 --type=install --to-version=2.1.1
python3 package_sanity_tests.py --distro=ubuntu1804 --type=install --to-version=2.1.1 --python-package=python3
python3 package_sanity_tests.py --distro=centos8 --type=install --to-version=2.1.1

Installation from package URL:

python3 package_sanity_tests.py --distro=ubuntu1404 --type=install --to-version=https://28747-23852161-gh.circle-artifacts.com/0/~/artifacts/test_build_deb_package/scalyr-agent.deb

2. Upgrade tests

Installation and upgrade from stable apt repo:

python3 packages_sanity_tests.py --distro=ubuntu1804 --type=upgrade --from-version=2.0.59 --to-version=2.1.1
python3 packages_sanity_tests.py --distro=centos7 --type=upgrade --from-version=2.0.59 --to-version=2.1.1

Installation and upgrade from package URL:
python3 package_sanity_tests.py --distro=ubuntu1404 --type=install --from-version=https://28747-23852161-gh.circle-artifacts.com/0/~/artifacts/test_build_deb_package/scalyr-agent.deb --to-version=https://28747-23852161-gh.circle-artifacts.com/0/~/artifacts/test_build_deb_package/scalyr-agent.deb

NOTE: You can't mix version strings and package URLs. You need to use one or the other, but not
combination of both.
"""

from __future__ import absolute_import
from __future__ import print_function

if False:  # NOSONAR
    from typing import List
    from typing import Optional
    from typing import Dict

import os
import sys
import time
import re
import tempfile
import shutil

import random
import argparse
from io import open

from jinja2 import FileSystemLoader
from jinja2 import Environment
import requests

from libcloud.compute.types import Provider
from libcloud.compute.base import NodeDriver
from libcloud.compute.base import NodeImage
from libcloud.compute.base import NodeSize
from libcloud.compute.base import StorageVolume
from libcloud.compute.base import DeploymentError
from libcloud.compute.providers import get_driver
from libcloud.compute.deployment import (
    ScriptDeployment,
    FileDeployment,
    MultiStepDeployment,
)

from scalyr_agent import compat

from tests.ami.utils import get_env_throw_if_not_set

BASE_DIR = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts/")

# Directory which contains config files used by the tests which are uploaded to the server
MOCK_CONFIGS_DIRECTORY = os.path.join(BASE_DIR, "configs/")

# Directory which contains additional files which are used by the test and are uploaded to the
# server
TEST_FILES_DIRECTORY = os.path.join(BASE_DIR, "files/")

# TODO: Revert back to micro image if there are still failures with small
EC2_DISTRO_DETAILS_MAP = {
    # Debian based distros
    "ubuntu1404": {
        "image_id": "ami-07957d39ebba800d5",
        "image_name": "Ubuntu Server 14.04 LTS (HVM)",
        "size_id": "t2.small",
        "ssh_username": "ubuntu",
        "default_python_package_name": "python",
    },
    "ubuntu1604": {
        "image_id": "ami-08bc77a2c7eb2b1da",
        "image_name": "Ubuntu Server 16.04 LTS (HVM), SSD Volume Type",
        "size_id": "m1.small",
        "ssh_username": "ubuntu",
        "default_python_package_name": "python",
    },
    "ubuntu1804": {
        "image_id": "ami-07ebfd5b3428b6f4d",
        "image_name": "Ubuntu Server 18.04 LTS (HVM), SSD Volume Type",
        "size_id": "m1.small",
        "ssh_username": "ubuntu",
        "default_python_package_name": "python",
    },
    "debian1003": {
        "image_id": "ami-0b9a611a02047d3b1",
        "image_name": "Debian 10 Buster",
        "size_id": "t2.small",
        "ssh_username": "admin",
        "default_python_package_name": "python",
    },
    # RHEL based distros
    # NOTE: Currently doesn't work with 4096 RSA keys due to paramiko issues
    # Need to use 2048 bit key to test this one
    "centos6": {
        "image_id": "ami-03a941394ec9849de",
        "image_name": "CentOS 6 (x86_64) - with Updates HVM",
        "size_id": "t2.small",
        "ssh_username": "root",
        "default_python_package_name": "python",
    },
    "centos7": {
        "image_id": "ami-0affd4508a5d2481b",
        "image_name": "CentOS 7 (x86_64) - with Updates HVM",
        "size_id": "t2.small",
        "ssh_username": "centos",
        "default_python_package_name": "python",
    },
    "centos8": {
        "image_id": "ami-01ca03df4a6012157",
        "image_name": "CentOS 8 (x86_64) - with Updates HVM",
        "size_id": "t2.small",
        "ssh_username": "centos",
        "default_python_package_name": "python2",
    },
    "amazonlinux2": {
        "image_id": "ami-09d95fab7fff3776c",
        "image_name": "Amazon Linux 2 AMI (HVM), SSD Volume Type",
        "size_id": "t2.small",
        "ssh_username": "ec2-user",
        "default_python_package_name": "python",
    },
    # Windows
    "WindowsServer2019": {
        "image_id": "ami-0f9790554e2b6bc8d",
        "image_name": "WindowsServer2019-SSH",
        "size_id": "t2.small",
        "ssh_username": "Administrator",
        "default_python_package_name": "python2",
    },
    "WindowsServer2016": {
        "image_id": "ami-06e455febb7d693eb",
        "image_name": "WindowsServer2016-SSH",
        "size_id": "t2.small",
        "ssh_username": "Administrator",
        "default_python_package_name": "python2",
    },
    "WindowsServer2012": {
        "image_id": "ami-033513be5c11f0e67",
        "image_name": "WindowsServer2012R2-SSH",
        "size_id": "t2.small",
        "ssh_username": "Administrator",
        "default_python_package_name": "python2",
    },
}

DEFAULT_INSTALLER_SCRIPT_URL = (
    "https://www.scalyr.com/scalyr-repo/stable/latest/install-scalyr-agent-2.sh"
)

ACCESS_KEY = get_env_throw_if_not_set("ACCESS_KEY")
SECRET_KEY = get_env_throw_if_not_set("SECRET_KEY")
REGION = get_env_throw_if_not_set("REGION", "us-east-1")

KEY_NAME = get_env_throw_if_not_set("KEY_NAME")
PRIVATE_KEY_PATH = get_env_throw_if_not_set("PRIVATE_KEY_PATH")
PRIVATE_KEY_PATH = os.path.expanduser(PRIVATE_KEY_PATH)

SECURITY_GROUPS_STR = get_env_throw_if_not_set(
    "SECURITY_GROUPS", "circleci-remote-access"
)  # sg-075bf2191cf04c821
SECURITY_GROUPS = SECURITY_GROUPS_STR.split(",")  # type: List[str]

SCALYR_API_KEY = get_env_throw_if_not_set("SCALYR_API_KEY")

VERBOSE = compat.os_environ_unicode.get("VERBOSE", "false").lower() == "true"

# All the instances created by this script will use this string in the name.
INSTANCE_NAME_STRING = "-automated-agent-tests-"
assert "-tests-" in INSTANCE_NAME_STRING


def _get_source_type(version_string):
    # type: (str) -> Optional[str]
    """
    Get agent installation package source type according to data in the version string.
    """
    if not version_string:
        return None

    if "http://" in version_string or "https://" in version_string:
        return "url"
    elif os.path.exists(version_string) and os.path.isfile(version_string):
        return "file"
    elif re.match(r"\d+\.\d+\.\d+", version_string) or version_string == "current":
        return "install_script"
    else:
        raise ValueError(
            'Invalid value "%s" for version_string. If it\'s a path to a file, make'
            "sure the file exists and if it's a URL, ensure URL exists."
            % (version_string)
        )


def _create_file_deployment_step(file_path, remote_file_name):
    # type: (str, str) -> FileDeployment
    """
    Create Libcloud file deployment step object.

    """
    file_name = os.path.basename(file_path)
    extension = os.path.splitext(file_name)[1]

    target_path = "./{0}{1}".format(remote_file_name, extension)

    step = FileDeployment(file_path, target_path)

    return step


def _create_config_file_deployment_step(file_path):
    # type: (str) -> FileDeployment
    """
    Create a FileDeployment class instance for a step which uploads a config file to the remote
    server.

    This function works by copying source config file to a temporary location, adding in Scalyr
    API key and uploading this file to a remote server.
    """
    temp_dir = tempfile.mkdtemp(prefix="ami-tests-configs")

    file_name = os.path.basename(file_path)
    temp_file_path = os.path.join(temp_dir, file_name)

    # Copy file to a temporary directory
    shutil.copyfile(file_path, temp_file_path)

    # Add in Scalyr API key
    with open(temp_file_path, "r") as fp:
        content = fp.read()

    content = content.replace("REPLACE_THIS", SCALYR_API_KEY)

    with open(temp_file_path, "w") as fp:
        fp.write("// AUTO GENERATED BY AMI TESTS SCRIPT\n")
        fp.write(content)

    target_path = "./{0}".format(file_name)
    step = FileDeployment(temp_file_path, target_path)

    return step


def _verify_url_exists(url, use_head=False):
    # (str, bool) -> bool
    """
    Verify that the provided URL exists (aka doesn't return 404).
    """
    try:
        if use_head:
            resp = requests.head(url)
        else:
            resp = requests.get(url)
    except requests.exceptions.ConnectionError:
        return False

    return resp.status_code in [200, 302]


def main(
    distro,
    test_type,
    from_version,
    to_version,
    python_package,
    installer_script_url,
    additional_packages=None,
    destroy_node=False,
    verbose=False,
):
    # type: (str, str, str, str, str, str, str, bool, bool) -> None

    # deployment objects for package files will be stored here.
    file_upload_steps = []

    # We always upload all the mock test configs from tests/ami/configs/ directory to a remote
    # server.
    # Those configs are used during various checks and tests. Uploading the configs is much less
    # messy compared to manipulating the configs using sed on the server.
    file_names = os.listdir(MOCK_CONFIGS_DIRECTORY)
    for file_name in file_names:
        config_file_path = os.path.join(MOCK_CONFIGS_DIRECTORY, file_name)
        file_upload_step = _create_config_file_deployment_step(config_file_path)
        file_upload_steps.append(file_upload_step)

    # Upload auxiliary files from tests/ami/files/
    file_names = os.listdir(TEST_FILES_DIRECTORY)
    for file_name in file_names:
        file_path = os.path.join(TEST_FILES_DIRECTORY, file_name)
        file_upload_step = _create_file_deployment_step(file_path, "ca_certs")
        file_upload_steps.append(file_upload_step)

    if test_type == "install":
        install_package_source = to_version
    else:
        # install package is specified in from-version in case of upgrade
        install_package_source = from_version

    # prepare data for install_package
    install_package_source_type = _get_source_type(install_package_source)

    if install_package_source_type == "file":
        # create install package file deployment object.
        file_upload_steps.append(
            _create_file_deployment_step(install_package_source, "install_package")
        )

    install_package_info = {
        "type": install_package_source_type,
        "source": install_package_source,
    }

    upgrade_package_info = None

    # prepare data for upgrade_package if it is specified.
    if test_type == "upgrade":
        upgrade_package_source = to_version
        upgrade_package_source_type = _get_source_type(upgrade_package_source)

        if upgrade_package_source_type == "file":
            # create install package file deployment object.
            file_upload_steps.append(
                _create_file_deployment_step(to_version, "upgrade_package")
            )

        upgrade_package_info = {
            "type": upgrade_package_source_type,
            "source": upgrade_package_source,
        }

    distro_details = EC2_DISTRO_DETAILS_MAP[distro]

    if distro.lower().startswith("windows"):
        package_type = "windows"
        script_extension = "ps1"
    else:
        package_type = (
            "deb"
            if distro.startswith("ubuntu") or distro.startswith("debian")
            else "rpm"
        )
        script_extension = "sh"

    script_filename = "test_%s.%s.j2" % (package_type, script_extension)
    script_file_path = os.path.join(SCRIPTS_DIR, script_filename)

    with open(script_file_path, "r") as fp:
        script_content = fp.read()

    cat_logs_script_file_path = os.path.join(
        SCRIPTS_DIR, "cat_logs.%s" % (script_extension)
    )

    with open(cat_logs_script_file_path, "r") as fp:
        cat_logs_script_content = fp.read()

    installer_script_info = {
        "source": installer_script_url or DEFAULT_INSTALLER_SCRIPT_URL
    }
    if os.path.exists(installer_script_url):
        installer_script_info["type"] = "file"
        file_upload_steps.append(
            _create_file_deployment_step(installer_script_url, "install-scalyr-agent-2")
        )
    else:
        if not _verify_url_exists(installer_script_url):
            raise ValueError(
                'Failed to retrieve installer script from "%s". Ensure that the URL is correct.'
                % (installer_script_url)
            )
        installer_script_info["type"] = "url"

    rendered_template = render_script_template(
        script_template=script_content,
        distro_name=distro,
        distro_details=distro_details,
        python_package=python_package,
        test_type=test_type,
        install_package=install_package_info,
        upgrade_package=upgrade_package_info,
        installer_script_url=installer_script_info,
        additional_packages=additional_packages,
        verbose=verbose,
    )

    # TODO: Lower those timeouts when upstream yum related issues or similar start to stabilize.
    # All AMI tests should take less than 5 minutes, but in the last days (dec 1, 2020), they
    # started to take 10 minutes with multiple timeouts.
    if "windows" in distro.lower():
        deploy_step_timeout = 440  # 320
        deploy_overall_timeout = 460  # 320
        cat_step_timeout = 10
        max_tries = 3
    else:
        deploy_step_timeout = 320  # 260
        deploy_overall_timeout = 340  # 280
        max_tries = 3
        cat_step_timeout = 5

    remote_script_name = "deploy.{0}".format(script_extension)
    test_package_step = ScriptDeployment(
        rendered_template, name=remote_script_name, timeout=deploy_step_timeout
    )

    if file_upload_steps:
        # Package files must be uploaded to the instance directly.
        file_upload_steps.append(test_package_step)  # type: ignore
        deployment = MultiStepDeployment(add=file_upload_steps)  # type: ignore
    else:
        deployment = MultiStepDeployment(add=test_package_step)  # type: ignore

    # Add a step which always cats agent.log file at the end. This helps us troubleshoot failures.
    if "windows" not in distro.lower():
        # NOTE: We don't add it on Windows since it tends to time out often
        cat_logs_step = ScriptDeployment(
            cat_logs_script_content, timeout=cat_step_timeout
        )
        deployment.add(cat_logs_step)
    else:
        cat_logs_step = None  # type: ignore

    driver = get_libcloud_driver()

    size = NodeSize(
        distro_details["size_id"],
        distro_details["size_id"],
        0,
        0,
        0,
        0,
        driver,
    )
    image = NodeImage(
        distro_details["image_id"], distro_details["image_name"], driver, None
    )

    circle_branch_name = compat.os_environ_unicode.get("CIRCLE_BRANCH", "unknown")
    circle_branch_name = circle_branch_name.replace("/", "_").replace("-", "_")
    circle_build_num = compat.os_environ_unicode.get(
        "CIRCLE_BUILD_NUM", random.randint(0, 1000)
    )

    name = "%s-automated-agent-tests-%s-branch-%s-build-%s" % (
        distro,
        test_type,
        circle_branch_name,
        circle_build_num,
    )

    print("Starting node provisioning and tests...")

    start_time = int(time.time())

    kwargs = {}
    if destroy_node:
        kwargs["at_exit_func"] = destroy_node_and_cleanup

    try:
        node = driver.deploy_node(
            name=name,
            image=image,
            size=size,
            ssh_key=PRIVATE_KEY_PATH,
            ex_keyname=KEY_NAME,
            ex_security_groups=SECURITY_GROUPS,
            ssh_username=distro_details["ssh_username"],
            ssh_timeout=20,
            max_tries=max_tries,
            wait_period=15,
            timeout=deploy_overall_timeout,
            deploy=deployment,
            **kwargs
        )
    except DeploymentError as e:
        print("Deployment failed: %s" % (str(e)))
        node = e.node
        success = False
        test_package_step.exit_status = 1
        stdout = getattr(e.original_error, "stdout", None)
        stderr = getattr(e.original_error, "stderr", None)
    else:
        success = test_package_step.exit_status == 0
        stdout = test_package_step.stdout
        stderr = test_package_step.stderr

        if cat_logs_step and cat_logs_step.stdout:
            stdout += "\n" + cat_logs_step.stdout

        if cat_logs_step and cat_logs_step.stderr:
            stdout += "\n" + cat_logs_step.stderr

    duration = int(time.time()) - start_time

    if success:
        print("Script successfully completed.")
    else:
        print("Script failed.")

    print(("stdout: %s" % (stdout)))
    print(("stderr: %s" % (stderr)))
    print(("exit_code: %s" % (test_package_step.exit_status)))
    print(("succeeded: %s" % (str(success))))
    print(("duration: %s seconds" % (duration)))

    # We don't destroy node if destroy_node is False (e.g. to aid with troubleshooting on failure
    # and similar)
    if node and destroy_node:
        destroy_node_and_cleanup(driver=driver, node=node)

    if not success:
        sys.exit(1)


def render_script_template(
    script_template,
    distro_name,
    distro_details,
    python_package,
    test_type,
    install_package=None,
    upgrade_package=None,
    installer_script_url=None,
    additional_packages=None,
    verbose=False,
):
    # type: (str, str, dict, str, str, Optional[Dict], Optional[Dict], Optional[Dict], Optional[str], bool) -> str
    """
    Render the provided script template with common context.
    """
    # from_version = from_version or ""
    # to_version = to_version or ""
    template_context = distro_details.copy()
    template_context["distro_name"] = distro_name

    template_context["test_type"] = test_type

    template_context["installer_script_info"] = (
        installer_script_url or DEFAULT_INSTALLER_SCRIPT_URL
    )
    template_context["scalyr_api_key"] = SCALYR_API_KEY
    template_context["python_package"] = (
        python_package or distro_details["default_python_package_name"]
    )

    template_context["install_package"] = install_package
    template_context["upgrade_package"] = upgrade_package
    template_context["additional_packages"] = additional_packages

    template_context["verbose"] = verbose

    env = Environment(
        loader=FileSystemLoader(SCRIPTS_DIR), extensions=["jinja2.ext.with_"]
    )
    template = env.from_string(script_template)
    rendered_template = template.render(**template_context)
    return rendered_template


def destroy_node_and_cleanup(driver, node):
    """
    Destroy the provided node and cleanup any left over EBS volumes.
    """
    volumes = driver.list_volumes(node=node)

    assert (
        INSTANCE_NAME_STRING in node.name
    ), "Refusing to delete node without %s in the name" % (INSTANCE_NAME_STRING)

    print("")
    print(('Destroying node "%s"...' % (node.name)))
    node.destroy()

    assert len(volumes) <= 1
    print("Cleaning up any left-over EBS volumes for this node...")

    # Give it some time for the volume to become detached from the node
    time.sleep(10)

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
    # type: (NodeDriver, StorageVolume, int, int) -> bool
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


def get_libcloud_driver():
    """
    Return Libcloud driver instance.
    """
    cls = get_driver(Provider.EC2)
    driver = cls(ACCESS_KEY, SECRET_KEY, region=REGION)
    return driver


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
        help=("Package version or URL to the package to use for upgrade tests."),
        default="current",
        required=False,
    )
    parser.add_argument(
        "--to-version",
        help=(
            "Package version or URL to the package to use for fresh install and upgrade tests."
        ),
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
        "--additional-packages",
        help=("Optional string of additional system level packages to install."),
        required=False,
    )

    parser.add_argument(
        "--installer-script-url",
        help=("URL to the installer script to use."),
        default=DEFAULT_INSTALLER_SCRIPT_URL,
        required=False,
    )
    parser.add_argument(
        "--verbose",
        help=(
            "True to enable verbose mode where every executed shell command is logged."
        ),
        action="store_true",
        default=VERBOSE,
    )
    parser.add_argument(
        "--no-destroy-node",
        help=("True to not destroy the node at the end."),
        action="store_true",
        default=False,
    )
    args = parser.parse_args(sys.argv[1:])

    if args.type == "install" and not args.to_version:
        raise ValueError("--to-version needs to be provided for install test")

    if args.type == "upgrade" and (not args.from_version or not args.to_version):
        raise ValueError(
            "--from-version and to --to-version needs to be provided for upgrade test"
        )

    if args.type == "upgrade" and (
        args.from_version == "current" and args.to_version == "current"
    ):
        raise ValueError(
            "--from-version and --to-version options "
            'can not have the same "current" value.'
        )

    if _get_source_type(args.from_version) == "url" and not _verify_url_exists(
        args.from_version, True
    ):
        raise ValueError(
            'Failed to retrieve package from "%s". Ensure that the URL is correct.'
            % (args.from_version)
        )

    if _get_source_type(args.to_version) == "url" and not _verify_url_exists(
        args.to_version, True
    ):
        raise ValueError(
            'Failed to retrieve package from "%s". Ensure that the URL is correct.'
            % (args.to_version)
        )

    main(
        distro=args.distro,
        test_type=args.type,
        from_version=args.from_version,
        to_version=args.to_version,
        python_package=args.python_package,
        installer_script_url=args.installer_script_url,
        additional_packages=args.additional_packages,
        destroy_node=not args.no_destroy_node,
        verbose=args.verbose,
    )
