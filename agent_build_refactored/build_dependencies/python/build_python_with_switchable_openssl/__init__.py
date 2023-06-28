import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.tools.builder import BuilderStep
from agent_build_refactored.build_dependencies.python.build_python import (
    BuilderPythonStep,
    BUILD_TYPE_MAX_COMPATIBILITY
)

_PARENT_DIR = pl.Path(__file__).parent


def _get_python_x_y_version(version: str):
    return ".".join(version.split(".")[:2])


class BuildPythonWithSwitchableOpenSSL(BuilderStep):
    def __init__(
        self,
        python_version: str,
        openssl_1_version: str,
        openssl_3_version: str,
        architecture: CpuArch,
        libc: str
    ):

        python_install_prefix = pl.Path("/opt/scalyr-agent-2/python3")
        python_dependencies_install_prefix = pl.Path("/usr/local")

        dependencies_source_type = BUILD_TYPE_MAX_COMPATIBILITY
        self.build_python_with_openssl_1_step = BuilderPythonStep(
            python_version=python_version,
            openssl_version=openssl_1_version,
            install_prefix=python_install_prefix,
            build_type=dependencies_source_type,
            dependencies_install_prefix=python_dependencies_install_prefix,
            architecture=architecture,
            libc=libc
        )

        self.build_python_with_openssl_3_step = BuilderPythonStep(
            python_version=python_version,
            openssl_version=openssl_3_version,
            install_prefix=python_install_prefix,
            build_type=dependencies_source_type,
            dependencies_install_prefix=python_dependencies_install_prefix,
            architecture=architecture,
            libc=libc
        )

        python_x_y_version = _get_python_x_y_version(version=python_version)

        super(BuildPythonWithSwitchableOpenSSL, self).__init__(
            name="build_python_with_switchable_openssl",
            context=_PARENT_DIR,
            dockerfile_path=_PARENT_DIR / "Dockerfile",
            build_contexts=[
                self.build_python_with_openssl_3_step.prepare_build_base_step,
                self.build_python_with_openssl_1_step.build_openssl_step,
                self.build_python_with_openssl_1_step,
                self.build_python_with_openssl_3_step.build_openssl_step,
                self.build_python_with_openssl_3_step,
            ],
            build_args={
                "PYTHON_INSTALL_PREFIX": str(python_install_prefix),
                "PYTHON_X_Y_VERSION": python_x_y_version,
                "COMMON_PYTHON_DEPENDENCY_PYTHON_INSTALL_PREFIX": python_dependencies_install_prefix
            }
        )