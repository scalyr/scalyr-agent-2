#!/usr/bin/env bash

COMMIT_DATE=$(git show --quiet --date='format-local:%Y-%m-%d %H:%M:%S' --format="%cd" ${COMMIT_SHA1})
#export COMMIT_DATE=$COMMIT_DATE

docker run -it \
-e CODESPEED_URL="https://scalyr-agent-codespeed.herokuapp.com/" \
-e CODESPEED_AUTH="scalyr:scalyr7854" \
-e CODESPEED_PROJECT="scalyr-agent-2" \
-e CODESPEED_EXECUTABLE="Python 2.7 - k8s idle" \
-e CODESPEED_ENVIRONMENT="Circle CI Docker Executor Medium Size" \
-e CODESPEED_BRANCH="master" \
-e COMMIT_DATE="${COMMIT_DATE}" \
-e AGENT_CONFIG_FILE="benchmarks/configs/agent_no_monitored_logs.json" \
  agent_k8s




