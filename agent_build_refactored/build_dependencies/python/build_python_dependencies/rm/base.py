import pathlib as pl
from typing import Dict, List

from agent_build_refactored.tools.constants import CpuArch, LibC
from agent_build_refactored.tools.builder import BuilderStep
from agent_build_refactored.build_dependencies.python.download_source_base import DownloadSourcesBaseStep
from ..prepare_build_base import PrepareBuildBaseStep

PARENT_DIR = pl.Path(__file__).parent

PYTHON_DEPENDENCIES_INSTALL_PREFIX = "/usr/local"


class BasePythonDependencyBuildStep(BuilderStep):
    BUILD_CONTEXT_PATH: pl.Path

    def __init__(
        self,
        install_prefix: pl.Path,
        architecture: CpuArch,
        libc: LibC,
        build_args: Dict[str, str] = None,
        build_contexts: List[BuilderStep] = None,
        unique_name_suffix: str = None,
    ):
        self.prepare_build_base_step = PrepareBuildBaseStep(
            architecture=architecture,
            libc=libc
        )

        build_args = build_args or {}
        build_args.update(
            {
                "INSTALL_PREFIX": str(install_prefix),
                "ARCH": architecture.value,
                "LIBC": libc.value,
            },
        )

        build_contexts = build_contexts or []
        build_contexts.extend([
            self.prepare_build_base_step,
        ])

        super(BasePythonDependencyBuildStep, self).__init__(
            name=self.__class__.BUILD_CONTEXT_PATH.name,
            context=self.__class__.BUILD_CONTEXT_PATH,
            build_contexts=build_contexts,
            dockerfile=self.__class__.BUILD_CONTEXT_PATH / "Dockerfile",
            build_args=build_args,
            platform=architecture,
            unique_name_suffix=unique_name_suffix,
        )
