import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.build_dependencies.python.build_python_dependencies.base import BasePythonDependencyBuildStep


class BuildPythonOpenSSLStep(BasePythonDependencyBuildStep):
    BUILD_CONTEXT_PATH = pl.Path(__file__).parent

    def __init__(
        self,
        version: str,
        architecture: CpuArch,
        libc: str,
        install_prefix: pl.Path
    ):

        major_version = version.split(".")[0]
        super(BuildPythonOpenSSLStep, self).__init__(
            name=f"build_openssl_{major_version}",
            version=version,
            architecture=architecture,
            libc=libc,
            build_args={
                "MAJOR_VERSION": major_version,
            },
            install_prefix=install_prefix,
        )
