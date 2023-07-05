import pathlib as pl

from agent_build_refactored.tools.builder import BuilderStep
from agent_build_refactored.build_dependencies.python.build_python import BuilderPythonStep
from agent_build_refactored.build_dependencies.python.build_dev_requirements import BuildDevRequirementsStep


_PARENT_DIR = pl.Path(__file__).parent


class PrepareBuildBaseWithPythonStep(BuilderStep):
    def __init__(
        self,
        build_python_step: BuilderPythonStep,
        build_dev_requirements_step: BuildDevRequirementsStep,
        run_in_remote_builder_if_possible: bool = False,
    ):

        self.build_python_step = build_python_step
        self.build_dev_requirements_step = build_dev_requirements_step
        self.architecture = self.build_python_step.architecture
        self.libc = self.build_python_step.libc

        super(PrepareBuildBaseWithPythonStep, self).__init__(
            name=_PARENT_DIR.name,
            context=_PARENT_DIR,
            dockerfile=_PARENT_DIR / "Dockerfile",
            platform=self.architecture,
            build_contexts=[
                self.build_python_step.prepare_build_base_step,
                self.build_python_step.build_python_dependencies_step,
                self.build_python_step,
                self.build_dev_requirements_step,
            ],
            build_args={
                "INSTALL_PREFIX": str(self.build_python_step.install_prefix),
                "PYTHON_DEPENDENCIES_INSTALL_PREFIX": str(self.build_python_step.dependencies_install_prefix),
                "REQUIREMENTS_CONTENT": self.build_dev_requirements_step.requirements_file_content,
            },
            run_in_remote_builder_if_possible=run_in_remote_builder_if_possible,
        )