from __future__ import unicode_literals

from __future__ import absolute_import

if False:
    from typing import Type

import six

from .distributions.amazonlinux import AmazonLinuxSmokeImageBuilder
from .distributions.ubuntu import UbuntuSmokeImageBuilder
from .base_builder import AgentImageBuilder

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
    if distribution == AMAZONLINUX:

        class _AmazonLinuxSmokeImageBuilder(AmazonLinuxSmokeImageBuilder):
            PYTHON_VERSION = python_version
            IMAGE_TAG = "scalyr_agent_smoke_{0}_{1}".format(
                distribution, python_version
            )

        return _AmazonLinuxSmokeImageBuilder

    elif distribution == UBUNTU:

        class _UbuntuSmokeImageBuilder(UbuntuSmokeImageBuilder):
            PYTHON_VERSION = python_version
            IMAGE_TAG = "scalyr_agent_smoke_{0}_{1}".format(
                distribution, python_version
            )

        return _UbuntuSmokeImageBuilder

    else:
        raise IOError("Can not find such distribution: {0}".format(distribution))
