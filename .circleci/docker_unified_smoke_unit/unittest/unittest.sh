#!/usr/bin/env bash

# This script expects 2 environment variables
# 1) Two-digit PYTHON_VERSION (e.g. 2.4, 2.5, 2.6, 2.7)
# 2) TEST_BRANCH (git branch name)

# This file should be python-version agnostic
# export OLDPATH=$PATH;
# export PYTHON_PATH_PREFIX=`cat /tmp/python_path_prefix`
# export PATH=$PYTHON_PATH_PREFIX:$OLDPATH

# create work directory to checkout source code
export WORK_DIR=/work
mkdir -p $WORK_DIR/src && pushd $WORK_DIR/src
git clone https://github.com/scalyr/scalyr-agent-2.git

cd scalyr-agent-2
git checkout $TEST_BRANCH

# So that third party libs can be found
export PYTHONPATH=$WORK_DIR/src/scalyr-agent-2/scalyr_agent/third_party

# Finally, run unit tests
echo ""
echo "---------------------------------"
echo "Using python from" `which python`
echo "---------------------------------"
echo ""

if [[ $PYTHON_VERSION == "2.4" ]]; then
    PYENV_VERSION="2.4.1"
elif [[ $PYTHON_VERSION == "2.5" ]]; then
    PYENV_VERSION="2.5.4"
elif [[ $PYTHON_VERSION == "2.6" ]]; then
    PYENV_VERSION="2.6.9"
elif [[ $PYTHON_VERSION == "2.7" ]]; then
    PYENV_VERSION="2.7.12"
fi
source ~/.bashrc && pyenv shell ${PYENV_VERSION} && pyenv version && python run_tests.py
