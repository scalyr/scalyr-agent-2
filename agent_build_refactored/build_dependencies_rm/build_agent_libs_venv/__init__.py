import pathlib as pl


from agent_build_refactored.build_dependencies.python.prepare_build_base_with_python import (
    PrepareBuildBaseWithPythonStep
)

from agent_build_refactored.build_dependencies.python.build_dev_requirements import BuildDevRequirementsStep

_PARENT_DIR = pl.Path(__file__).parent


class BuildAgentLibsVenvStep(BuilderStep):
    def __init__(
        self,
        prepare_build_base_with_python_step: PrepareBuildBaseWithPythonStep,
    ):
        self.prepare_build_base_with_python_step = prepare_build_base_with_python_step
        self.build_python_step = prepare_build_base_with_python_step.build_python_step
        self.build_dev_requirements_step = prepare_build_base_with_python_step.build_dev_requirements_step

        self.architecture = self.prepare_build_base_with_python_step.architecture
        self.libc = self.prepare_build_base_with_python_step.libc

        super(BuildAgentLibsVenvStep, self).__init__(
            name=_PARENT_DIR.name,
            context=_PARENT_DIR,
            dockerfile=_PARENT_DIR / "Dockerfile",
            platform=self.architecture,
            build_contexts=[
                self.prepare_build_base_with_python_step,
                self.build_dev_requirements_step,
            ],
            build_args={
                "PYTHON_INSTALL_PREFIX": str(self.build_python_step.install_prefix),
                "REQUIREMENTS": ALL_AGENT_REQUIREMENTS
            }
        )