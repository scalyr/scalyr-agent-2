#!/usr/bin/env python
from __future__ import unicode_literals
from __future__ import print_function

import argparse

import docker

from ..base_builder import Builder, handle_command_line
from scalyr_agent.tests.smoke_tests.tools.utils import create_temp_dir_with_constant_name

import six

dockerfile = \
    """
FROM python:3.6

RUN apt update && apt install -y ruby ruby-dev rubygems rpm build-essential

RUN gem install --no-document fpm
    """


# def build_package_builder_image(image_tag, docker_client=None, skip_if_exists=False):
#     docker_client = docker_client or docker.from_env()
#
#     if skip_if_exists:
#         if docker_client.images.list(name=image_tag):
#             return
#
#     build_context_path = create_temp_dir_with_constant_name(".scalyr_agent_test")
#
#     dockerfile_path = build_context_path / "Dockerfile"
#     dockerfile_path.write_text(dockerfile)
#
#     docker_client.images.build(
#         tag=image_tag,
#         path=six.text_type(build_context_path),
#         dockerfile=six.text_type(dockerfile_path),
#         rm=True,
#     )


class DistributionPackageBuilder(Builder):
    IMAGE_TAG = "scalyr_test_distribution_package_builder"

    @property
    def dockerfile(self):  # type: () -> six.text_type
        return dockerfile


if __name__ == '__main__':
    handle_command_line(DistributionPackageBuilder)
    # parser = argparse.ArgumentParser()
    # parser.add_argument("image_tag")
    # parser.add_argument(
    #     "--dockerfile",
    #     action="store_true",
    #     default=False
    # )
    # parser.add_argument(
    #     "--skip-if-exists",
    #     action="store_true",
    #     default=False
    # )
    #
    # args = parser.parse_args()
    # if args.dockerfile:
    #     print(dockerfile)
    # else:
    #     build_package_builder_image(args.image_tag, skip_if_exists=args.skip_if_exists)
