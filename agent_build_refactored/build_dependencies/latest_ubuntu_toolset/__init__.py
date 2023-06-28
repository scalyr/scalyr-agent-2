import pathlib as pl

from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.tools.builder import BuilderStep

PARENT_DIR = pl.Path(__file__).parent


class LatestUbuntuToolsetStep(BuilderStep):
    def __init__(
        self
    ):
        super(LatestUbuntuToolsetStep, self).__init__(
            name="latest_ubuntu_toolset",
            context=PARENT_DIR,
            dockerfile_path=PARENT_DIR / "Dockerfile",
            platform=CpuArch.x86_64,
        )