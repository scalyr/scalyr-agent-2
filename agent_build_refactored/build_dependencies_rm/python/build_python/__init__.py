import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch, LibC
from agent_build_refactored.tools.builder import BuilderStep
from agent_build_refactored.build_dependencies.python.prepare_build_base import PrepareBuildBaseStep
from agent_build_refactored.build_dependencies.python.download_sources import DownloadSourcesStep
from agent_build_refactored.build_dependencies.python.build_python_dependencies import BuildPytonDependenciesStep

_PARENT_DIR = pl.Path(__file__).parent


class BuilderPythonStep(BuilderStep):

    def __init__(
        self,
        download_sources_step: DownloadSourcesStep,
        prepare_build_base_step: PrepareBuildBaseStep,
        build_python_dependencies_step: BuildPytonDependenciesStep,
        openssl_version: str,
        install_prefix: pl.Path,
        dependencies_install_prefix: pl.Path,
        run_in_remote_builder_if_possible: bool = False,
    ):
        self.download_sources_step = download_sources_step
        self.prepare_build_base_step = prepare_build_base_step
        self.build_python_dependencies_step = build_python_dependencies_step
        self.openssl_version = openssl_version
        self.install_prefix = install_prefix
        self.dependencies_install_prefix = dependencies_install_prefix
        self.architecture = self.prepare_build_base_step.architecture
        self.libc = self.prepare_build_base_step.libc

        openssl_major_version = openssl_version.strip(".")[0]

        super(BuilderPythonStep, self).__init__(
            name=_PARENT_DIR.name,
            context=_PARENT_DIR,
            dockerfile=_PARENT_DIR / "Dockerfile",
            platform=self.architecture,
            build_contexts=[
                self.prepare_build_base_step,
                self.download_sources_step,
                self.build_python_dependencies_step,
            ],
            build_args={
                "INSTALL_PREFIX": str(self.install_prefix),
                "OPENSSL_MAJOR_VERSION": openssl_major_version,
                "PYTHON_DEPENDENCIES_INSTALL_PREFIX": self.build_python_dependencies_step.install_prefix,
                "ARCH": self.architecture.value,
                "LIBC": self.libc,
            },
            unique_name_suffix=f"_with_openssl_{openssl_major_version}",
            run_in_remote_builder_if_possible=run_in_remote_builder_if_possible,
        )