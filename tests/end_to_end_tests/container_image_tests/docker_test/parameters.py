from agent_build.docker_image_builders import (
    DOCKER_DEFAULT_BUILDERS,
    DOCKER_ADDITIONAL_BUILDERS,
)

DEFAULT_DOCKER_TEST_PARAMS = []

for builder_cls in DOCKER_DEFAULT_BUILDERS:
    DEFAULT_DOCKER_TEST_PARAMS.append({"image_builder_name": builder_cls.get_name()})

ADDITIONAL_DOCKER_TEST_PARAMS = []
for builder_cls in DOCKER_ADDITIONAL_BUILDERS:
    ADDITIONAL_DOCKER_TEST_PARAMS.append({"image_builder_name": builder_cls.get_name()})

ALL_DOCKER_TEST_PARAMS = [*DEFAULT_DOCKER_TEST_PARAMS, *ADDITIONAL_DOCKER_TEST_PARAMS]
