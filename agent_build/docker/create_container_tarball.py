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
This script is used by the 'Dockerfile' file to produce a tarball with all files that are used in the
Agent docker images.
"""

import argparse
import pathlib as pl
import tarfile
import os
import sys

_SOURCE_ROOT = pl.Path(__file__).parent.parent.parent

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(_SOURCE_ROOT))

import agent_build.tools.common
from agent_build import prepare_agent_filesystem

if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-path",
        required=True,
        help="Output path for the container tarball."
    )

    parser.add_argument(
        "--config",
        help="Name of the config directory to use in the build."
    )

    args = parser.parse_args()

    output_path = pl.Path(args.output_path)

    if not output_path.exists():
        output_path.mkdir(parents=True)

    agent_filesystem_root_path = output_path / "root"

    config_path = agent_build.tools.common.SOURCE_ROOT / "docker" / args.config

    # Create common LFS agent filesystem.
    prepare_agent_filesystem.build_linux_lfs_agent_files(
        copy_agent_source=True,
        output_path=agent_filesystem_root_path,
        config_path=config_path,
    )

    # Need to create some docker specific directories.
    pl.Path(agent_filesystem_root_path / "var/log/scalyr-agent-2/containers").mkdir()

    # Put everything into a tarball.
    container_tarball_path = output_path / "scalyr-agent.tar.gz"

    # Do a manual walk over the contents of root so that we can use `addfile` to add the tarfile... which allows
    # us to reset the owner/group to root.  This might not be that portable to Windows, but for now, Docker is
    # mainly Posix.
    with tarfile.open(container_tarball_path, "w:gz") as container_tar:

        for root, dirs, files in os.walk(agent_filesystem_root_path):
            to_copy = []
            for name in dirs:
                to_copy.append(os.path.join(root, name))
            for name in files:
                to_copy.append(os.path.join(root, name))

            for x in to_copy:
                file_entry = container_tar.gettarinfo(
                    x, arcname=str(pl.Path(x).relative_to(agent_filesystem_root_path))
                )
                file_entry.uname = "root"
                file_entry.gname = "root"
                file_entry.uid = 0
                file_entry.gid = 0

                if file_entry.isreg():
                    with open(x, "rb") as fp:
                        container_tar.addfile(file_entry, fp)
                else:
                    container_tar.addfile(file_entry)