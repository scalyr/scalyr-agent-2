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


import pathlib as pl

from agent_build_refactored.utils.constants import SOURCE_ROOT, CpuArch
from agent_build_refactored.utils.toolset_image import (
    build_toolset_image_oci_layout,
)
from agent_build_refactored.utils.docker.buildx.build import (
    LocalDirectoryBuildOutput,
    buildx_build,
)

_PARENT_DIR = pl.Path(__file__).parent

AGENT_SOURCE_TARBALL_FILENAME = "source.tar.gz"


def prepare_agent_source_tarball(
    output_dir: pl.Path,
):

    toolset_oci_layout_path = build_toolset_image_oci_layout()

    buildx_build(
        dockerfile_path=_PARENT_DIR / "Dockerfile",
        context_path=SOURCE_ROOT,
        architectures=[CpuArch.x86_64],
        build_args={
            "AGENT_SOURCE_TARBALL_FILENAME": AGENT_SOURCE_TARBALL_FILENAME,
        },
        build_contexts={"toolset": f"oci-layout://{toolset_oci_layout_path}"},
        output=LocalDirectoryBuildOutput(dest=output_dir),
    )
