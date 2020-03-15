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

if False:
    from typing import Optional

from abc import ABCMeta, abstractmethod

import six

from tests.smoke_tests.tools.utils import (
    create_temp_dir_with_constant_name,
    copy_agent_source as copy_source,
)
from tests.smoke_tests.tools.compat import Path


@six.add_metaclass(ABCMeta)
class AgentImageBuilder(object):
    """
     Abstraction to build docker images.
    """

    IMAGE_TAG = None  # type: six.text_type

    # add agent source code to the build context of the image
    COPY_AGENT_SOURCE = False  # type: bool

    def __init__(self):
        self._docker = None  # type: Optional

    @property
    def _docker_client(self):
        if self._docker is None:
            import docker

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
        pass

    def build(self):
        """
        Build docker image.
        """
        build_context_path = create_temp_dir_with_constant_name(".scalyr_agent_testing")

        dockerfile_path = build_context_path / "Dockerfile"
        dockerfile_path.write_text(self.get_dockerfile_content())
        if self._copy_agent_source:
            agent_source_path = build_context_path / "agent_source"
            copy_source(agent_source_path)

        self._docker_client.images.build(
            tag=self.image_tag,
            path=six.text_type(build_context_path),
            dockerfile=six.text_type(dockerfile_path),
            rm=True,
        )

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
