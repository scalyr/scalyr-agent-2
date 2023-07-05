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

        self.architecture = architecture
        self.libc = libc
        super(PrepareBuildBaseStep, self).__init__(
            name=_PARENT_DIR.name,
            context=_PARENT_DIR,
            dockerfile=_PARENT_DIR / "Dockerfile",
            platform=architecture,
            build_args={
                "ARCH": self.architecture.value,
                "LIBC": self.libc.value,
            }
        )