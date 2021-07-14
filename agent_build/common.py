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


import dataclasses
import io
import subprocess
import time
import pathlib as pl
import hashlib

from typing import List, Union

SOURCE_ROOT = pl.Path(__file__).parent.parent


@dataclasses.dataclass
class PackageBuildInfo:
    build_summary: str
    variant: str = None
    no_versioned_file_name: bool = False

    """
        This data class contains all common information about the build.
        
        :param package_type: The package type.
        :param package_version: The agent version.
        :param description: The description of the package.
        :param variant: If not None, will add the specified string into the iteration identifier for the package. This
            allows for different packages to be built for the same type and same version.
    """


def get_build_info():
    """Returns a string containing the build info."""

    build_info_buffer = io.StringIO()

    # We need to execute the git command in the source root.
    # Add in the e-mail address of the user building it.
    try:
        packager_email = subprocess.check_output(
            "git config user.email", shell=True, cwd=str(SOURCE_ROOT)
        ).decode().strip()
    except subprocess.CalledProcessError:
        packager_email = "unknown"

    print("Packaged by: %s" % packager_email.strip(), file=build_info_buffer)

    # Determine the last commit from the log.
    commit_id = (
        subprocess.check_output(
            "git log --summary -1 | head -n 1 | cut -d ' ' -f 2",
            shell=True,
            cwd=SOURCE_ROOT,
        )
            .decode()
            .strip()
    )

    print("Latest commit: %s" % commit_id.strip(), file=build_info_buffer)

    # Include the branch just for safety sake.
    branch = (
        subprocess.check_output(
            "git branch | cut -d ' ' -f 2", shell=True, cwd=SOURCE_ROOT
        )
            .decode()
            .strip()
    )
    print("From branch: %s" % branch.strip(), file=build_info_buffer)

    # Add a timestamp.
    print(
        "Build time: %s" % str(time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())),
        file=build_info_buffer,
    )

    return build_info_buffer.getvalue()


def get_files_sha256_checksum(files: List[Union[str, pl.Path]], sha256=None):
    # Calculate the sha256 for each file's content, filename and permissions.
    sha256 = sha256 or hashlib.sha256()
    for file_path in files:
        file_path = pl.Path(file_path)
        sha256.update(str(file_path).encode())
        sha256.update(str(file_path.stat().st_mode).encode())
        sha256.update(file_path.read_bytes())

    return sha256

