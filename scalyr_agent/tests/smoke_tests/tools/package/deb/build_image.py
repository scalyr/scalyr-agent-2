from __future__ import unicode_literals
from __future__ import print_function

from ..base_builder import Builder, handle_command_line

import six

dockerfile = \
    """
FROM ubuntu:18.04
RUN apt update -y
RUN apt install -y python2.7 python3 build-essential
RUN apt install -y python-pip python2.7-dev python3-pip python3-dev

COPY agent_source/dev-requirements.txt dev-requirements.txt
COPY agent_source/extra-requirements.txt extra-requirements.txt

RUN python3 -m pip install -r dev-requirements.txt
RUN python3 -m pip install -r extra-requirements.txt

RUN python2 -m pip install -r dev-requirements.txt
RUN python2 -m pip install -r extra-requirements.txt
    """


class DebBaseDistributionImageBuilder(Builder):
    IMAGE_TAG = "scalyr_test_base_deb_distribution_image"

    def __init__(
            self,
            docker_client=None,
            skip_if_exists=False,
    ):
        super(DebBaseDistributionImageBuilder, self).__init__(
            docker_client=docker_client,
            skip_if_exists=skip_if_exists,
            copy_agent_source=True,
        )

    @property
    def dockerfile(self):  # type: () -> six.text_type
        return dockerfile


if __name__ == '__main__':
    handle_command_line(DebBaseDistributionImageBuilder)
