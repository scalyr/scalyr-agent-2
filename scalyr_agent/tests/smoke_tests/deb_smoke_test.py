from __future__ import unicode_literals
from __future__ import print_function

import os

import pytest
import docker
import six


from .tools.package.base_builder import Builder
from .tools.package.distribution_package_builder.build_image import DistributionPackageBuilder
from .tools.package.deb.build_image import DebBaseDistributionImageBuilder

dockerfile = \
    """
FROM {package_builder_image} as package_builder
ADD ./agent_source /agent_source
WORKDIR /package
RUN python /agent_source/build_package.py deb
FROM {deb_base_image} as deb_base
COPY --from=package_builder /package/scalyr-agent*.deb /scalyr-agent.deb
COPY --from=package_builder /agent_source /agent_source
RUN dpkg -i scalyr-agent.deb
RUN ln -s -f /usr/bin/{python_version} /usr/bin/python
WORKDIR /agent_source
CMD python -m pytest /agent_source/scalyr_agent/tests/smoke_tests/standalone_smoke_test.py --config config.ini --runner-type PACKAGE
    """


class RpmDistributionImageBuilder(Builder):
    IMAGE_TAG = "scalyr_test_deb_distribution_image"

    def __init__(
            self,
            python_version,
            docker_client=None,
            skip_if_exists=False,
    ):
        super(RpmDistributionImageBuilder, self).__init__(
            docker_client=docker_client,
            skip_if_exists=skip_if_exists,
            copy_agent_source=True,
        )
        self._python_version = python_version

    @property
    def dockerfile(self):  # type: () -> six.text_type
        return dockerfile.format(
            python_version=self._python_version,
            package_builder_image=DistributionPackageBuilder.IMAGE_TAG,
            deb_base_image=DebBaseDistributionImageBuilder.IMAGE_TAG
        )


@pytest.mark.usefixtures("agent_environment")
def test_deb_agent(request):
    docker_client = docker.from_env()

    python_version = request.config.getoption("--package-python-version")
    skip_image_build = request.config.getoption("--package-skip-if-images-exist")

    if not skip_image_build:
        dist_package_builder = DistributionPackageBuilder(
            docker_client=docker_client,
            skip_if_exists=skip_image_build
        )
        dist_package_builder.build()

        deb_base_distr_builder = DebBaseDistributionImageBuilder(
            docker_client=docker_client,
            skip_if_exists=skip_image_build
        )

        deb_base_distr_builder.build()

    deb_distr_builder = RpmDistributionImageBuilder(
        python_version,
        docker_client=docker_client,
        skip_if_exists=skip_image_build
    )

    deb_distr_builder.build()

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
        name="{}_{}".format(deb_distr_builder.IMAGE_TAG, python_version),
        image=deb_distr_builder.IMAGE_TAG,
        environment=environment,
        detach=False,
        stdout=True,
        auto_remove=True
    )

    print(output)
