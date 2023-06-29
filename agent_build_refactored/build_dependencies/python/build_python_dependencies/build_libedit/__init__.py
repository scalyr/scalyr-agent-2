import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch, LibC
from agent_build_refactored.build_dependencies.python.build_python_dependencies.base import BasePythonDependencyBuildStep
from ..build_ncurses import BuildPythonNcursesStep


class BuildPythonLibeditStep(BasePythonDependencyBuildStep):
    BUILD_CONTEXT_PATH = pl.Path(__file__).parent

    def __init__(
            self,
            version_commit: str,
            install_prefix: pl.Path,
            architecture: CpuArch,
            libc: LibC,
            build_ncurses_step: BuildPythonNcursesStep
    ):
        super(BuildPythonLibeditStep, self).__init__(
            install_prefix=install_prefix,
            architecture=architecture,
            libc=libc,
            build_contexts=[build_ncurses_step],
            build_args={
                "VERSION_COMMIT": version_commit
            }
        )
