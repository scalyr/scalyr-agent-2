import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch, LibC
from agent_build_refactored.build_dependencies.python.build_python_dependencies.base import BasePythonDependencyBuildStep
from ..build_ncurses import BuildPythonNcursesStep
from agent_build_refactored.build_dependencies.python.download_sources import DownloadSourcesStep


class BuildPythonLibeditStep(BasePythonDependencyBuildStep):
    BUILD_CONTEXT_PATH = pl.Path(__file__).parent

    def __init__(
            self,
            download_source_step: DownloadSourcesStep,
            install_prefix: pl.Path,
            architecture: CpuArch,
            libc: LibC,
            build_ncurses_step: BuildPythonNcursesStep
    ):
        super(BuildPythonLibeditStep, self).__init__(
            install_prefix=install_prefix,
            architecture=architecture,
            libc=libc,
            build_contexts=[
                download_source_step,
                build_ncurses_step
            ],
            build_args={
                "VERSION_COMMIT": download_source_step.libedit_version_commit,
            }
        )
