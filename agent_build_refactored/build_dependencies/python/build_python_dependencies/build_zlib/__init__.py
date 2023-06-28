import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.build_dependencies.python.build_python_dependencies.base import BasePythonDependencyBuildStep


class BuildPythonZlibStep(BasePythonDependencyBuildStep):
    BUILD_CONTEXT_PATH = pl.Path(__file__).parent

    def __init__(
        self,
        version: str,
        install_prefix: pl.Path,
        architecture: CpuArch,
        libc: str
    ):
        super(BuildPythonZlibStep, self).__init__(
            name="build_zlib",
            install_prefix=install_prefix,
            architecture=architecture,
            libc=libc,
            build_args={
                "VERSION": version
            },
        )
