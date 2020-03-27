{fpm_package_builder_dockerfile}
ADD ./agent_source /agent_source
WORKDIR /package
RUN python /agent_source/build_package.py rpm
# change version and build new package for agent upgrade test.
RUN echo "$(cat /agent_source/VERSION).1" > /agent_source/VERSION
WORKDIR /second_package
RUN python /agent_source/build_package.py rpm

FROM centos:6

# Needed for python-pip package
RUN yum update -y
RUN yum install -y epel-release

# Needed for python35 package (epel-release only contains 3.4 which we don't support)
RUN curl 'https://setup.ius.io/' -o setup-ius.sh
RUN sh setup-ius.sh

RUN yum update -y
RUN yum install -y initscripts gcc python2 python2-devel python-pip
RUN yum install -y python35u python35u-devel python35u-pip
RUN sudo ln -sf /usr/bin/python3.5 /usr/bin/python3

COPY agent_source/dev-requirements.txt dev-requirements.txt

RUN python2 -m pip install -r dev-requirements.txt
RUN python3 -m pip install -r dev-requirements.txt

COPY --from=fpm_package_build /package/scalyr-agent*.rpm /scalyr-agent.rpm
COPY --from=fpm_package_build /second_package/scalyr-agent*.rpm /scalyr-agent-second.rpm
COPY --from=fpm_package_build /agent_source /agent_source

WORKDIR /
