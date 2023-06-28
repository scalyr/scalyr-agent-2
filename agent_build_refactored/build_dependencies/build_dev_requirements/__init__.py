import pathlib as pl

from agent_build_refactored.tools.constants import (
    CpuArch,
    NON_RUST_BASED_REQUIREMENTS,
    RUST_BASED_REQUIREMENTS,
)
from agent_build_refactored.tools.builder import BuilderStep
from agent_build_refactored.build_dependencies.python.build_python import BuilderPythonStep

_PARENT_DIR = pl.Path(__file__).parent


class BuildDevRequirementsStep(BuilderStep):
    def __init__(
        self,
            build_python_step: BuilderPythonStep,
    ):

        self.build_python_step = build_python_step
        architecture = build_python_step.architecture
        libc = build_python_step.libc

        if architecture != CpuArch.ARMV7:
            abi_path = ""
        else:
            abi_path = "eabihf"

        rust_platform = f"{architecture.value}-unknown-linux-{libc}{abi_path}"

        if architecture == CpuArch.ARMV7 and libc == "must":
            rust_source = "package_manager"
        else:
            rust_source = "site"

        rust_source = "package_manager"

        super(BuildDevRequirementsStep, self).__init__(
            name="build_dev_requirements",
            context=_PARENT_DIR,
            dockerfile_path=_PARENT_DIR / "Dockerfile",
            build_contexts=[
                build_python_step.download_base_step,
                build_python_step.prepare_build_base_step,
                build_python_step.build_libffi_step,
                build_python_step.build_zlib_step,
                build_python_step,
            ],
            build_args={
                "RUST_SOURCE": rust_source,
                "RUST_VERSION": "1.63.0",
                "RUST_PLATFORM": rust_platform,
                "NON_RUST_BASED_REQUIREMENTS": NON_RUST_BASED_REQUIREMENTS,
                "RUST_BASED_REQUIREMENTS": RUST_BASED_REQUIREMENTS,
                "LIBC": libc,
                "PYTHON_INSTALL_PREFIX": str(build_python_step.install_prefix),
            }
        )

