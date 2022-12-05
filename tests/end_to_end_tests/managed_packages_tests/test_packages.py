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

import pathlib as pl
import shlex
import subprocess
import logging
import textwrap
from typing import List

import pytest

from agent_build_refactored.tools.constants import SOURCE_ROOT
from agent_build_refactored.managed_packages.managed_packages_builders import (
    PYTHON_PACKAGE_NAME,
    AGENT_LIBS_PACKAGE_NAME,
    AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME,
)

logger = logging.getLogger(__name__)

"""
This test module preforms end to end testing of the Linux agent package and its dependency packages.
Since we perform testing for multiple distributions, those tests are mainly run inside another remote machines,
such as ec2 instance or docker container. If needed, it can be run locally, but you have to be aware that those tests
are changing system state and must be aware of risks.
"""


def _verify_package_subdirectories(
    package_path: pl.Path,
    package_type: str,
    package_name: str,
    output_dir: pl.Path,
    expected_folders: List[str],
):
    """
    Verify structure if the agent's dependency packages.
    First,  we have to ensure that all package files are located inside special subdirectory and nothing has leaked
    outside.
    :param package_type: Type of the package, e.g. deb, rpm.
    :param package_name: Name of the package.
    :param output_dir: Directory where to extract a package.
    :param expected_folders: List of paths that are expected to be in this package.
    """

    package_root = output_dir / package_name
    package_root.mkdir()

    if package_type == "deb":
        subprocess.check_call(["dpkg-deb", "-x", str(package_path), str(package_root)])
    elif package_type == "rpm":
        escaped_package_path = shlex.quote(str(package_path))
        command = f"rpm2cpio {escaped_package_path} | cpio -idm"
        subprocess.check_call(
            command,
            shell=True,
            cwd=package_root,
            env={"LD_LIBRARY_PATH": "/lib64"},
        )
    else:
        raise Exception(f"Unknown package type {package_type}.")

    remaining_paths = set(package_root.glob("**/*"))

    for expected in expected_folders:
        expected_path = package_root / expected
        for path in list(remaining_paths):
            if str(path).startswith(str(expected_path)) or str(path) in str(
                expected_path
            ):
                remaining_paths.remove(path)

    assert (
        len(remaining_paths) == 0
    ), "Something remains outside if the expected package structure."


def test_dependency_packages(
    package_builder,
    tmp_path,
    package_source_type,
    packages_repo_dir,
    python_package_path,
    agent_libs_package_path,
):
    if package_source_type not in ["dir", "repo-tarball"]:
        pytest.skip("Only run when packages dir provided.")

    package_type = package_builder.PACKAGE_TYPE

    _verify_package_subdirectories(
        package_path=python_package_path,
        package_type=package_builder.PACKAGE_TYPE,
        package_name=PYTHON_PACKAGE_NAME,
        output_dir=tmp_path,
        expected_folders=[
            f"usr/lib/{AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME}/",
            f"usr/share/{AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME}/",
            # Depending on its type, a package also may install its own "metadata", so we have to take it into
            # account too.
            f"usr/share/doc/{PYTHON_PACKAGE_NAME}/"
            if package_type == "deb"
            else "usr/lib/.build-id/",
        ],
    )

    # Verify structure of the agent_libs package and make sure there's no any file outside it.
    _verify_package_subdirectories(
        package_path=agent_libs_package_path,
        package_type=package_builder.PACKAGE_TYPE,
        package_name=AGENT_LIBS_PACKAGE_NAME,
        output_dir=tmp_path,
        expected_folders=[
            f"usr/lib/{AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME}/",
            f"usr/share/{AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME}/",
            # Depending on its type, a package also may install its own "metadata", so we have to take it into
            # account too.
            f"usr/share/doc/{AGENT_LIBS_PACKAGE_NAME}/"
            if package_type == "deb"
            else "usr/lib/.build-id/",
        ],
    )


