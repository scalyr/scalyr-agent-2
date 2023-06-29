import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch, LibC
from agent_build_refactored.build_dependencies.python.build_python_dependencies.base import BasePythonDependencyBuildStep


class BuildPythonOpenSSLStep(BasePythonDependencyBuildStep):
    BUILD_CONTEXT_PATH = pl.Path(__file__).parent

    def __init__(
        self,
        version: str,
        major_version: str,
        install_prefix: pl.Path,
        architecture: CpuArch,
        libc: LibC,
    ):

        super(BuildPythonOpenSSLStep, self).__init__(
            install_prefix=install_prefix,
            architecture=architecture,
            libc=libc,
            build_args={
                "MAJOR_VERSION": major_version,
                "VERSION": version,
            },
            unique_name_suffix=f"_{major_version}"
        )
