import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch, LibC
from agent_build_refactored.build_dependencies.python.build_python_dependencies.base import BasePythonDependencyBuildStep
from agent_build_refactored.build_dependencies.python.download_sources import DownloadSourcesStep


class BuildPythonSqliteStep(BasePythonDependencyBuildStep):
    BUILD_CONTEXT_PATH = pl.Path(__file__).parent

    def __init__(
        self,
        download_source_step: DownloadSourcesStep,
        install_prefix: pl.Path,
        architecture: CpuArch,
        libc: LibC
    ):
        super(BuildPythonSqliteStep, self).__init__(
            install_prefix=install_prefix,
            architecture=architecture,
            libc=libc,
            build_contexts=[
                download_source_step,
            ],
            build_args={
                "TCL_VERSION_COMMIT": download_source_step.tcl_version_commit,
                "VERSION_COMMIT": download_source_step.sqlite_version_commit,
            },
        )
