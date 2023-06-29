import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.tools.builder import BuilderStep

_PARENT_DIR = pl.Path(__file__).parent


class DownloadSourcesBaseStep(BuilderStep):

    def __init__(
        self
    ):
        super(DownloadSourcesBaseStep, self).__init__(
            name=_PARENT_DIR.name,
            context=_PARENT_DIR,
            dockerfile=_PARENT_DIR / "Dockerfile",
            platform=CpuArch.x86_64,
        )
