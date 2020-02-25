from __future__ import unicode_literals
from __future__ import print_function

from __future__ import absolute_import

import pytest
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
    image_cache_path = request.config.getoption("--package-image_cache-path")

    docker_client = docker.from_env()

    distribution_builder_class = get_agent_distribution_builder(
        package_distribution, package_python_version
    )
    builder = distribution_builder_class()
    if image_cache_path:
        builder.build_with_cache(Path(image_cache_path))
    else:
        builder.build()

    docker_client.containers.run(
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
        detach=False,
        stdout=True,
        auto_remove=True,
        command="python -m pytest smoke_tests/standalone_smoke_test.py "
        "--config config.ini --runner-type PACKAGE",
    )
