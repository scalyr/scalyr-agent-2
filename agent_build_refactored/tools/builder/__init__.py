import abc
import pathlib as pl
import shlex
import shutil
from typing import List

from agent_build_refactored.tools.constants import SOURCE_ROOT, AGENT_BUILD_OUTPUT_PATH, CpuArch
from agent_build_refactored.tools.docker.buildx.build import buildx_build, LocalDirectoryBuildOutput

_PARENT_DIR = pl.Path(__file__).parent


class Builder:
    NAME: str = None

    def __init__(
        self
    ):
        self.name = self.__class__.NAME

    @property
    def root_dir(self) -> pl.Path:
        return AGENT_BUILD_OUTPUT_PATH / "builders" / self.name

    @property
    def result_dir(self) -> pl.Path:
        return self.root_dir / "result"

    @property
    def work_dir(self):
        return self.root_dir / "work"

    @abc.abstractmethod
    def _build(self):
        pass

    def to_in_docker_path(self, path: pl.Path):
        rel_path = path.relative_to(self.root_dir)
        in_docker_output_dir_path = pl.Path("/tmp/root")
        return in_docker_output_dir_path / rel_path

    def get_new_work_subdir_path(self, subdir_name: str):
        return self.work_dir / subdir_name

    def build(
        self,
        output_dir: pl.Path = None,
    ):

        if self.root_dir.exists():
            shutil.rmtree(self.root_dir)

        self.root_dir.mkdir(parents=True)

        self.work_dir.mkdir(parents=True)
        self.result_dir.mkdir(parents=True)

        self._build()

        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                self.result_dir,
                output_dir,
                symlinks=True,
                dirs_exist_ok=True,
            )

    def run_command_in_docker(
        self,
        cmd_args: List[str],
        output_dir: pl.Path,
        base_image_oci_layout_dir: pl.Path,
        cwd: pl.Path = None
    ):

        cmd_str = shlex.join(cmd_args)
        in_docker_root_dir = self.to_in_docker_path(self.root_dir)
        in_docker_cmd_output_dir = self.to_in_docker_path(output_dir)

        additional_build_args = {}
        if cwd:
            in_docker_cwd = self.to_in_docker_path(cwd)
            additional_build_args["CWD"] = str(in_docker_cwd)

        return buildx_build(
            dockerfile_path=_PARENT_DIR / "run_cmd.Dockerfile",
            context_path=SOURCE_ROOT,
            architecture=CpuArch.x86_64,
            build_args={
                "COMMAND": cmd_str,
                "ROOT_DIR": str(in_docker_root_dir),
                "OUTPUT_DIR": str(in_docker_cmd_output_dir),
                **additional_build_args,
            },
            build_contexts={
                "root_dir": str(self.root_dir),

                "base": f"oci-layout://{base_image_oci_layout_dir}"
            },
            output=LocalDirectoryBuildOutput(
                dest=output_dir,
            )
        )