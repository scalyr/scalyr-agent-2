import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.tools.builder import BuilderStep


class PrepareBuildBaseStep(BuilderStep):
    BUILD_CONTEXT = pl.Path(__file__).parent

    def __init__(
        self,
        architecture: CpuArch,
        libc: str,
    ):

        super(PrepareBuildBaseStep, self).__init__(
            name="prepare_build_base",
            context=self.__class__.BUILD_CONTEXT,
            platform=architecture,
            dockerfile_path=self.__class__.BUILD_CONTEXT / "Dockerfile",
            build_args={
                "ARCH": architecture.value,
                "LIBC": libc,
            }
        )