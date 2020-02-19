from __future__ import unicode_literals

import io
import tempfile
import shutil

import docker
import six

from scalyr_agent.tests.smoke_tests.tools.compat import Path
from scalyr_agent.tests.smoke_tests.tools.utils import create_temp_dir_with_constant_name

from scalyr_agent.__scalyr__ import get_package_root

dockerfile_base = \
    """
FROM python:3.6

RUN apt update && apt install -y ruby ruby-dev rubygems rpm build-essential

RUN gem install --no-document fpm
    """

"""
# ADD ./scalyr_agent_package.rpm /scalyr_build
# 
# ADD /agent_source /agent_source
#
# RUN ln -s -f /usr/bin/$PYTHON_VERSION /usr/bin/python
# 
# RUN rpm -i scalyr_agent_package.rpm
"""


def copy_agent_source(dest_path):
    root_path = Path(get_package_root()).parent
    shutil.copytree(
        six.text_type(root_path),
        six.text_type(dest_path),
        ignore=shutil.ignore_patterns(
            "*.pyc",
            "__pycache__",
            "*.egg-info",
            ".tox",
            ".pytest*",
            ".mypy*",
            ".idea",
            ".git"
        ),
    )


docker_client = docker.DockerClient()

build_context_path = create_temp_dir_with_constant_name(".scalyr_agent_test")
agent_source_path = build_context_path / "agent_source"

#copy_agent_source(agent_source_path)

dockerfile_path = build_context_path / "Dockerfile"
dockerfile_path.write_text(dockerfile_base)

docker_client.images.build(
    tag="scalyr_test_agent_package_builder_image",
    path=six.text_type(build_context_path),
    dockerfile=six.text_type(dockerfile_path),
    rm=True,
)

rpm_base_dockerfile = \
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
build_context_path = create_temp_dir_with_constant_name(".scalyr_agent_test")
agent_source_path = build_context_path / "agent_source"

copy_agent_source(agent_source_path)
dockerfile_path = build_context_path / "Dockerfile"
dockerfile_path.write_text(rpm_base_dockerfile)

_, o = docker_client.images.build(
    tag="scalyr_test_agent_rpm_base_image",
    path=six.text_type(build_context_path),
    dockerfile=six.text_type(dockerfile_path),
    rm=True,
)

rpm_dockerfile = \
    """
FROM scalyr_test_agent_package_builder_image as package_builder
ADD ./agent_source /agent_source
WORKDIR /package
RUN python /agent_source/build_package.py rpm
FROM scalyr_test_agent_rpm_base_image as rpm_base
ARG PYTHON_VERSION=python2
COPY --from=package_builder /package/scalyr-agent*.rpm /scalyr-agent.rpm
COPY --from=package_builder /agent_source /agent_source
RUN rpm -i scalyr-agent.rpm
RUN ln -s -f /usr/bin/$PYTHON_VERSION /usr/bin/python
WORKDIR /agent_source
CMD python -m pytest /agent_source scalyr_agent/tests/smoke_tests/agent_standalone_smoke_test.py --config config.ini

    """

build_context_path = create_temp_dir_with_constant_name(".scalyr_agent_test")
agent_source_path = build_context_path / "agent_source"

copy_agent_source(agent_source_path)
dockerfile_path = build_context_path / "Dockerfile"
dockerfile_path.write_text(rpm_dockerfile)

import docker.errors
try:
    _, o = docker_client.images.build(
        tag="scalyr_test_agent_rpm_image",
        path=six.text_type(build_context_path),
        dockerfile=six.text_type(dockerfile_path),
        buildargs={"PYTHON_VERSION": "python3"},
        rm=True,
    )
except docker.errors.BuildError as e:
    ll = list(e.build_log)

a=10