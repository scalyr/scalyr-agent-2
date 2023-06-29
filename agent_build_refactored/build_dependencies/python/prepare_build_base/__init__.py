import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch, LibC
from agent_build_refactored.tools.builder import BuilderStep

_PARENT_DIR = pl.Path(__file__).parent


class PrepareBuildBaseStep(BuilderStep):
    BUILD_CONTEXT = pl.Path(__file__).parent

    def __init__(
        self,
        architecture: CpuArch,
        libc: LibC,
    ):

        super(PrepareBuildBaseStep, self).__init__(
            name=_PARENT_DIR.name,
            context=_PARENT_DIR,
            platform=architecture,
            dockerfile=_PARENT_DIR / "Dockerfile",
            build_args={
                "ARCH": architecture.value,
                "LIBC": libc.value,
            }
        )