import pathlib as pl

from agent_build_refactored.tools.constants import ALL_REQUIREMENTS
from agent_build_refactored.tools.builder import BuilderStep
from ..prepare_build_base import PrepareBuildBaseStep
from ..build_python import BuilderPythonStep
from agent_build_refactored.build_dependencies.build_dev_requirements import BuildDevRequirementsStep


_BUILD_CONTEXT_PATH = pl.Path(__file__).parent


class PrepareBuildBaseWithPythonStep(BuilderStep):
    def __init__(
        self,
        build_dev_requirements_step: BuildDevRequirementsStep,
    ):
        build_python_step = build_dev_requirements_step.build_python_step
        self.build_python_step = build_python_step
        self.build_dev_requirements_step = build_dev_requirements_step

        self.architecture = build_python_step.architecture
        self.libc = build_python_step.libc

        super(PrepareBuildBaseWithPythonStep, self).__init__(
            name="prepare_build_base_with_python",
            context=_BUILD_CONTEXT_PATH,
            dockerfile_path=_BUILD_CONTEXT_PATH / "Dockerfile",
            build_contexts=[
                build_python_step.prepare_build_base_step,
                build_python_step,
                build_dev_requirements_step,
            ],
            build_args={
                "INSTALL_PREFIX": str(build_python_step.install_prefix),
                "ALL_REQUIREMENTS": ALL_REQUIREMENTS,
            },
        )