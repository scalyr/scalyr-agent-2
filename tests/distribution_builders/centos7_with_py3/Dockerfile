FROM scalyr-agent-testings-fpm_package-builder as fpm_package_build

ADD ./agent_source /agent_source

RUN /agent_source/tests/distribution_builders/base/build_packages.sh rpm

FROM scalyr-agent-testings-centos7-with-py3-base

COPY --from=fpm_package_build /package/scalyr-agent*.rpm /scalyr-agent.rpm
COPY --from=fpm_package_build /second_package/scalyr-agent*.rpm /scalyr-agent-second.rpm
COPY --from=fpm_package_build /agent_source /agent_source

WORKDIR /