def test_packages(
    package_builder,
    repo_url,
    repo_public_key,
    distro_name,
):
    _add_repo(
        package_type=package_builder.PACKAGE_TYPE,
        repo_url=repo_url,
        repo_public_key=repo_public_key,
        distro_name=distro_name,
    )
    _install_package(
        package_type=package_builder.PACKAGE_TYPE,
        package_name=AGENT_LIBS_PACKAGE_NAME,
    )

    logger.info(
        "Execute simple sanity test script for the python interpreter and its libraries."
    )
    subprocess.check_call(
        [
            f"/usr/lib/{AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME}/bin/python3",
            "tests/end_to_end_tests/managed_packages_tests/verify_python_interpreter.py",
        ],
        env={
            # It's important to override the 'LD_LIBRARY_PATH' to be sure that libraries paths from the test runner
            # frozen binary are not leaked to a script's process.
            "LD_LIBRARY_PATH": "",
            "PYTHONPATH": str(SOURCE_ROOT),
        },
    )

    # TODO: Add actual agent package testing here.


def _add_repo(package_type: str, repo_url, repo_public_key: str, distro_name: str):
    """
    Add repo with tested packages.
    :param package_type: Type of the package, e.g. deb, rpm.
    :param repo_url: URL of a repo.
    :param repo_public_key: Content of repo's public key.
    :param distro_name: name of a tested distribution.
    """

    if package_type == "deb":
        # Add repo's public key
        repo_key_path = pl.Path("/etc/apt/trusted.gpg.d/test.asc")
        repo_key_path.write_text(repo_public_key)

        # Add repo for ubuntu 14 and 16 by using deprecated apt-key command.
        if distro_name in ["ubuntu1404", "ubuntu1604"]:
            subprocess.check_call(
                ["apt-key", "add", str(repo_key_path)], env={"LD_LIBRARY_PATH": "/lib"}
            )

        # Add repo's config file.
        repo_file_path = pl.Path("/etc/apt/sources.list.d/test.list")
        repo_file_path.write_text(f"deb {repo_url} trusty main")
        _call_apt(["update"])
    elif package_type == "rpm":
        # Add repo's public key
        repo_key_path = pl.Path("/tmp/public_key")
        repo_key_path.write_text(repo_public_key)

        # Add repo's config file.
        repo_file_path = pl.Path("/etc/yum.repos.d/test.repo")
        repo_config = textwrap.dedent(
            f"""
            [test_repo]
            name=test_repo
            baseurl={repo_url}
            enabled=1
            gpgcheck=0
            repo_gpgcheck=1
            gpgkey=file://{repo_key_path}
            """
        )
        repo_file_path.write_text(repo_config.format(repo_url=repo_url))

        if distro_name == "centos8":
            # For centos 8 we replace repo urls for vault.
            for repo_name in ["BaseOS", "AppStream"]:
                repo_file = pl.Path(f"/etc/yum.repos.d/CentOS-Linux-{repo_name}.repo")
                content = repo_file.read_text()
                content = content.replace("mirror.centos.org", "vault.centos.org")
                content = content.replace("#baseurl", "baseurl")
                content = content.replace("mirrorlist=", "#mirrorlist=")
                repo_file.write_text(content)

        elif distro_name == "centos6":
            # for centos 6, we remove repo file for disabled repo, so it could use vault repo.
            pl.Path("/etc/yum.repos.d/CentOS-Base.repo").unlink()


def _install_package(
    package_type: str,
    package_name: str,
):
    """
    Installs package from repo.
    """
    if package_type == "deb":
        _call_apt(["install", "-y", package_name])
    elif package_type == "rpm":
        _call_yum(["install", "-y", package_name])
    else:
        raise Exception(f"Unknown package type: {package_type}")


def _call_apt(command: List[str]):
    """Run apt command"""
    subprocess.check_call(
        ["apt", *command],
        # Since test may run in "frozen" pytest executable, add missing variables.
        env={"LD_LIBRARY_PATH": "/lib", "PATH": "/usr/sbin:/sbin:/usr/bin:/bin"},
    )


def _call_yum(command: List[str]):
    """Run yum command"""
    subprocess.check_call(
        ["yum", *command],
        # Since test may run in "frozen" pytest executable, add missing variables.
        env={"LD_LIBRARY_PATH": "/lib64"},
    )
