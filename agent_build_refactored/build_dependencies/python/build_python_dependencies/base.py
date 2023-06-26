import pathlib as pl
from typing import Dict, List

from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.tools.builder import BuilderStep
from .download_sources_base import DownloadSourcesBaseStep
from ..prepare_build_base import PrepareBuildBaseStep

PARENT_DIR = pl.Path(__file__).parent

COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX = "/usr/local"


class BasePythonDependencyBuildStep(BuilderStep):
    BUILD_CONTEXT_PATH: pl.Path

    def __init__(
        self,
        name: str,
        version: str,
        architecture: CpuArch,
        libc: str,
        build_args: Dict[str, str] = None,
        build_contexts: List[BuilderStep] = None,
        install_prefix=COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX,
    ):
        self.download_base_step = DownloadSourcesBaseStep()
        self.prepare_build_base_step = PrepareBuildBaseStep(
            architecture=architecture,
            libc=libc
        )

        build_args = build_args or {}
        build_args.update(
            {
                "VERSION": version,
                "INSTALL_PREFIX": install_prefix,
                "ARCH": architecture.value,
                "LIBC": libc,
            },
        )

        build_contexts = build_contexts or []
        build_contexts.extend([
            self.download_base_step,
            self.prepare_build_base_step,
        ])

        super(BasePythonDependencyBuildStep, self).__init__(
            name=name,
            context=self.__class__.BUILD_CONTEXT_PATH,
            build_contexts=build_contexts,
            dockerfile_path=self.__class__.BUILD_CONTEXT_PATH / "Dockerfile",
            build_args=build_args,
            platform=CpuArch.x86_64,
        )
