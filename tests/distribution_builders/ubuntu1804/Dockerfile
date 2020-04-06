FROM scalyr-agent-testings-fpm_package-builder as fpm_package_build

ADD ./agent_source /agent_source

RUN /agent_source/tests/distribution_builders/base/build_packages.sh deb

FROM scalyr-agent-testings-ubuntu1804-base

COPY --from=fpm_package_build /package/scalyr-agent*.deb /scalyr-agent.deb
COPY --from=fpm_package_build /second_package/scalyr-agent*.deb /scalyr-agent-second.deb
COPY --from=fpm_package_build /agent_source /agent_source

WORKDIR /
