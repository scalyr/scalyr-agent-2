# Copyright 2014-2021 Scalyr Inc.
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


import os
import pathlib as pl
import re
import shutil

from typing import Union

from agent_build import common


def cat_files(file_paths, destination, convert_newlines=False):
    """Concatenates the contents of the specified files and writes it to a new file at destination.

    @param file_paths: A list of paths for the files that should be read. The concatenating will be done in the same
        order as the list.
    @param destination: The path of the file to write the contents to.
    @param convert_newlines: If True, the final file will use Windows newlines (i.e., CR LF).
    """
    dest_fp = open(destination, "w")
    for file_path in file_paths:
        in_fp = open(file_path, "r")
        for line in in_fp:
            if convert_newlines:
                line.replace("\n", "\r\n")
            dest_fp.write(line)
        in_fp.close()
    dest_fp.close()


def add_certs(path: Union[str, pl.Path]):
    path = pl.Path(path)
    source_certs_path = common.SOURCE_ROOT / "certs"

    cat_files(source_certs_path.glob("*_root.pem"), path / "ca_certs.crt")
    cat_files(
        source_certs_path.glob("*_intermediate.pem"),
        path / "intermediate_certs.pem",
    )
    for cert_file in source_certs_path.glob("*.pem"):
        shutil.copy(cert_file, path / cert_file.name)


def recursively_delete_files_by_name(
        dir_path: Union[str, pl.Path],
        *file_names: Union[str, pl.Path]
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
            remove_it = False
            for matcher in matchers:
                if matcher.match(file_path):
                    remove_it = True
            # Delete it if it did match.
            if remove_it:
                os.unlink(os.path.join(root, file_path))


def build_base_files(
        build_info: common.PackageBuildInfo,
        package_type: str,
        output_path: Union[str, pl.Path]
):
    """
    Build the basic structure for a package..

        This creates a directory and then populates it with the basic structure required by most of the packages.

        It copies the certs, the configuration directories, etc.

        In the end, the structure will look like:
            certs/ca_certs.pem         -- The trusted SSL CA root list.
            bin/scalyr-agent-2         -- Symlink to the agent_main.py file to run the agent.
            bin/scalyr-agent-2-config  -- Symlink to config_main.py to run the configuration tool
            build_info                 -- A file containing the commit id of the latest commit included in this package,
                                          the time it was built, and other information.

    :param build_info: The basic information about the build.
    :param output_path: The output path where the result files are stored.
    """
    output_path = pl.Path(output_path)

    if output_path.exists():
        shutil.rmtree(output_path)

    output_path.mkdir(parents=True)

    # Write build_info file.
    build_info_path = output_path / "build_info"
    build_info_path.write_text(build_info.build_summary)

    # Copy the monitors directory.
    monitors_path = output_path / "monitors"
    shutil.copytree(common.SOURCE_ROOT / "monitors", monitors_path)
    recursively_delete_files_by_name(output_path / monitors_path, "README.md")

    # Create the trusted CA root list.
    certs_path = output_path / "certs"
    certs_path.mkdir()
    add_certs(certs_path)

    # Misc extra files needed for some features.
    # This docker file is needed by the `scalyr-agent-2-config --docker-create-custom-dockerfile` command.
    # We put it in all distributions (not just the docker_tarball) in case a customer creates an image
    # using a package.
    misc_path = output_path / "misc"
    misc_path.mkdir()
    for f in [
        "Dockerfile.custom_agent_config", "Dockerfile.custom_k8s_config"
    ]:
        shutil.copy2(common.SOURCE_ROOT / "docker" / f, misc_path / f)

    # Add VERSION file.
    shutil.copy2(common.SOURCE_ROOT / "VERSION", output_path / "VERSION")

    # # Write a special file to specify the type of the package.
    # package_type_file = output_path / "install_type"
    # package_type_file.write_text(package_type)


