import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.build_dependencies.python.build_python_dependencies.base import BasePythonDependencyBuildStep


class BuildPythonNcursesStep(BasePythonDependencyBuildStep):
    BUILD_CONTEXT_PATH = pl.Path(__file__).parent

    def __init__(self, version: str, architecture: CpuArch, libc: str):
        super(BuildPythonNcursesStep, self).__init__(
            name="build_ncurses",
            version=version,
            architecture=architecture,
            libc=libc
        )
