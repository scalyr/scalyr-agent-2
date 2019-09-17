#!/bin/bash

##################################################################
# Scalyr Agent standalone release smoketest
#
#   Simulates customer install of a provided release artifact (rpm, deb, tarball)
#   Artifact may be locally built file or public/published version.
#
# Behavior:
#   Runs a standalone smoketest
#   Starts the agent, configured to watch a designated local file.
#   Runs the standalone-agent smoketest, a python process that comprises:
#     uploader: writes text into the designated local file
#     verifier: queries scalyr backend to verify that the agent has
#               correctly uploaded the designated local file.
#
# Expects /tmp to contain smoketest.py and the override agent config files
#
# Usage: <this_script>
# Expects the following env vars
#   ARTIFACT_FILE: Full path to artifact file to install locally (or if eq "PUBLISHED", will install the
#     latest published version via https://www.scalyr.com/install-agent.sh script.)
#   PYTHON_VERSION: python version to run test with
#   SCALYR_API_KEY: Write api key
#   READ_API_KEY: Read api key for querying
#   SCALYR_SERVER: scalyr server
#   MAX_WAIT: max secs to verify upload
#   CIRCLE_BUILD_NUM: arbitrary unique build number
#   AGENT_VERSION: agent release version (e.g. 2.0.51)
##################################################################

alias ll='ls -la'
PS1='\h:\w\$ '

# Validate inputs
function validate_envar() {
  envar="$1";
  if [[ -z ${!envar} ]]; then
    echo "Environment variable ${envar} must not be empty";
    exit 1;
  fi
}
for envar in ARTIFACT_FILE PYTHON_VERSION SCALYR_API_KEY READ_API_KEY SCALYR_SERVER MAX_WAIT CIRCLE_BUILD_NUM AGENT_VERSION; do
  validate_envar "$envar"
done


# Simulate customer install of artifact
echo "Artifact_file = \"$ARTIFACT_FILE\""
export SCALYR_AGENT_ETC_DIR=/etc/scalyr-agent-2
export SCALYR_AGENT_LOG_DIR=/var/log/scalyr-agent-2
if [[ $ARTIFACT_FILE =~ .*rpm ]]; then
  echo "Installing local yum artifact"
  yum install -y --nogpgcheck $ARTIFACT_FILE
  yum install -y scalyr-repo
  yum install -y scalyr-agent-2
elif [[ $ARTIFACT_FILE =~ .*deb ]]; then
  echo "Installing local debian artifact"
  apt-get install -y $ARTIFACT_FILE
  apt-get update
elif [[ $ARTIFACT_FILE == "PUBLISHED" ]]; then
  echo "Installing via published script (https://www.scalyr.com/install-agent.sh)"
  pushd /tmp && curl https://www.scalyr.com/install-agent.sh -o /tmp/install-agent.sh && sleep 3 && chmod 755 /tmp/install-agent.sh && \
  sudo /tmp/install-agent.sh --set-api-key $SCALYR_API_KEY
elif [[ $ARTIFACT_FILE =~ .*gz ]]; then
  pushd /usr/share
  tar --no-same-owner -zxf $ARTIFACT_FILE
  mv scalyr-agent-${AGENT_VERSION} scalyr-agent-2
  export PATH=/usr/share/scalyr-agent-2/bin:$PATH
  popd
  SCALYR_AGENT_ETC_DIR=/usr/share/scalyr-agent-2/config
  SCALYR_AGENT_LOG_DIR=/usr/share/scalyr-agent-2/log
fi

# Directory where smoketest.py is stored
FILES=/tmp

if [[ ! -f $SCALYR_AGENT_ETC_DIR/agent.json ]]; then
    find / -name scalyr_install.log
    cat $(find / -name scalyr_install.log)
    exit 1
fi

# Setup the agent config (files must be owned by root as agent runs as root)
/bin/cp -f $FILES/override_files/agent.json $SCALYR_AGENT_ETC_DIR/agent.json
perl -pi.bak -e "s{CIRCLE_BUILD_NUM}{$CIRCLE_BUILD_NUM}" $SCALYR_AGENT_ETC_DIR/agent.json
echo "Overriding contents of agent.json"
cat $SCALYR_AGENT_ETC_DIR/agent.json

echo "{api_key: \"$SCALYR_API_KEY\"}" > /tmp/api_key.json
mv /tmp/api_key.json $SCALYR_AGENT_ETC_DIR/agent.d/api_key.json
echo "{scalyr_server: \"${SCALYR_SERVER}\", debug_init: true, debug_level: 5}" > /tmp/scalyr_server.json
mv /tmp/scalyr_server.json $SCALYR_AGENT_ETC_DIR/agent.d/scalyr_server.json

echo "Starting agent ..."
scalyr-agent-2 start

if [[ ! -f $SCALYR_AGENT_LOG_DIR/agent.pid ]]; then
    exit 1
fi

function print_header() {
    header="$1";
    if [[ -n $header ]]; then
        echo "";
        echo "=======================================";
        echo $header;
        echo "=======================================";
    fi
}

# Display python version that tcollector lib uses
print_header 'Agent Python version:'
python --version

print_header 'Python version used by tcollector (/usr/bin/python) is:'
/usr/bin/python --version

print_header 'Python processes'
ps -ef | fgrep python

# Write to a test file after starting agent (otherwise logs are not included since considered too old)
# This file must match the log stanza in the overridden agent.json config
LOGFILE='/var/log/scalyr-agent-2/data.json'

# Execute the test in Python3 (independent of the agent python version)
# Fake the container name (i.e. don't actually need to run docker --name
print_header 'Querying Scalyr server to verify log upload'

# The smoketest python process requires python 3
python3 $FILES/smoketest.py \
ci-agent-standalone-${CIRCLE_BUILD_NUM} $MAX_WAIT \
--scalyr_server $SCALYR_SERVER --read_api_key $READ_API_KEY \
--python_version $PYTHON_VERSION --monitored_logfile $LOGFILE \
--debug true

