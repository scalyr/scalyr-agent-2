# Copyright 2014-2023 Scalyr Inc.
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
This module allows to build a "toolset" images that contains various tools and program that are widely used
across the whole codebase.
"""

import pathlib as pl
import shutil

from agent_build_refactored.utils.constants import SOURCE_ROOT, CpuArch, OCI_LAYOUTS_DIR
from agent_build_refactored.utils.docker.buildx.build import DockerImageBuildOutput, buildx_build, OCITarballBuildOutput, BuildOutput

_PARENT_DIR = pl.Path(__file__).parent

_NAME = "agent_build_toolset"

_OCI_LAYOUT_PATH = OCI_LAYOUTS_DIR / _NAME


_already_built_image = False
_already_built_oci_layout = False


def _build(
    output: BuildOutput,
):
    buildx_build(
        dockerfile_path=_PARENT_DIR / "Dockerfile",
        context_path=SOURCE_ROOT,
        architecture=CpuArch.x86_64,
        output=output,
        cache_name=_NAME,
    )


def build_toolset_image():
    """Build toolset images and import it directly to docker engine."""
    global _already_built_image

    if _already_built_image:
        return _NAME

    _build(
        output=DockerImageBuildOutput(
            name=_NAME
        )
    )
    _already_built_image = True
    return _NAME


def build_toolset_image_oci_layout():
    """
    Build toolset image and import it as OCI image tarball
    """
    global _already_built_oci_layout

    if _already_built_oci_layout:
        return _OCI_LAYOUT_PATH

    if _OCI_LAYOUT_PATH.exists():
        shutil.rmtree(_OCI_LAYOUT_PATH)

    _OCI_LAYOUT_PATH.mkdir(parents=True)

    _build(
        output=OCITarballBuildOutput(
            dest=_OCI_LAYOUT_PATH,
        ),
    )
    _already_built_oci_layout = True
    return _OCI_LAYOUT_PATH