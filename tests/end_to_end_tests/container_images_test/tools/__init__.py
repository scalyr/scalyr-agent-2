import pathlib as pl
from typing import List

from agent_build_refactored.tools.constants import CpuArch, REQUIREMENTS_DEV_COVERAGE
from agent_build_refactored.tools.docker.buildx.build import buildx_build, LocalDirectoryBuildOutput

_PARENT_DIR = pl.Path(__file__).parent


def build_image_test_dependencies(
        architectures: List[CpuArch],
        prod_image_name: str,
        output_dir: pl.Path
):
    buildx_build(
        dockerfile_path=_PARENT_DIR / "test_image.Dockerfile",
        context_path=_PARENT_DIR,
        architecture=architectures,
        build_args={
            "REQUIREMENTS_FILE_CONTENT": REQUIREMENTS_DEV_COVERAGE,
        },
        build_contexts={
            "prod_image": f"docker-image://{prod_image_name}",
        },
        output=LocalDirectoryBuildOutput(
            dest=output_dir,
        )
    )