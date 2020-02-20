from __future__ import unicode_literals
from __future__ import print_function

from typing import Type
from abc import ABCMeta, abstractmethod
import argparse

import docker
import six

from ..utils import create_temp_dir_with_constant_name, copy_agent_source as copy_source
from ..compat import Path


@six.add_metaclass(ABCMeta)
class Builder(object):
    IMAGE_TAG = None  # type: six.text_type

    def __init__(self,
                 docker_client=None,
                 skip_if_exists=False,
                 copy_agent_source=False
                 ):
        self._docker = docker_client or docker.from_env()
        self._skip_if_exists = skip_if_exists
        self._copy_agent_source = copy_agent_source
        self._image = None  # type : Optional

    @property
    def image_tag(self):
        return type(self).IMAGE_TAG

    @property
    @abstractmethod
    def dockerfile(self):  # type: () -> six.text_type
        pass

    def build(self):

        if self._skip_if_exists:
            if self._docker.images.list(name=self.image_tag):
                return

        build_context_path = create_temp_dir_with_constant_name(".scalyr_agent_testing")

        dockerfile_path = build_context_path / "Dockerfile"
        dockerfile_path.write_text(self.dockerfile)
        if self._copy_agent_source:
            agent_source_path = build_context_path / "agent_source"
            copy_source(agent_source_path)

        self._docker.images.build(
            tag=self.image_tag,
            path=six.text_type(build_context_path),
            dockerfile=six.text_type(dockerfile_path),
            rm=True,
        )

        return

    def circleci_build(self, path):  # type: (Path) -> None
        image_file_path = path / self.image_tag
        if not image_file_path.exists():
            print("Image file '{}' does not exist. Build it.".format(self.image_tag))
            self.build()
            print("Save image file to '{}'.".format(self.image_tag))
            self.save(image_file_path)
        else:
            print("Image file '{}' exists. Use it and skip the build.".format(self.image_tag))
            self.load(image_file_path)

    def load(self, path):  # type: (Path) -> None
        with path.open("rb") as f:
            self._docker.images.load(f.read())

    def save(self, path):  # type: (Path) -> None
        image = self._docker.images.list(name=self.image_tag)
        if image:
            if not path.parent.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as f:
                for chunk in image[0].save():
                    f.write(chunk)

            print("Image '{}' saved.".format(self.image_tag))


def handle_command_line(builder_cls):  # type: (Type[Builder]) -> None
    parser = argparse.ArgumentParser()
    # parser.add_argument("image_tag")
    parser.add_argument(
        "--dockerfile",
        action="store_true",
        default=False
    )
    parser.add_argument(
        "--skip-if-exists",
        action="store_true",
        default=False
    )

    parser.add_argument(
        "--image-tag",
        action="store_true",
        default=False
    )

    parser.add_argument(
        "--circleci-build",
    )

    args = parser.parse_args()

    builder = builder_cls(skip_if_exists=args.skip_if_exists)

    if args.dockerfile:
        print(builder.dockerfile)
    elif args.image_tag:
        print(builder.IMAGE_TAG)
    elif args.circleci_build:
        builder.circleci_build(Path(args.circleci_build))
    else:
        builder.build()
