import logging
from typing import Type

import pytest

from agent_build.tools.common import check_call_with_log
from agent_build.package_builders import ContainerImageBuilder, DOCKER_IMAGE_PACKAGE_BUILDERS
from agent_build.tools.build_in_docker import LocalRegistryContainer



@pytest.fixture(scope="session")
def image_builder_cls(request) -> Type[ContainerImageBuilder]:
    image_builder_name = request.param
    return DOCKER_IMAGE_PACKAGE_BUILDERS[image_builder_name]


@pytest.fixture(scope="session")
def agent_image_registry_port():
    return 5050


@pytest.fixture(scope="session")
def image_name(image_builder_cls):
    return image_builder_cls.RESULT_IMAGE_NAMES[0]

@pytest.fixture(scope="session")
def image_user():
    return "test_user"

@pytest.fixture(scope="session")
def image_tag():
    return "latest"


@pytest.fixture(scope="session")
def full_image_name(image_name, image_user, image_tag):
    return f"{image_user}/{image_name}:{image_tag}"


@pytest.fixture(scope="session")
def agent_image(image_builder_cls, agent_image_registry_port, image_name, image_user, image_tag, full_image_name):
    # Run container with docker registry.
    logging.info("Run new local docker registry in container.")

    registry_host = f"localhost:{agent_image_registry_port}"

    registry_container = LocalRegistryContainer(
        name="agent_images_registry", registry_port=agent_image_registry_port
    )

    builder = image_builder_cls(
        registry=registry_host,
        tags=[image_tag],
        user=image_user,
        push=True,
    )

    full_image_name_with_registry = f"{registry_host}/{full_image_name}"

    with registry_container:
        builder.build()

        # Pull result image from registry and make image visible for the munikube cluster.
        check_call_with_log(["docker", "pull", full_image_name_with_registry])
        check_call_with_log(["docker", "tag", full_image_name_with_registry, full_image_name])

    yield

    # cleanup
    check_call_with_log(["docker", "image", "rm", full_image_name])








