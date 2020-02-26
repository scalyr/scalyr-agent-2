from __future__ import unicode_literals
from __future__ import print_function

from __future__ import absolute_import
from smoke_tests.tools.package.base_builder import AgentImageBuilder
from smoke_tests.tools.package.distributions.fpm_package_builder import (
    fpm_package_builder_dockerfile,
)

import six

ubuntu_dockerfile = """
{fpm_package_builder_dockerfile}
ADD ./agent_source /agent_source
WORKDIR /package
RUN python /agent_source/build_package.py deb
FROM ubuntu:18.04
RUN apt update -y

RUN apt install -y python build-essential

RUN apt install -y {python_package_name} build-essential
RUN apt install -y {python_package_name}-pip {python_package_name}-dev

COPY agent_source/dev-requirements.txt dev-requirements.txt
COPY agent_source/extra-requirements.txt extra-requirements.txt

RUN {python_version} -m pip install -r dev-requirements.txt
RUN {python_version} -m pip install -r extra-requirements.txt

COPY --from=fpm_package_builder /package/scalyr-agent*.deb /scalyr-agent.deb
COPY --from=fpm_package_builder /agent_source /agent_source
RUN dpkg -i scalyr-agent.deb
RUN ln -s -f /usr/bin/{python_version} /usr/bin/python
WORKDIR /agent_source
# remove package source to be sure the it is started from installed package.
ENV PYTHONPATH=.:${{PYTHONPATH}}
    """


class UbuntuSmokeImageBuilder(AgentImageBuilder):
    COPY_AGENT_SOURCE = True
    PYTHON_VERSION = ""  # type: six.text_type

    @classmethod
    def get_dockerfile_content(cls):  # type: () -> six.text_type
        return ubuntu_dockerfile.format(
            fpm_package_builder_dockerfile=fpm_package_builder_dockerfile,
            python_package_name="python"
            if cls.PYTHON_VERSION == "python2"
            else cls.PYTHON_VERSION,
            python_version=cls.PYTHON_VERSION,
        )
