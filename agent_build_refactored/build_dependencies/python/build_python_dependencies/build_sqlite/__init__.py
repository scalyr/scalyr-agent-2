import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.build_dependencies.python.build_python_dependencies.base import BasePythonDependencyBuildStep


class BuildPythonSqliteStep(BasePythonDependencyBuildStep):
    BUILD_CONTEXT_PATH = pl.Path(__file__).parent

    def __init__(
        self,
        version_commit: str,
        install_prefix: pl.Path,
        architecture: CpuArch,
        libc: str
    ):
        super(BuildPythonSqliteStep, self).__init__(
            name="build_sqlite",
            install_prefix=install_prefix,
            architecture=architecture,
            libc=libc,
            build_args={
                "TCL_VERSION_COMMIT": "338c6692672696a76b6cb4073820426406c6f3f9",  # tag - "core-8-6-13"
                "VERSION_COMMIT": version_commit
            },
        )
