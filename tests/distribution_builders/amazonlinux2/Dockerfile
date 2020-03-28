{fpm_package_builder_dockerfile_rpm}

FROM amazonlinux:2
RUN yum install -y initscripts python2 python3 gcc
RUN yum install -y python2-pip python2-devel python3-pip python3-devel

COPY agent_source/dev-requirements.txt dev-requirements.txt

RUN python -m pip install -r dev-requirements.txt
RUN python3 -m pip install -r dev-requirements.txt

COPY --from=fpm_package_build /package/scalyr-agent*.rpm /scalyr-agent.rpm
COPY --from=fpm_package_build /second_package/scalyr-agent*.rpm /scalyr-agent-second.rpm
COPY --from=fpm_package_build /agent_source /agent_source

WORKDIR /
