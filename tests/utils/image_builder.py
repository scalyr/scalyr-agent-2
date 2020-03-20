# Copyright 2014-2020 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import unicode_literals
from __future__ import print_function
from __future__ import absolute_import

import shutil
import docker
import argparse

if False:
    from typing import Optional

from abc import ABCMeta, abstractmethod

import six

from scalyr_agent.__scalyr__ import get_package_root
from tests.utils.common import create_tmp_directory
from tests.utils.compat import Path


def _copy_agent_source(dest_path):
    root_path = Path(get_package_root()).parent
    gitignore_path = root_path / ".gitignore"
    patterns = [
        p[:-1] if p.endswith("/") else p
        for p in gitignore_path.read_text().splitlines()
        if not p.startswith("#")
    ]
    shutil.copytree(
        six.text_type(root_path),
        six.text_type(dest_path),
        ignore=shutil.ignore_patterns(*patterns),
    )
    # test_config_path = Path(root_path, "test", "config.yml")
    # if test_config_path.exists():
    #     config_dest = Path(dest_path, "tests", "config.yml")
    #     shutil.copy(test_config_path, config_dest)


@six.add_metaclass(ABCMeta)
class AgentImageBuilder(object):
    """
     Abstraction to build docker images.
    """

    IMAGE_TAG = None  # type: six.text_type
    DOCKERFILE = None  # type: Path

    # add agent source code to the build context of the image
    COPY_AGENT_SOURCE = False  # type: bool

    def __init__(self):
        self._docker = None  # type: Optional

    @property
    def _docker_client(self):
        if self._docker is None:
            self._docker = docker.from_env()

        return self._docker

    @property
    def image_tag(self):  # type: () -> six.text_type
        return type(self).IMAGE_TAG

    @property
    def _copy_agent_source(self):  # type: () -> bool
        return type(self).COPY_AGENT_SOURCE

    @classmethod
    @abstractmethod
    def get_dockerfile_content(cls):  # type: () -> six.text_type
        """
        Get the content of the Dockerfile.
        """
        return cls.DOCKERFILE.read_text()

    def build(self, image_cache_path=None):
        """
        Build docker image.
        :param image_cache_path: import image from .tar files located in this directory, if exist.
        """

        if image_cache_path is not None:
            self.build_with_cache(Path(image_cache_path))
            return

        print("Build image: '{0}'".format(self.image_tag))
        build_context_path = create_tmp_directory(
            suffix="{0}-build-context".format(self.image_tag)
        )

        dockerfile_path = build_context_path / "Dockerfile"
        dockerfile_path.write_text(self.get_dockerfile_content())
        if self._copy_agent_source:
            agent_source_path = build_context_path / "agent_source"
            _copy_agent_source(agent_source_path)

        _, output_gen = self._docker_client.images.build(
            tag=self.image_tag,
            path=six.text_type(build_context_path),
            dockerfile=six.text_type(dockerfile_path),
            rm=True,
        )

        for chunk in output_gen:
            print(chunk.get("stream", ""), end="")

    def build_with_cache(self, dir_path):  # type: (Path) -> None
        """
        Search for 'image.tar' file named in 'path', if it is found, restore image (docker load) from this file.
        If file is not found, build it, and save in 'path'.
        This is convenient to use for example with CI caches.
        :param dir_path: Path to the directory with cached image or where to save it.
        """

        image_file_path = dir_path / self.image_tag
        if not image_file_path.exists():
            print("Image file '{0}' does not exist. Build it.".format(image_file_path))
            self.build()
            print("Save image file to '{0}'.".format(image_file_path))
            self.save(image_file_path)
        else:
            print(
                "Image file '{0}' exists. Use it and skip the build.".format(
                    image_file_path
                )
            )
            self.load(image_file_path)

    def load(self, dir_path):  # type: (Path) -> None
        """
        'docker load' from file named 'image.tar in directory located in 'path'.
        """
        with dir_path.open("rb") as f:
            image = self._docker_client.images.load(f.read())[0]
            image.tag(self.image_tag)

    def save(self, dir_path):  # type: (Path) -> None
        """
        'docker save' image to file 'image.tar' in 'path' directory.
        """
        image = self._docker_client.images.list(name=self.image_tag)
        if image:
            if not dir_path.parent.exists():
                dir_path.parent.mkdir(parents=True, exist_ok=True)
            with dir_path.open("wb") as f:
                for chunk in image[0].save():
                    f.write(chunk)

            print("Image '{0}' saved.".format(self.image_tag))

    @classmethod
    def handle_command_line(cls):
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--dockerfile",
            action="store_true",
            help="Print dockerfile content of the image.",
        )

        args = parser.parse_args()

        if args.dockerfile is not None:
            print(cls.get_dockerfile_content())
