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
import hashlib

if False:
    from typing import Optional
    from typing import List
    from typing import Type
    from typing import Dict
    from typing import Callable

from abc import ABCMeta

import six

from scalyr_agent.__scalyr__ import get_package_root
from tests.utils.common import create_tmp_directory
from tests.utils.compat import Path


def _copy_agent_source(src_path, dest_path):
    gitignore_path = src_path / ".gitignore"
    patterns = [
        p[:-1] if p.endswith("/") else p
        for p in gitignore_path.read_text().splitlines()
        if not p.startswith("#")
    ]
    shutil.copytree(
        six.text_type(src_path),
        six.text_type(dest_path),
        ignore=shutil.ignore_patterns(*patterns),
    )


@six.add_metaclass(ABCMeta)
class AgentImageBuilder(object):
    """
     Abstraction to build docker images.
    """

    IMAGE_TAG = None  # type: six.text_type
    DOCKERFILE = None  # type: Path
    REQUIRED_IMAGES = []  # type: List[Type[AgentImageBuilder]]

    REQUIRED_CHECKSUM_IMAGES = []  # type: List[Type[AgentImageBuilder]]

    # add agent source code to the build context of the image
    COPY_AGENT_SOURCE = False  # type: bool

    # Do not use image cache for this image builder even if 'build' method was called with 'image_cache_path' parameter.
    # Note. This flag does not affect images in requirements.
    IGNORE_CACHING = False

    # List of file paths which should be added to the build context and used when generating the
    # checksum used for image caching.
    # Any change to the included path will result in cache being invalidated.
    INCLUDE_PATHS = []  # type: List[Path]

    def __init__(self):
        self._docker = None  # type: Optional

        # dict with files which need to be copied to build_context.
        # New paths can be added by using 'add_to_build_context' method.
        self._things_copy_to_build_context = dict()  # type: Dict[Path, Dict]

        # copy agent course code if needed.
        if type(self).COPY_AGENT_SOURCE:
            root_path = Path(get_package_root()).parent
            self.add_to_build_context(
                root_path, "agent_source", custom_copy_function=_copy_agent_source
            )

        # the value of this attribute is the path to the file to be copied to the image build
        # context.
        for path in self.INCLUDE_PATHS:
            self.add_to_build_context(path, path.name)

    @property
    def _docker_client(self):
        if self._docker is None:
            self._docker = docker.from_env()

        return self._docker

    @property
    def image_tag(self):  # type: () -> six.text_type
        return type(self).IMAGE_TAG

    @property
    def _is_copy_agent_source(self):  # type: () -> bool
        return type(self).COPY_AGENT_SOURCE

    @classmethod
    def get_dockerfile_content(cls):  # type: () -> six.text_type
        """
        Get the content of the Dockerfile.
        """
        return cls.DOCKERFILE.read_text()

    def add_to_build_context(self, path, name, custom_copy_function=None):
        # type: (Path, six.text_type, Optional[Callable]) -> None
        """
        Add file or directory to image build context.
        :param path: path to file or directory.
        :param name: name if the file or directory after copying.
        It will be placed in the root of the  build context directory.
        :param custom_copy_function: Custom copy function. Can be used, for example, to filter files that not needed.
        :return:
        """
        self._things_copy_to_build_context[path] = {
            "name": name,
            "copy_function": custom_copy_function,
        }

    def _copy_to_build_context(self, context_path):  # type: (Path) -> None
        for path, info in self._things_copy_to_build_context.items():
            copy_function = info.get("copy_function")
            dest_path = context_path / info["name"]
            if copy_function is not None:
                copy_function(path, dest_path)
            else:
                if path.is_dir():
                    shutil.copytree(six.text_type(path), six.text_type(dest_path))
                else:
                    shutil.copy(six.text_type(path), six.text_type(dest_path))

    def _is_image_exists(self):
        try:
            self._docker_client.images.get(self.image_tag)
            return True
        except docker.errors.ImageNotFound:
            return False

    def build(self, image_cache_path=None, skip_requirements=False):
        """
        Build docker image.
        :param image_cache_path: import image from .tar files located in this directory, if exist.
        :param skip_requirements: Build only image for this builder and skip all required builders.
        """
        # if image caching is enabled and image exists we assume that image has already built in previous test cases.
        if image_cache_path is not None:
            if self._is_image_exists():
                print("Image '{0}' already exists. Skip build.".format(self.IMAGE_TAG))
                return

        if not skip_requirements:
            # build all required images.
            for required_image_builder_cls in type(self).REQUIRED_IMAGES:
                builder = required_image_builder_cls()
                builder.build(image_cache_path=image_cache_path)

        if not type(self).IGNORE_CACHING and image_cache_path is not None:
            self.build_with_cache(Path(image_cache_path))
            return

        print("Build image: '{0}'".format(self.image_tag))

        build_context_path = create_tmp_directory(
            suffix="{0}-build-context".format(self.image_tag)
        )

        dockerfile_path = build_context_path / "Dockerfile"
        dockerfile_path.write_text(self.get_dockerfile_content())
        self._copy_to_build_context(build_context_path)

        _, output_gen = self._docker_client.images.build(
            tag=self.image_tag,
            path=six.text_type(build_context_path),
            dockerfile=six.text_type(dockerfile_path),
            rm=True,
        )

        shutil.rmtree(six.text_type(build_context_path), ignore_errors=True)

        for chunk in output_gen:
            print(chunk.get("stream", ""), end="")

    def build_with_cache(
        self, dir_path, skip_if_exists=True
    ):  # type: (Path, bool) -> None
        """
        Search for 'image.tar' file named in 'path', if it is found, restore image (docker load) from this file.
        If file is not found, build it, and save in 'path'.
        This is convenient to use for example with CI caches.
        :param dir_path: Path to the directory with cached image or where to save it.
        :param skip_if_exists: Skip the build if set and image already exists.
        """
        # if image is loaded earlier - skip to avoid the multiple loading of the same image
        # if we build it multiple times.
        if skip_if_exists and self._is_image_exists():
            print("The image  '{0}' is already loaded.".format(self.image_tag))
            return

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
    def get_checksum(cls, hash_object=None):
        # type: (Optional[hashlib._Hash]) -> hashlib._Hash
        """
        Get sha265 checksum of the dockerfile and included files.
        Also, include checksums of all required builders.
        """

        if hash_object is None:
            hash_object = hashlib.sha256()

        for builder_cls in cls.REQUIRED_CHECKSUM_IMAGES:
            hash_object = builder_cls.get_checksum(hash_object=hash_object)

        if cls.IGNORE_CACHING:
            return hash_object

        dockerfile = cls.get_dockerfile_content()
        hash_object.update(dockerfile.encode("utf-8"))

        for path in cls.INCLUDE_PATHS:
            if path.is_dir():
                # TODO implement checksum calculation for directories.
                pass
            else:
                hash_object.update(path.read_bytes())

        return hash_object

    @classmethod
    def handle_command_line(cls):
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--dockerfile",
            action="store_true",
            help="Print dockerfile content of the image.",
        )

        parser.add_argument(
            "--checksum",
            action="store_true",
            help="Print base64 encoded sha256 checksum of the Dockerfile of this builder. "
            "Also, it counts checksum of all required builders.",
        )

        parser.add_argument(
            "--name",
            action="store_true",
            help="Get name of the image which is built by this builder.",
        )

        parser.add_argument(
            "--build-with-cache",
            type=six.text_type,
            help="Path to cache directory. If specified, firstly, the builder searches for serialized tar file of the image,"
            "If this file does not exist, builds it from scratch and saves there.",
        )

        args = parser.parse_args()

        if args.checksum:
            checksum_object = cls.get_checksum()

            base64_checksum = checksum_object.hexdigest()
            print(base64_checksum)
            exit(0)

        if args.name:
            print(cls.IMAGE_TAG)
            exit(0)

        if args.build_with_cache:
            builder = cls()
            builder.build_with_cache(Path(args.build_with_cache), skip_if_exists=False)
            exit(0)
