import pathlib as pl
import subprocess
from typing import Union

from agent_build.package_builder import builder

_PARENT_DIR = pl.Path(__file__).parent


class LinuxPackageBuilder(builder.PackageBuilder):
    BASE_DOCKER_IMAGE = "centos:7"
    PREPARE_ENVIRONMENT_SCRIPT_PATH = _PARENT_DIR / "prepare_build_environment.sh"

    @classmethod
    def prepare_dependencies(
            cls,
            cache_dir:
            Union[str, pl.Path] = None,
    ):
        subprocess.check_call(
            f"bash {prepare_environment_script_path}", shell=True
        )

