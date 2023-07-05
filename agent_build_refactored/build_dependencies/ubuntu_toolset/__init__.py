import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch, SOURCE_ROOT
from agent_build_refactored.tools.builder import BuilderStep

_PARENT_DIR = pl.Path(__file__).parent


class ToolsetStep(BuilderStep):
    def __init__(
        self
    ):
        super(ToolsetStep, self).__init__(
            name=_PARENT_DIR.name,
            context=SOURCE_ROOT,
            dockerfile=_PARENT_DIR / "Dockerfile",
            platform=CpuArch.x86_64,
        )