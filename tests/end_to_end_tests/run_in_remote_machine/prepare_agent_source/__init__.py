import pathlib as pl

from agent_build_refactored.tools.constants import SOURCE_ROOT, CpuArch
from agent_build_refactored.tools.toolset_image import build_toolset_image, build_toolset_image_oci_layout
from agent_build_refactored.tools.docker.buildx.build import LocalDirectoryBuildOutput, buildx_build

_PARENT_DIR = pl.Path(__file__).parent

AGENT_SOURCE_TARBALL_FILENAME = "source.tar.gz"


def prepare_agent_source(
    output_dir: pl.Path,
):

    toolset_oci_layout_path = build_toolset_image_oci_layout()

    buildx_build(
        dockerfile_path=_PARENT_DIR / "Dockerfile",
        context_path=SOURCE_ROOT,
        architecture=CpuArch.x86_64,
        build_args={
            "AGENT_SOURCE_TARBALL_FILENAME": AGENT_SOURCE_TARBALL_FILENAME,
        },
        build_contexts={
            "toolset": f"oci-layout://{toolset_oci_layout_path}"
        },
        output=LocalDirectoryBuildOutput(
            dest=output_dir
        ),
    )