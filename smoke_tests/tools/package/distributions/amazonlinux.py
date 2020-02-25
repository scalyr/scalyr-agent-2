from __future__ import unicode_literals
from __future__ import print_function
from __future__ import absolute_import

from typing import Optional, Any

from smoke_tests.tools.package.base_builder import AgentImageBuilder
from smoke_tests.tools.package.distributions.fpm_package_builder import (
    fpm_package_builder_dockerfile,
)

import six

amazonlinux_dockerfile = """
{fpm_package_builder_dockerfile}
ADD ./agent_source /agent_source
WORKDIR /package
RUN python /agent_source/build_package.py rpm
FROM amazonlinux
RUN yum install -y initscripts {python_version}
RUN yum groupinstall -y 'Development Tools'
RUN yum install -y {python_version}-pip {python_version}-devel

COPY agent_source/dev-requirements.txt dev-requirements.txt
COPY agent_source/extra-requirements.txt extra-requirements.txt

RUN {python_version} -m pip install -r dev-requirements.txt
RUN {python_version} -m pip install -r extra-requirements.txt

COPY --from=fpm_package_builder /package/scalyr-agent*.rpm /scalyr-agent.rpm
COPY --from=fpm_package_builder /agent_source /agent_source

RUN rpm -i scalyr-agent.rpm
RUN ln -s -f /usr/bin/{python_version} /usr/bin/python
WORKDIR /agent_source
ENV PYTHONPATH=.:${{PYTHONPATH}}
    """


class AmazonLinuxSmokeImageBuilder(AgentImageBuilder):
    IMAGE_TAG = "scalyr_test_amazonlinux_smoke_image"
    COPY_AGENT_SOURCE = True
    PYTHON_VERSION = ""  # type: six.text_type

    @classmethod
    def get_dockerfile_content(cls):  # type: () -> six.text_type
        return amazonlinux_dockerfile.format(
            fpm_package_builder_dockerfile=fpm_package_builder_dockerfile,
            python_version=cls.PYTHON_VERSION,
        )
