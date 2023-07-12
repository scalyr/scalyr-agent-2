import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch, LibC, SOURCE_ROOT
from agent_build_refactored.tools.builder import BuilderStep
from agent_build_refactored.build_dependencies.python.build_python import BuilderPythonStep


_PARENT_DIR = pl.Path(__file__).parent


class BuildDevRequirementsStep(BuilderStep):
    def __init__(
        self,
        build_python_step: BuilderPythonStep,
        run_in_remote_builder_if_possible: bool = False,
    ):

        self.build_python_step = build_python_step
        self.architecture = self.build_python_step.architecture
        self.libc = self.build_python_step.libc

        if self.architecture != CpuArch.ARMV7:
            abi_part = ""
        else:
            abi_part = "eabihf"

        rust_platform = f"{self.architecture.value}-unknown-linux-{self.libc.value}{abi_part}"

        requirements_file = SOURCE_ROOT / "dev-requirements-new.txt"
        self.requirements_file_content = requirements_file.read_text()

        super(BuildDevRequirementsStep, self).__init__(
            name=_PARENT_DIR.name,
            context=_PARENT_DIR,
            dockerfile=_PARENT_DIR / "Dockerfile",
            platform=self.architecture,
            build_contexts=[
                self.build_python_step.prepare_build_base_step,
                self.build_python_step.build_python_dependencies_step,
                self.build_python_step,
            ],
            build_args={
                "PYTHON_INSTALL_PREFIX": str(self.build_python_step.install_prefix),
                "PYTHON_DEPENDENCIES_INSTALL_PREFIX": str(self.build_python_step.dependencies_install_prefix),
                "REQUIREMENTS_CONTENT": self.requirements_file_content,
                "RUST_VERSION": "1.63.0",
                "RUST_PLATFORM": rust_platform,
            },
            run_in_remote_builder_if_possible=run_in_remote_builder_if_possible,
        )