{fpm_package_builder_dockerfile_rpm}

FROM centos:6

# Needed for python-pip package
RUN yum update -y
RUN yum install -y epel-release

RUN yum update -y
RUN yum install -y initscripts gcc
RUN yum install -y python2 python2-devel python-pip

COPY agent_source/py26-unit-tests-requirements.txt py26-unit-tests-requirements.txt

RUN pip install -r py26-unit-tests-requirements.txt

COPY --from=fpm_package_build /package/scalyr-agent*.rpm /scalyr-agent.rpm
COPY --from=fpm_package_build /second_package/scalyr-agent*.rpm /scalyr-agent-second.rpm
COPY --from=fpm_package_build /agent_source /agent_source

WORKDIR /
