import pathlib as pl

from agent_build_refactored.tools.builder import BuilderStep
from ..prepare_build_base import PrepareBuildBaseStep
from ..build_python import BuilderPythonStep


_BUILD_CONTEXT_PATH = pl.Path(__file__).parent


class PrepareBuildBaseWithPythonStep(BuilderStep):
    def __init__(
        self,
        build_python_step: BuilderPythonStep,
    ):
        super(PrepareBuildBaseWithPythonStep, self).__init__(
            name="prepare_build_base_with_python",
            context=_BUILD_CONTEXT_PATH,
            dockerfile_path=_BUILD_CONTEXT_PATH / "Dockerfile",
            build_contexts=[
                build_python_step.prepare_build_base_step,
                build_python_step,
            ]
        )