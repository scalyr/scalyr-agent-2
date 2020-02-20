from __future__ import unicode_literals
from __future__ import print_function

import os

import pytest
import docker
import six

from scalyr_agent.tests.smoke_tests.tools.utils import create_temp_dir_with_constant_name

from scalyr_agent.tests.smoke_tests.tools.package_builder import build_package_builder_image
from scalyr_agent.tests.smoke_tests.tools.rpm_image_builder import build_rpm_builder_image
from scalyr_agent.tests.smoke_tests.tools.utils import copy_agent_source

dockerfile = \
    """
FROM scalyr_test_agent_package_builder as package_builder
ADD ./agent_source /agent_source
WORKDIR /package
RUN python /agent_source/build_package.py rpm
FROM scalyr_test_agent_rpm_builder as rpm_base
ARG PYTHON_VERSION=python2
COPY --from=package_builder /package/scalyr-agent*.rpm /scalyr-agent.rpm
COPY --from=package_builder /agent_source /agent_source
RUN rpm -i scalyr-agent.rpm
RUN ln -s -f /usr/bin/$PYTHON_VERSION /usr/bin/python
WORKDIR /agent_source
CMD python -m pytest /agent_source/scalyr_agent/tests/smoke_tests/agent_standalone_smoke_test.py --config config.ini --runner-type PACKAGE

    """


def build_rpm_agent_image(image_tag, python_version, docker_client=None):
    build_context_path = create_temp_dir_with_constant_name(".scalyr_agent_test")
    agent_source_path = build_context_path / "agent_source"

    copy_agent_source(agent_source_path)
    dockerfile_path = build_context_path / "Dockerfile"
    dockerfile_path.write_text(dockerfile)

    docker_client = docker_client or docker.DockerClient()

    docker_client.images.build(
        tag=image_tag,
        path=six.text_type(build_context_path),
        dockerfile=six.text_type(dockerfile_path),
        buildargs={"PYTHON_VERSION": python_version},
        rm=True,
    )


@pytest.mark.usefixtures("agent_environment")
def test_rpm_agent(request):
    docker_client = docker.from_env()

    python_version = request.config.getoption("--package-python-version")
    build_package_builder_image("scalyr_test_agent_package_builder", docker_client=docker_client)
    build_rpm_builder_image("scalyr_test_agent_rpm_builder", docker_client=docker_client)

    rpm_agent_image_tag = "scalyr_test_agent_rpm_image_{}".format(python_version)
    build_rpm_agent_image(rpm_agent_image_tag, python_version, docker_client=docker_client)

    environment = dict(
        (env_name, os.environ[env_name])
        for env_name in [
            "SCALYR_API_KEY",
            "READ_API_KEY",
            "SCALYR_SERVER",
            "AGENT_HOST_NAME",
        ]
    )
    output = docker_client.containers.run(
        name="scalyr_test_agent_rpm_{}".format(python_version),
        image=rpm_agent_image_tag,
        environment=environment,
        detach=False,
        stdout=True,
        auto_remove=True
    )

    print(output)
