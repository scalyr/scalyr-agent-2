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
This module contains function that responsible for building of the content of the packages.
"""

import json
import platform
import pathlib as pl
import shutil
import re
import os
import subprocess
import time
from typing import Union, List

from agent_build_refactored.tools.constants import SOURCE_ROOT, AGENT_BUILD_PATH


def recursively_delete_dirs_by_name(root_dir: Union[str, pl.Path], *dir_names: str):
    """
    Deletes any directories that are in the current working directory or any of its children whose file names
    match the specified regular expressions.

    This will recursively examine all children of the current working directory.

    If a directory is found that needs to be deleted, all of it and its children are deleted.

    @param dir_names: A variable number of strings containing regular expressions that should match the file names of
        the directories that should be deleted.
    """

    # Compile the strings into actual regular expression match objects.
    matchers = []
    for dir_name in dir_names:
        matchers.append(re.compile(dir_name))

    # Walk down the file tree, top down, allowing us to prune directories as we go.
    for root, dirs, files in os.walk(root_dir):
        # Examine all directories at this level, see if any get a match
        for dir_path in dirs:
            for matcher in matchers:
                if matcher.match(dir_path):
                    shutil.rmtree(os.path.join(root, dir_path))
                    # Also, remove it from dirs so that we don't try to walk down it.
                    dirs.remove(dir_path)
                    break


def recursively_delete_files_by_name(
    dir_path: Union[str, pl.Path], *file_names: Union[str, pl.Path]
):
    """Deletes any files that are in the current working directory or any of its children whose file names
    match the specified regular expressions.

    This will recursively examine all children of the current working directory.

    @param file_names: A variable number of strings containing regular expressions that should match the file names of
        the files that should be deleted.
    """
    # Compile the strings into actual regular expression match objects.
    matchers = []
    for file_name in file_names:
        matchers.append(re.compile(str(file_name)))

    # Walk down the current directory.
    for root, dirs, files in os.walk(dir_path.absolute()):
        # See if any of the files at this level match any of the matchers.
        for file_path in files:
            for matcher in matchers:
                if matcher.match(file_path):
                    # Delete it if it did match.
                    os.unlink(os.path.join(root, file_path))
                    break


def cat_files(file_paths, destination, convert_newlines=False):
    """Concatenates the contents of the specified files and writes it to a new file at destination.

    @param file_paths: A list of paths for the files that should be read. The concatenating will be done in the same
        order as the list.
    @param destination: The path of the file to write the contents to.
    @param convert_newlines: If True, the final file will use Windows newlines (i.e., CR LF).
    """
    with pl.Path(destination).open("w") as dest_fp:
        for file_path in file_paths:
            with pl.Path(file_path).open("r") as in_fp:
                for line in in_fp:
                    if convert_newlines:
                        line.replace("\n", "\r\n")
                    dest_fp.write(line)


def _add_certs(
    path: Union[str, pl.Path], intermediate_certs=True, copy_other_certs=True
):
    """
    Create needed certificates files in the specified path.
    """

    path = pl.Path(path)
    path.mkdir(parents=True)
    source_certs_path = SOURCE_ROOT / "certs"

    cat_files(source_certs_path.glob("*_root.pem"), path / "ca_certs.crt")

    if intermediate_certs:
        cat_files(
            source_certs_path.glob("*_intermediate.pem"),
            path / "intermediate_certs.pem",
        )
    if copy_other_certs:
        for cert_file in source_certs_path.glob("*.pem"):
            shutil.copy(cert_file, path / cert_file.name)


def add_config(
    base_config_source_path: Union[str, pl.Path],
    output_path: Union[str, pl.Path],
    additional_config_paths: List[pl.Path] = None,
):
    """
    Copy config folder from the specified path to the target path.
    :param base_config_source_path: Path to the base config directory to copy.
    :param additional_config_paths: List of paths to config directories to copy to the result config directory.
        New files are places along with files from the 'base_config_source_path' or overwrite them.
    """
    base_config_source_path = pl.Path(base_config_source_path)
    output_path = pl.Path(output_path)
    # Copy config
    shutil.copytree(base_config_source_path, output_path)

    # Copy additional config files.
    for a_config_path in additional_config_paths or []:
        # pylint: disable=unexpected-keyword-arg
        shutil.copytree(
            a_config_path,
            output_path,
            dirs_exist_ok=True,
        )
        # pylint: enable=unexpected-keyword-arg

    # Make sure config file has 640 permissions
    config_file_path = output_path / "agent.json"
    config_file_path.chmod(int("640", 8))

    # Make sure there is an agent.d directory regardless of the config directory we used.
    agent_d_path = output_path / "agent.d"
    agent_d_path.mkdir(exist_ok=True)
    # NOTE: We in intentionally set this permission bit for agent.d directory to make sure it's not
    # readable by others.
    agent_d_path.chmod(int("741", 8))

    # Also iterate through all files in the agent.d and set appropriate permissions.
    for child_path in agent_d_path.iterdir():
        if child_path.is_file():
            child_path.chmod(int("640", 8))


def get_build_info():
    """Returns a dict containing the package build info."""

    build_info = {}

    original_dir = os.getcwd()

    try:
        # We need to execute the git command in the source root.
        os.chdir(SOURCE_ROOT)
        # Add in the e-mail address of the user building it.
        try:
            packager_email = (
                subprocess.check_output("git config user.email", shell=True)
                .decode()
                .strip()
            )
        except subprocess.CalledProcessError:
            packager_email = "unknown"

        build_info["packaged_by"] = packager_email

        # Determine the last commit from the log.
        commit_id = (
            subprocess.check_output(
                "git log --summary -1 | head -n 1 | cut -d ' ' -f 2", shell=True
            )
            .decode()
            .strip()
        )

        build_info["latest_commit"] = commit_id

        # Include the branch just for safety sake.
        branch = (
            subprocess.check_output("git branch | cut -d ' ' -f 2", shell=True)
            .decode()
            .strip()
        )
        build_info["from_branch"] = branch

        # Add a timestamp.
        build_info["build_time"] = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

        return build_info
    finally:
        os.chdir(original_dir)


def get_install_info(install_type: str) -> dict:
    """
    Get dict with installation info.
    """
    return {"build_info": get_build_info(), "install_type": install_type}


def build_agent_base_files(
    output_path: pl.Path,
    install_type: str,
    version: str = None,
    frozen_binary_path: pl.Path = None,
    copy_agent_source: bool = False,
):
    """
    Create directory with agent's core files.
    :param output_path: Output path for the root of the agent's base files.
    :param install_type: String with install type of the future package.
        See 'install_info' in scalyr_agent/__scalyr__.py module.
    :param version: Version string to assign to the future package, uses version from the VERSION file if None.
    :param frozen_binary_path: Path to frozen binaries, if specified, then those binaries will be used in the
        'bin' folder. Excludes 'copy_agent_source'.
    :param copy_agent_source: If True, then agent's source code is also copied into the '<output_path>/py' directory.
        In opposite, it is expected that a frozen binaries will be placed instead of source code later.
    """
    if output_path.exists():
        shutil.rmtree(output_path)

    output_path.mkdir(parents=True)

    # Copy the monitors directory.
    monitors_path = output_path / "monitors"
    shutil.copytree(SOURCE_ROOT / "monitors", monitors_path)
    recursively_delete_files_by_name(output_path / monitors_path, "README.md")

    # Add VERSION file.
    result_version_path = output_path / "VERSION"
    if version:
        result_version_path.write_text(version)
    else:
        shutil.copy2(SOURCE_ROOT / "VERSION", output_path / "VERSION")

    # Create bin directory with executables.
    bin_path = output_path / "bin"

    if frozen_binary_path:
        shutil.copytree(frozen_binary_path / ".", bin_path)

    elif copy_agent_source:
        bin_path.mkdir()
        source_code_path = output_path / "py"

        shutil.copytree(SOURCE_ROOT / "scalyr_agent", source_code_path / "scalyr_agent")

        agent_main_executable_path = bin_path / "scalyr-agent-2"
        agent_main_executable_path.symlink_to(
            pl.Path("..", "py", "scalyr_agent", "agent_main.py")
        )

        # Copy wrapper script for removed 'scalyr-agent-2-config' executable for backward compatibility.
        shutil.copy2(
            AGENT_BUILD_PATH / "linux/scalyr-agent-2-config",
            bin_path,
        )

        # Write install_info file inside the "scalyr_agent" package.
        install_info_path = source_code_path / "scalyr_agent" / "install_info.json"

        install_info = get_install_info(install_type=install_type)
        install_info_path.write_text(json.dumps(install_info))

        # Don't include the tests directories.  Also, don't include the .idea directory created by IDE.
        recursively_delete_dirs_by_name(
            source_code_path, r"\.idea", "tests", "__pycache__"
        )
        recursively_delete_files_by_name(
            source_code_path,
            r".*\.pyc",
            r".*\.pyo",
            r".*\.pyd",
            r"all_tests\.py",
            r".*~",
        )


def build_linux_agent_files(
    output_path: pl.Path,
    install_type: str,
    version: str = None,
    frozen_binary_path: pl.Path = None,
    copy_agent_source: bool = False,
):
    """
    Extend agent core files with files that are common for all Linux based distributions.
    :param output_path: Output path for the root of the agent's base files.
    :param install_type: String with install type of the future package.
        See 'install_info' in scalyr_agent/__scalyr__.py module.
    :param version: Version string to assign to the future package, uses version from the VERSION file if None.
    :param frozen_binary_path: Path to frozen binaries, if specified, then those binaries will be used in the
        'bin' folder. Excludes 'copy_agent_source'.
    :param copy_agent_source: If True, then agent's source code is also copied into the '<output_path>/py' directory.
        In opposite, it is expected that a frozen binaries will be placed instead of source code later.
    """

    build_agent_base_files(
        output_path=output_path,
        install_type=install_type,
        version=version,
        frozen_binary_path=frozen_binary_path,
        copy_agent_source=copy_agent_source,
    )

    # Add certificates.
    certs_path = output_path / "certs"
    _add_certs(certs_path)

    # Misc extra files needed for some features.
    # This docker file is needed by the `scalyr-agent-2-config --docker-create-custom-dockerfile` command.
    # We put it in all distributions (not just the docker_tarball) in case a customer creates an image
    # using a package.
    misc_path = output_path / "misc"
    misc_path.mkdir()
    for f in ["Dockerfile.custom_agent_config", "Dockerfile.custom_k8s_config"]:
        shutil.copy2(SOURCE_ROOT / "docker" / f, misc_path / f)


def build_linux_lfs_agent_files(
    output_path: pl.Path,
    version: str = None,
    frozen_binary_path: pl.Path = None,
    copy_agent_source: bool = False,
):
    """
    Adapt agent's Linux based files for LFS based packages such DEB,RPM or for the filesystems for our docker images.
        In opposite, it is expected that a frozen binaries will be placed instead of source code later.
    :param output_path: Output path for the root of the agent's base files.
    :param version: Version string to assign to the future package, uses version from the VERSION file if None.
    :param frozen_binary_path: Path to frozen binaries, if specified, then those binaries will be used in the
        'bin' folder. Excludes 'copy_agent_source'.
    :param copy_agent_source: If True, then agent's source code is also copied into the '<output_path>/py' directory.
    """
    agent_install_root = output_path / "usr/share/scalyr-agent-2"
    build_linux_agent_files(
        output_path=agent_install_root,
        install_type="package",
        version=version,
        frozen_binary_path=frozen_binary_path,
        copy_agent_source=copy_agent_source,
    )

    pl.Path(output_path, "var/log/scalyr-agent-2").mkdir(parents=True)
    pl.Path(output_path, "var/lib/scalyr-agent-2").mkdir(parents=True)

    usr_sbin_path = output_path / "usr/sbin"
    usr_sbin_path.mkdir(parents=True)

    agent_frozen_binary_filename = "scalyr-agent-2"
    if platform.system().lower().startswith("win"):
        agent_frozen_binary_filename = f"{agent_frozen_binary_filename}.exe"

    agent_binary_symlink_path = output_path / "usr/sbin" / agent_frozen_binary_filename
    frozen_binary_symlink_target_path = pl.Path(
        "..", "share", "scalyr-agent-2", "bin", agent_frozen_binary_filename
    )
    agent_binary_symlink_path.symlink_to(frozen_binary_symlink_target_path)

    scalyr_agent_config_symlink_path = (
        output_path / "usr/sbin" / "scalyr-agent-2-config"
    )
    scalyr_agent_config_symlink_target_path = pl.Path(
        "..", "share", "scalyr-agent-2", "bin", "scalyr-agent-2-config"
    )
    scalyr_agent_config_symlink_path.symlink_to(scalyr_agent_config_symlink_target_path)
