import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch, SOURCE_ROOT
from agent_build_refactored.tools.builder import BuilderStep
from agent_build_refactored.build_dependencies.python.build_python import BuilderPythonStep
from agent_build_refactored.build_dependencies.python.build_dev_requirements import BuildDevRequirementsStep

_PARENT_DIR = pl.Path(__file__).parent


class UbuntuToolset(BuilderStep):
    def __init__(
        self,
        build_python_step: BuilderPythonStep,
        build_dev_requirements_step: BuildDevRequirementsStep,

    ):
        self.build_python_step = build_python_step
        self.build_dev_requirements_step = build_dev_requirements_step
        self.architecture = build_python_step.architecture
        self.libc = build_python_step.libc
        super(UbuntuToolset, self).__init__(
            name=_PARENT_DIR.name,
            context=_PARENT_DIR,
            dockerfile=_PARENT_DIR / "Dockerfile",
            platform=self.architecture,
            build_contexts=[
                self.build_python_step.prepare_build_base_step,
                self.build_python_step.build_python_dependencies,
                self.build_python_step,
                self.build_dev_requirements_step,
            ],
            build_args={
                "PYTHON_INSTALL_PREFIX": str(self.build_python_step.install_prefix),
                "COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX": str(self.build_python_step.dependencies_install_prefix),
                "REQUIREMENTS_CONTENT": self.build_dev_requirements_step.requirements_file_content,
            }
        )