from __future__ import unicode_literals
from __future__ import print_function

import argparse

import docker

from scalyr_agent.tests.smoke_tests.tools.compat import Path
from scalyr_agent.__scalyr__ import get_package_root
from scalyr_agent.tests.smoke_tests.tools.utils import create_temp_dir_with_constant_name, copy_agent_source

import six

dockerfile = \
    """
FROM amazonlinux
RUN yum install -y initscripts python2 python3
RUN yum groupinstall -y 'Development Tools'
RUN yum install -y python2-pip python2-devel python3-pip python3-devel

COPY agent_source/dev-requirements.txt dev-requirements.txt
COPY agent_source/extra-requirements.txt extra-requirements.txt
RUN python2 -m pip install -r dev-requirements.txt
RUN python2 -m pip install -r extra-requirements.txt
RUN python3 -m pip install -r dev-requirements.txt
RUN python3 -m pip install -r extra-requirements.txt
    """


def build_rpm_builder_image(image_tag, docker_client=None):
    docker_client = docker_client or docker.DockerClient()

    build_context_path = create_temp_dir_with_constant_name(".scalyr_agent_test")
    agent_source_path = build_context_path / "agent_source"
    copy_agent_source(agent_source_path)

    dockerfile_path = build_context_path / "Dockerfile"
    dockerfile_path.write_text(dockerfile)

    docker_client.images.build(
        tag=image_tag,
        path=six.text_type(build_context_path),
        dockerfile=six.text_type(dockerfile_path),
        rm=True,
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("image_tag")
    parser.add_argument(
        "--dockerfile",
        action="store_true",
        default=False
    )

    args = parser.parse_args()
    if args.dockerfile:
        print(dockerfile)
    else:
        build_rpm_builder_image(args.image_tag)
