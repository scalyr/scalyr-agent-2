FROM python:2.7


ARG BRANCH="master"
ARG COMMIT_SHA1=""

ENV COMMIT_SHA1=$COMMIT_SHA1

ADD . /agent_source

WORKDIR /agent_source

RUN git reset --hard
RUN git checkout ${BRANCH}

RUN /bin/bash -c "mkdir -p ~/scalyr-agent-dev/{log,config,data}"

CMD python scalyr_agent/agent_main.py start --no-fork --no-change-user --config=/config/config.json