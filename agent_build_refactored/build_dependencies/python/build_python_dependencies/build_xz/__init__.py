import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch, LibC
from agent_build_refactored.build_dependencies.python.build_python_dependencies.base import BasePythonDependencyBuildStep
from agent_build_refactored.build_dependencies.python.download_sources import DownloadSourcesStep


class BuildXZStep(BasePythonDependencyBuildStep):
    BUILD_CONTEXT_PATH = pl.Path(__file__).parent

    def __init__(
            self,
            download_source_step: DownloadSourcesStep,
            install_prefix: pl.Path,
            architecture: CpuArch,
            libc: LibC
    ):
        super(BuildXZStep, self).__init__(
            install_prefix=install_prefix,
            architecture=architecture,
            libc=libc,
            build_contexts=[
                download_source_step,
            ],
            build_args={
                "VERSION": download_source_step.xz_version,
            },
        )
