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

import pytest  # type: ignore
import docker

from smoke_tests.tools.compat import Path
from smoke_tests.tools.package import get_agent_distribution_builder
from scalyr_agent import compat


def pytest_generate_tests(metafunc):
    if "package_distribution" in metafunc.fixturenames:
        metafunc.parametrize(
            "package_distribution", metafunc.config.getoption("--package-distribution")
        )
    if "package_python_version" in metafunc.fixturenames:
        metafunc.parametrize(
            "package_python_version",
            metafunc.config.getoption("--package-python-version"),
        )


@pytest.mark.usefixtures("agent_environment")
def test_agent_package_smoke(package_distribution, package_python_version, request):
    """
    Prepare docker container with needed distribution
    and run regular standalone test inside it (smoke_tests/standalone_smoke_test.py).
    """
    print("")
    image_cache_path = request.config.getoption("--package-image-cache-path")

    docker_client = docker.from_env()

    print(
        "Get docker image for '{0}' and '{1}'".format(
            package_distribution, package_python_version
        )
    )
    distribution_builder_class = get_agent_distribution_builder(
        package_distribution, package_python_version
    )

    builder = distribution_builder_class()
    print("Build image: '{0}'".format(distribution_builder_class.IMAGE_TAG))
    if image_cache_path:
        print("Skip build if image exists in cache.")
        builder.build_with_cache(Path(image_cache_path))
    else:
        builder.build()

    # clear containers with the same name.
    found_containers = docker_client.containers.list(
        all=True, filters={"name": distribution_builder_class.IMAGE_TAG}
    )
    if found_containers:
        for cont in found_containers:
            print("Remove old container: '{0}'".format(cont.name))
            cont.remove(force=True)

    print("Run container: '{0}'".format(distribution_builder_class.IMAGE_TAG))
    print("Smoke test for agent is started inside the container.")
    container = docker_client.containers.run(
        name=distribution_builder_class.IMAGE_TAG,
        image=distribution_builder_class.IMAGE_TAG,
        environment=dict(
            (env_name, compat.os_environ_unicode[env_name])
            for env_name in [
                "SCALYR_API_KEY",
                "READ_API_KEY",
                "SCALYR_SERVER",
                "AGENT_HOST_NAME",
            ]
        ),
        detach=True,
        stdout=True,
        # run regular standalone smoke test inside the container.
        command="python -m pytest smoke_tests/standalone_smoke_tests/standalone_smoke_test.py "
        "-s -vv --agent-installation-type PACKAGE_INSTALL",
    )

    stream = container.logs(stream=True)

    for line in stream:
        print(line.decode(), end="")

    exit_code = container.wait()

    # test for exit code.
    assert exit_code["StatusCode"] == 0
