FROM centos:7

ADD scalyr-agent-2-2.1.1-1.noarch.rpm scalyr-agent-2-2.1.1-1.noarch.rpm

ADD scalyr-agent-2-2.1.5-1.noarch.rpm scalyr-agent-2-2.1.5-1.noarch.rpm

RUN rpm -iv scalyr-agent-2-2.1.1-1.noarch.rpm

RUN rpm -iv scalyr-agent-2-2.1.5-1.noarch.rpm