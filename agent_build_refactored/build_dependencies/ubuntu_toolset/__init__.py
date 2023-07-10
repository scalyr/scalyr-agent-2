import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch, SOURCE_ROOT, LibC
from agent_build_refactored.tools.builder import BuilderStep
from agent_build_refactored.build_dependencies.python.build_python import BuilderPythonStep
from agent_build_refactored.build_dependencies.python.build_dev_requirements import BuildDevRequirementsStep
from agent_build_refactored.build_dependencies.python import (
    BUILD_PYTHON_STEPS,
    BUILD_DEV_REQUIREMENTS_STEPS,
)

_PARENT_DIR = pl.Path(__file__).parent


class UbuntuToolset(BuilderStep):
    def __init__(
        self,

    ):

        self.architecture = CpuArch.x86_64
        self.libc = LibC.GNU

        self.build_python_step = BUILD_PYTHON_STEPS[self.libc][self.architecture]

        self.build_dev_requirement_step = BUILD_DEV_REQUIREMENTS_STEPS[self.libc][self.architecture]

        super(UbuntuToolset, self).__init__(
            name=_PARENT_DIR.name,
            context=_PARENT_DIR,
            dockerfile=_PARENT_DIR / "Dockerfile",
            platform=self.architecture,
            build_contexts=[
                self.build_python_step.prepare_build_base_step,
                self.build_python_step.build_python_dependencies_step,
                self.build_python_step,
                self.build_dev_requirement_step,
            ],
            build_args={
                "PYTHON_INSTALL_PREFIX": str(self.build_python_step.install_prefix),
                "PYTHON_DEPENDENCIES_INSTALL_PREFIX": str(self.build_python_step.dependencies_install_prefix),
                "REQUIREMENTS_CONTENT": self.build_dev_requirement_step.requirements_file_content,
            }
        )


UBUNTU_TOOLSET_X86_64 = UbuntuToolset()