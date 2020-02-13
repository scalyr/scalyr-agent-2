from typing import Optional
from pathlib import Path


import docker

from .utils import create_temp_dir

from scalyr_agent.__scalyr__ import get_package_root
import six


def build(docker_client, path, tag, **kwargs):
    """
    # type: (docker.DockerClient, six.text_type, six.text_type)
    :param docker_client:
    :param path:
    :param tag:
    :param kwargs:
    :return:
    """
    print(f"The '{tag}' image build started.")
    img, build_logs = docker_client.images.build(
        path=path, tag=f"{tag}", rm=True, **kwargs
    )
    output = "".join([log.get("stream", "") for log in build_logs])
    print(
        "========================================================\n",
        output,
        "========================================================\n",
    )
    print(f"The '{tag}' image build")


class AgentDockerImageBuilder:
    def __init__(self, docker_client=None): # type: (Optional[docker.DockerClient]) -> None

        self._docker = docker_client or docker.DockerClient()

        self._build_context_dir = create_temp_dir()
        self._build_context_dir_path = Path(self._build_context_dir.name)
        self._tag = None

    @property
    def dockefile(self):
        content = \
"""
FROM amazonlinux

RUN yum install -y initscripts $PYTHON_VERSION

ARG PYTHON_VERSION=python3

RUN ln -s -f /usr/bin/$PYTHON_VERSION /usr/bin/python

ADD ./agent_source /agent_source 
"""

    def _prepare_build_context(self):
        r = get_package_root()

        return

    def build(self):
        self._prepare_build_context()
        print("The '{}' image build started.")
        img, build_logs = self._docker.images.build(
            path=str(self._build_context_dir_path),
            tag="{}",
            rm=True,
            #**kwargs
        )
        output = "".join([log.get("stream", "") for log in build_logs])
        print(
            "========================================================\n",
            output,
            "========================================================\n",
        )
        print(f"The '{tag}' image build")


def create_package(package_type):
    from build_package import build_package

    pass


# def ae(self):
#     """Create agent rpm package by running container instantiated from 'scalyr_package_builder'"""
#
#     package_directory = create_temp_dir()
#     docker_client.containers.start(
#         "scalyr_agent_test_package_builder",
#         name="scalyr_package_builder",
#         mounts=[
#             docker.types.Mount("/agent_source", root_dir, type="bind"),
#             docker.types.Mount("/package_result", package_directory.name, type="bind"),
#         ],
#         working_dir="/package_result",
#         command="python /agent_source/build_package.py rpm",
#         auto_remove=True,
#     )
#     package_path = next(Path(package_directory.name).glob("*.rpm"))
#     new_package_path = package_path.parent / "scalyr_agent_package.rpm"
#     package_path.rename(new_package_path)
#
#     yield str(new_package_path)
#     package_directory.cleanup()
