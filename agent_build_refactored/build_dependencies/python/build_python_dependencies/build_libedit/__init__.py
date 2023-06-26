import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.build_dependencies.python.build_python_dependencies.base import BasePythonDependencyBuildStep
from ..build_ncurses import BuildPythonNcursesStep


class BuildPythonLibeditStep(BasePythonDependencyBuildStep):
    BUILD_CONTEXT_PATH = pl.Path(__file__).parent

    def __init__(
            self,
            version_commit: str,
            architecture: CpuArch,
            libc: str,
            build_ncurses_step: BuildPythonNcursesStep
    ):
        super(BuildPythonLibeditStep, self).__init__(
            name="build_libedit",
            version=version_commit,
            architecture=architecture,
            libc=libc,
            build_contexts=[build_ncurses_step]

        )
