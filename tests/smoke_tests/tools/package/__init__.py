from __future__ import unicode_literals

from __future__ import absolute_import

if False:
    from typing import Type

import six

from tests.smoke_tests.tools.compat import Path
from tests.smoke_tests.tools.package.base_builder import AgentImageBuilder

AMAZONLINUX = "amazonlinux"
UBUNTU = "ubuntu"

ALL_DISTRIBUTION_NAMES = [AMAZONLINUX, UBUNTU]


def get_agent_distribution_builder(distribution, python_version):
    # type: (six.text_type, six.text_type) -> Type[AgentImageBuilder]
    """
    Find agent distribution docker image for smoke testing.
    :param distribution: distribution name on which agent package should be installed.
    Possible values are in the 'ALL_DISTRIBUTION_NAMES' constant.
    :param python_version: Version of the python interpreter in the distribution.
    """
    distribution = distribution.lower()

    dockerfiles_directory_path = Path(__file__).parent / "distribution_dockerfiles"

    fpm_builder_dockerfile_path = (
        dockerfiles_directory_path / "Dockerfile.fpm_package_builder"
    )

    fpm_package_builder_dockerfile_content = fpm_builder_dockerfile_path.read_text()

    if distribution == AMAZONLINUX:

        class AmazonLinuxSmokeImageBuilder(AgentImageBuilder):
            PYTHON_VERSION = python_version
            COPY_AGENT_SOURCE = True
            IMAGE_TAG = "scalyr_agent_smoke_{0}_{1}".format(
                distribution, python_version
            )

            @classmethod
            def get_dockerfile_content(cls):  # type: () -> six.text_type

                dockerfile_path = dockerfiles_directory_path / "Dockerfile.amazonlinux"
                dockerfile_content = dockerfile_path.read_text()

                return dockerfile_content.format(
                    fpm_package_builder_dockerfile=fpm_package_builder_dockerfile_content,
                    python_version=cls.PYTHON_VERSION,
                )

        return AmazonLinuxSmokeImageBuilder

    elif distribution == UBUNTU:

        class _UbuntuSmokeImageBuilder(AgentImageBuilder):
            PYTHON_VERSION = python_version
            COPY_AGENT_SOURCE = True
            IMAGE_TAG = "scalyr_agent_smoke_{0}_{1}".format(
                distribution, python_version
            )

            @classmethod
            def get_dockerfile_content(cls):  # type: () -> six.text_type

                dockerfile_path = dockerfiles_directory_path / "Dockerfile.ubuntu"
                dockerfile_content = dockerfile_path.read_text()

                return dockerfile_content.format(
                    fpm_package_builder_dockerfile=fpm_package_builder_dockerfile_content,
                    python_package_name="python"
                    if cls.PYTHON_VERSION == "python2"
                    else cls.PYTHON_VERSION,
                    python_version=cls.PYTHON_VERSION,
                )

        return _UbuntuSmokeImageBuilder

    else:
        raise IOError("Can not find such distribution: {0}".format(distribution))
