from __future__ import unicode_literals
from __future__ import print_function

from ..base_builder import Builder, handle_command_line

import six

dockerfile = \
    """
FROM amazonlinux
RUN yum install -y initscripts python2 python3
RUN yum groupinstall -y 'Development Tools'
RUN yum install -y python2-pip python2-devel python3-pip python3-devel

COPY agent_source/dev-requirements.txt dev-requirements.txt
COPY agent_source/extra-requirements.txt extra-requirements.txt

RUN python3 -m pip install -r dev-requirements.txt
RUN python3 -m pip install -r extra-requirements.txt

RUN python2 -m pip install -r dev-requirements.txt
RUN python2 -m pip install -r extra-requirements.txt
    """


class RpmBaseDistributionImageBuilder(Builder):
    IMAGE_TAG = "scalyr_test_base_rpm_distribution_image"

    def __init__(
            self,
            docker_client=None,
            skip_if_exists=False,
    ):
        super(RpmBaseDistributionImageBuilder, self).__init__(
            docker_client=docker_client,
            skip_if_exists=skip_if_exists,
            copy_agent_source=True,
        )

    @property
    def dockerfile(self):  # type: () -> six.text_type
        return dockerfile


if __name__ == '__main__':
    handle_command_line(RpmBaseDistributionImageBuilder)
