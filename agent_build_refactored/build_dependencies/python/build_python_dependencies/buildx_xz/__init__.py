import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.build_dependencies.python.build_python_dependencies.base import BasePythonDependencyBuildStep


class BuildPythonXZStep(BasePythonDependencyBuildStep):
    BUILD_CONTEXT_PATH = pl.Path(__file__).parent

    def __init__(self, xz_version: str, architecture: CpuArch, libc: str):
        super(BuildPythonXZStep, self).__init__(
            name="build_xz",
            version=xz_version,
            architecture=architecture,
            libc=libc,
        )
