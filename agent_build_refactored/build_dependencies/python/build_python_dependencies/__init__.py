import pathlib as pl

from agent_build_refactored.tools.builder import BuilderStep
from agent_build_refactored.build_dependencies.python.download_sources import DownloadSourcesStep
from agent_build_refactored.build_dependencies.python.prepare_build_base import PrepareBuildBaseStep


_PARENT_DIR = pl.Path(__file__).parent


class BuildPytonDependenciesStep(BuilderStep):
    def __init__(
        self,
        download_sources_step: DownloadSourcesStep,
        prepare_build_base: PrepareBuildBaseStep,
        install_prefix: pl.Path,
    ):
        self.download_sources_step = download_sources_step
        self.prepare_build_base = prepare_build_base
        self.install_prefix = install_prefix
        self.architecture = self.prepare_build_base.architecture
        self.libc = self.prepare_build_base.libc

        super(BuildPytonDependenciesStep, self).__init__(
            name="build_python_dependencies",
            context=_PARENT_DIR,
            dockerfile=_PARENT_DIR / "Dockerfile",
            platform=self.architecture,
            build_contexts=[
                self.download_sources_step,
                self.prepare_build_base,
            ],
            build_args={
                "INSTALL_PREFIX": str(install_prefix),
                "ARCH": self.architecture.value,
                "LIBC": self.libc.value,
            },
        )
