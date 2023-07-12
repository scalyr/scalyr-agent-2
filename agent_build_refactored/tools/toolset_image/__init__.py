import pathlib as pl
import shutil

from agent_build_refactored.tools.constants import SOURCE_ROOT, CpuArch, OCI_LAYOUTS_DIR
from agent_build_refactored.tools.docker.buildx.build import DockerImageBuildOutput, buildx_build, OCITarballBuildOutput, BuildOutput

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
        cache_scope=_NAME,
    )


def build_toolset_image():
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