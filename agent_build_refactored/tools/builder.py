import abc
import pathlib as pl
import shutil

from agent_build_refactored.tools.constants import SOURCE_ROOT, AGENT_BUILD_OUTPUT_PATH


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

    @staticmethod
    def to_in_docker_path(path: pl.Path):
        rel_path = path.relative_to(SOURCE_ROOT)
        in_docker_output_dir_path = pl.Path("/tmp/source_root")
        return in_docker_output_dir_path / rel_path

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