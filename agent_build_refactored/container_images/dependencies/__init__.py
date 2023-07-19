import collections
import pathlib as pl
import shutil
from typing import Dict, Set, List

from agent_build_refactored.tools.constants import CpuArch, OCI_LAYOUTS_DIR, AGENT_REQUIREMENTS, AGENT_BUILD_OUTPUT_PATH, SOURCE_ROOT
from agent_build_refactored.tools.docker.buildx.build import buildx_build, OCITarballBuildOutput, LocalDirectoryBuildOutput, BuildOutput


from agent_build_refactored.container_images.dependencies.base_images import UBUNTU_BASE_IMAGE, ALPINE_BASE_IMAGE

_PARENT_DIR = pl.Path(__file__).parent

BASE_DISTRO_IMAGE_NAMES = {
    "ubuntu": UBUNTU_BASE_IMAGE,
    "alpine": ALPINE_BASE_IMAGE,
}

_existing_built_images: Dict[str, Set[CpuArch]] = collections.defaultdict(set)


def build_agent_image_dependencies(
    base_distro: str,
    architectures: List[CpuArch],
    output: BuildOutput,

):
    global _existing_built_images

    arch_suffix = ""
    for arch in architectures:
        arch_suffix = f"{arch_suffix}_{arch.value}"
    cache_name = f"agent_container_image_dependencies_{base_distro}_{arch_suffix}"
    result_dir = AGENT_BUILD_OUTPUT_PATH / cache_name

    # def _copy_output():
    #     output_dir.mkdir(parents=True, exist_ok=True)
    #     shutil.copytree(
    #         result_dir,
    #         output_dir,
    #         dirs_exist_ok=True,
    #         symlinks=True,
    #     )

    # if architecture in _existing_built_images[base_distro]:
    #     #_copy_output()
    #     return result_dir

    if result_dir.exists():
        shutil.rmtree(result_dir)

    base_image_name = BASE_DISTRO_IMAGE_NAMES[base_distro]

    buildx_build(
        dockerfile_path=_PARENT_DIR / "Dockerfile",
        context_path=_PARENT_DIR,
        architecture=architectures,
        build_args={
            "BASE_DISTRO": base_distro,
            "AGENT_REQUIREMENTS": AGENT_REQUIREMENTS,
        },
        build_contexts={
            "base_image": f"docker-image://{base_image_name}",
        },
        # output=LocalDirectoryBuildOutput(
        #     dest=result_dir,
        # ),
        output=output,
        cache_name=cache_name,
        #fallback_to_remote_builder=True,
    )

    # _existing_built_images[base_distro].add(architecture)
    # _copy_output()
    # return result_dir