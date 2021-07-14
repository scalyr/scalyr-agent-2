import pathlib as pl
import abc
import sys
import shlex
from typing import List, Union

from agent_build.docker_images.image_builder import ImageBuilder
from agent_build.package_builder import builder
from agent_build import common

__all__ = ["PackageBuilderInsideDocker"]

_PARENT_DIR = pl.Path(__file__).parent


class PackageBuilderInsideDocker(builder.PackageBuilder, metaclass=abc.ABCMeta):
    BASE_IMAGE: ImageBuilder = None
    DOCKERFILE_PATH: Union[str, pl.Path] = _PARENT_DIR / "Dockerfile"

    @classmethod
    def _get_used_files(cls):
        return cls.BASE_IMAGE.get_used_files()

    @classmethod
    def prepare_dependencies(
            cls,
            cache_dir:
            Union[str, pl.Path] = None,
    ):
        cls.BASE_IMAGE.build(cache_dir=cache_dir)

    def _build_in_docker(
            self,
            build_info: common.PackageBuildInfo,
            output_path: Union[str, pl.Path],
    ):
        # if we build package inside the docker, then we need to pre-build the base image first.
        self.prepare_dependencies()

        # Build the package using docker.
        image_name = f"scalyr-agent-{self.package_type_name}-package-builder"

        # When package is build inside the docker, the trick is to run the script 'agent_build/build_package.py
        # once more but inside the docker image build.
        new_argv = []
        i = 0
        while True:
            if i >= len(sys.argv):
                break
            v = sys.argv[i]
            i += 1

            if v == "--output-dir":
                i += 1
                continue

            path = pl.Path(v)
            if path.exists():
                if not path.is_absolute():
                    path = path.absolute()

                rel_path = path.relative_to(common.SOURCE_ROOT)

                value = str(pl.Path("/scalyr-agent-2", rel_path))
            else:
                value = v

            new_argv.append(shlex.quote(value))

        # create the command to run the build_package.py script, but with '--locally' option.
        command_to_execute = f"python3 {' '.join(new_argv)} " \
                             f"--output-dir /tmp/build/package --locally"

        image_builder = ImageBuilder(
            image_name=image_name,
            source_dir=common.SOURCE_ROOT,
            dockerfile_path=self.DOCKERFILE_PATH,
            build_args={
                "ARGV": command_to_execute,
                "BASE_IMAGE_NAME": type(self).BASE_IMAGE.image_name
            }
        )
        # Build the image and, thereby, build the package.
        image_builder.build()

        # Save package from the build image.
        image_builder.save_artifacts(
            paths={"/tmp/build/package": output_path}
        )

    def build(
            self,
            build_info: common.PackageBuildInfo,
            output_path: Union[str, pl.Path]
    ):
        if self._locally:
            # if the 'locally' option is set, then build the package directly on the current system.
            # NOTE: The current system has to be prepared to run this script. In opposite, it's better try it
            # inside the docker.
            super(PackageBuilderInsideDocker, self).build(
                build_info=build_info,
                output_path=output_path
            )
        else:
            self._build_in_docker(
                build_info=build_info,
                output_path=output_path
            )
