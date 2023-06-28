import pathlib as pl

from agent_build_refactored.tools.constants import ALL_AGENT_REQUIREMENTS
from agent_build_refactored.tools.builder import BuilderStep
from agent_build_refactored.build_dependencies.python.prepare_build_base_with_python import (
    PrepareBuildBaseWithPythonStep
)

_PARENT_DIR = pl.Path(__file__).parent


class BuildAgentLibsVenvStep(BuilderStep):
    def __init__(
        self,
        prepare_build_base_with_python_step: PrepareBuildBaseWithPythonStep
    ):
        build_python_step = prepare_build_base_with_python_step.build_python_step
        super(BuildAgentLibsVenvStep, self).__init__(
            name="build_agent_libs_venv",
            context=_PARENT_DIR,
            dockerfile_path=_PARENT_DIR / "Dockerfile",
            build_contexts=[
                prepare_build_base_with_python_step,
                prepare_build_base_with_python_step.build_dev_requirements_step,
            ],
            build_args={
                "PYTHON_INSTALL_PREFIX": str(build_python_step.install_prefix),
                "REQUIREMENTS": ALL_AGENT_REQUIREMENTS
            }
        )