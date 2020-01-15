#!/bin/bash

##################################################################
# Scalyr Agent smoketest
#   Checks out a test branch.
#   Builds an RPM and installs it (mimicking a user install).
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
#   TEST_BRANCH: git branch
#   PYTHON_VERSION: python version to run test as (2.4-2.6)
#   SCALYR_API_KEY: Write api key
#   READ_API_KEY: Read api key for querying
#   SCALYR_SERVER: scalyr server
#   MAX_WAIT: max secs to verify upload
#   CIRCLE_BUILD_NUM: unique circle ci build num
#
# Optional env vars:
#   TLS_REVERSE_PROXY:  (e.g. https://localhost:8080). If set, scalyr agent will use this proxy url
#
# Expects following positional args:
#   $1 : coverage_enabled (true or false)
##################################################################

coverage_enabled=$1

alias ll='ls -la'
PS1='\h:\w\$ '

FILES=/tmp

# Parse args

# Create work directory to checkout source code
mkdir -p /tmp/src && pushd /tmp/src
df -kh
if [[ ! -d "./scalyr-agent-2" ]]; then
    git clone https://github.com/scalyr/scalyr-agent-2.git
fi
cd scalyr-agent-2
git checkout $TEST_BRANCH


# Switch python version and set PATH.  Also symlink /usr/bin/python to Tcollector doesn't
# inadvertently use preinstalled 2.7
python_version_opt='--version'
SIMULATE_TLS12_FAILURE=false

echo "Input PYTHON_VERSION = $PYTHON_VERSION"
if [[ $PYTHON_VERSION == "2.4" ]]; then
    export PYENV_VERSION="2.4.1"
    python_version_opt='-V'
elif [[ $PYTHON_VERSION == "2.5" ]]; then
    export PYENV_VERSION="2.5.4"
elif [[ $PYTHON_VERSION == "2.6" ]]; then
    export PYENV_VERSION="2.6.9"
elif [[ $PYTHON_VERSION == "2.7" ]]; then
    export PYENV_VERSION="2.7.12"
elif [[ $PYTHON_VERSION == "2.6.tls12" ]]; then
    export PYENV_VERSION="2.6.9"
    SIMULATE_TLS12_FAILURE=true
elif [[ $PYTHON_VERSION == "2.7.tls12" ]]; then
    export PYENV_VERSION="2.7.12"
    SIMULATE_TLS12_FAILURE=true
fi


# Force an Exception when HTTPSConnectionWithTimeoutAndVerification is used
if [[ $SIMULATE_TLS12_FAILURE == "true" ]]; then
    perl -pi -e 's/# SIMULATE_TLS12_FAILURE //g' scalyr_agent/connection.py
fi


# Make sure /usr/local/bin/fpm is runnable
export PATH=/usr/local/bin:$PATH

# Build RPM with python 2.7
echo ""
echo "Using python 2.7 to build rpm"
SAVED_PYENV_VERSION=$PYENV_VERSION
source ~/.bashrc && pyenv shell 2.7.12 && pyenv version
echo "Building agent RPM."
python build_package.py rpm
RPMFILE=`ls scalyr-agent*.rpm`
sudo -E rpm -i $RPMFILE

echo ""
echo "Switching to python $SAVED_PYENV_VERSION for smoke test"
source ~/.bashrc && pyenv shell $SAVED_PYENV_VERSION && pyenv version

# Make sure system python is the same as test version (for tcollector)
pythonbin=$(which python)
echo "pythonbin == $pythonbin"
sudo ln -sf ${pythonbin} /usr/bin/python
ls -la /usr/bin/python

# Setup the agent config (files must be owned by root as agent runs as root)
sudo /bin/cp -f $FILES/override_files/agent.json /etc/scalyr-agent-2/agent.json
sudo perl -pi.bak -e "s{CIRCLE_BUILD_NUM}{$CIRCLE_BUILD_NUM}" /etc/scalyr-agent-2/agent.json
echo "Overriding contents of: /etc/scalyr-agent-2/agent.json"
cat /etc/scalyr-agent-2/agent.json

echo "{api_key: \"$SCALYR_API_KEY\"}" > /tmp/api_key.json
sudo mv /tmp/api_key.json /etc/scalyr-agent-2/agent.d/api_key.json
if [[ -n ${TLS_REVERSE_PROXY} ]]; then
    echo "{scalyr_server: \"${TLS_REVERSE_PROXY}\", verify_server_certificate: false, allow_http: true, debug_init: true, debug_level: 5}" > /tmp/scalyr_server.json
else
    echo "{scalyr_server: \"${SCALYR_SERVER}\", debug_init: true, debug_level: 5}" > /tmp/scalyr_server.json
fi
sudo mv /tmp/scalyr_server.json /etc/scalyr-agent-2/agent.d/scalyr_server.json

# Start the agent.  Must use -E to inherit environment for proper python settings


if [[ $coverage_enabled == "true" ]]; then
  echo "Installing coverage"
  sudo -E python -m pip install coverage==4.5.4
  echo "Starting agent ..."
  # coverage tool needs a real file, not symlink.
  sudo -E python -m coverage run /usr/share/scalyr-agent-2/py/scalyr_agent/agent_main.py start
else
  echo "Starting agent ..."
  sudo -E scalyr-agent-2 start
fi

if [[ ! -f /var/log/scalyr-agent-2/agent.pid ]]; then
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
python $python_version_opt

print_header 'Python version used by tcollector (/usr/bin/python) is:'
/usr/bin/python $python_version_opt

print_header 'Python processes'
ps -ef | fgrep python

# Write to a test file after starting agent (otherwise logs are not included since considered too old)
# This file must match the log stanza in the overridden agent.json config
LOGFILE='/var/log/scalyr-agent-2/data.json'

# Execute the test in Python3 (independent of the agent python version)
# Fake the container name (i.e. don't actually need to run docker --name
print_header 'Querying Scalyr server to verify log upload'

# The smoketest python process requires python 3
sudo -E bash -c "source ~/.bashrc && pyenv shell 3.7.3 && python $FILES/smoketest.py \
ci-agent-standalone-${CIRCLE_BUILD_NUM} $MAX_WAIT \
--scalyr_server $SCALYR_SERVER --read_api_key $READ_API_KEY \
--python_version $PYTHON_VERSION --monitored_logfile $LOGFILE \
--debug true"

if [[ $coverage_enabled == "true" ]]; then
  # copy .coverage to root to make it easyer to find it outside of docker container.
  sudo cp .coverage /.coverage
fi
