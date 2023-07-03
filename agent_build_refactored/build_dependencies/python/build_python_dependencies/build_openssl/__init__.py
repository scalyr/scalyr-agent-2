import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch, LibC
from agent_build_refactored.build_dependencies.python.build_python_dependencies.base import BasePythonDependencyBuildStep
from agent_build_refactored.build_dependencies.python.download_sources import DownloadSourcesStep


class BuildPythonOpenSSLStep(BasePythonDependencyBuildStep):
    BUILD_CONTEXT_PATH = pl.Path(__file__).parent

    def __init__(
        self,
        download_source_step: DownloadSourcesStep,
        major_version: str,
        install_prefix: pl.Path,
        architecture: CpuArch,
        libc: LibC,
    ):

        if major_version == "3":
            openssl_version = download_source_step.openssl_3_version
        elif major_version == "1":
            openssl_version = download_source_step.openssl_1_version
        else:
            raise Exception(f"Unknown openssl major version: {major_version}")

        super(BuildPythonOpenSSLStep, self).__init__(
            install_prefix=install_prefix,
            architecture=architecture,
            libc=libc,
            build_contexts=[
                download_source_step,
            ],
            build_args={
                "MAJOR_VERSION": major_version,
                "VERSION": openssl_version,
            },
            unique_name_suffix=f"_{major_version}"
        )
