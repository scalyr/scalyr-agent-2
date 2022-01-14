#!/usr/bin/env python
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

"""
This is a special script that has to be executed only by GitHub Action publish job.
This script expects that all images are already pushed by GH actions with tag "_temp_release", so it can "re-tag"
them to their normal tags.
"""

import argparse
import subprocess
import sys
import pathlib as pl
import re
from typing import List

_SOURCE_ROOT = pl.Path(__file__).parent.parent.parent.absolute()

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(_SOURCE_ROOT))

from agent_build import package_builders

BUILDERS_TO_USE = [
    package_builders.DOCKER_JSON_CONTAINER_BUILDER_BUSTER,
    package_builders.DOCKER_SYSLOG_CONTAINER_BUILDER_BUSTER,
    package_builders.K8S_CONTAINER_BUILDER_BUSTER,
    package_builders.DOCKER_JSON_CONTAINER_BUILDER_ALPINE,
    package_builders.DOCKER_SYSLOG_CONTAINER_BUILDER_ALPINE,
    package_builders.K8S_CONTAINER_BUILDER_ALPINE,
]


def verify_get_tag_ang_get_image_tags(git_tag) -> List[str]:
    """
    Return set of result tags according to the name of the git tag.
    """
    production_tag_pattern = r"^v(\d+\.\d+\.\d+)$"

    m = re.match(production_tag_pattern, git_tag)

    # if given tag does not match production tag (e.g. v2.1.25), then just push
    # the image by the same, unchanged tag.
    if not m:
        return [git_tag]

    # The production tag is given, verify it the given version matches the version in the file.
    tag_version = m.group(1)

    version_file_path = _SOURCE_ROOT / "VERSION"

    current_version = version_file_path.read_text().strip()

    if tag_version != current_version:
        RuntimeError(
            f"Error. New version tag {git_tag} does not match "
            f"current version {current_version}.",
        )

    return [tag_version, "latest"]


def main(
    git_ref_name: str,
    git_ref_type: str,
    git_commit_sha: str,
    registry: str = None,
    registry_user: str = None
):

    # If Github actions ref type if "tag" then check if the tag is a "production" tag or not.
    if git_ref_type == "tag":
        tags = verify_get_tag_ang_get_image_tags(git_ref_name)
        print(f"Push using tags {tags}")
    else:
        # Just push using commit SHA as tag.
        print(f"Push using commit SHA: {git_commit_sha}")
        tags = [git_commit_sha]

    for builder in BUILDERS_TO_USE:
        for image_name in builder.RESULT_IMAGE_NAMES:
            full_image_name = image_name

            if registry_user:
                full_image_name = f"{registry_user}/{full_image_name}"

            if registry:
                full_image_name = f"{registry}/{full_image_name}"

            tag_options = []

            for tag in tags:
                tag_options.append("-t")

                # Add additional suffix for  alpine images.
                if builder.name.endswith("alpine"):
                    final_tag = f"{tag}-alpine"
                else:
                    final_tag = tag

                tag_options.append(f"{full_image_name}:{final_tag}")

            # NOTE: We expect that this script runs right after the GitHub action job that has pushed
            # all needed images with a special tag "_temp_release", so we just can use the
            # "buildx imagetools" command to "retag" it.

            # Also add distribution related suffix to the temporary tag.
            temp_release_tag = "_temp_release"
            if builder.name.endswith("alpine"):
                temp_release_tag = f"{temp_release_tag}-alpine"
            else:
                temp_release_tag = f"{temp_release_tag}-buster"

            subprocess.check_call([
                "docker",
                "buildx",
                "imagetools",
                "create",
                f"{full_image_name}:{temp_release_tag}",
                *tag_options
            ])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument("--git-ref-name", required=False)
    parser.add_argument("--git-ref-type")
    parser.add_argument("--git-commit-sha", required=False)
    parser.add_argument("--registry", required=False)
    parser.add_argument("--user", required=False)

    args = parser.parse_args()
    main(
        git_ref_name=args.git_ref_name,
        git_ref_type=args.git_ref_type,
        git_commit_sha=args.git_commit_sha,
        registry=args.registry,
        registry_user=args.user,
    )