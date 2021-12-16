#!/usr/bin/env bash

#----------------------------------------------------------------------------------------
# Runs agent smoketest for k8s in Minikube:
#    - Assumes that the current scalyr-agent-2 root directory contains the test branch and that
#       the VERSION file can be overwritten (ie. the scalyr-agent-2 directory is a "throwaway" copy.
#    - Launch agent k8s pod
#    - Launch uploader pod (writes lines to stdout)
#    - Launch verifier pod (polls for liveness of agent and uploader as well as verifies expected uploaded lines)
#
# Build local k8s image from code and launch a DaemonSet with it
# - modifies production daemonset spec file
#
# Expects the following env vars:
#   SCALYR_API_KEY
#   SCALYR_SERVER
#   READ_API_KEY (Read api key. 'SCALYR_' prefix intentionally omitted to suppress in status -v)
#   CIRCLE_BUILD_NUM
#
# Expects following positional args:
#   $1 : smoketest image tag
#   $2 : max secs until test hard fails
#   $3 : flag indicating whether to delete pre-existing k8s objects
#
# e.g. usage
#   smoketest_k8s.sh scalyr/scalyr-agent-ci-smoketest:3 300
#----------------------------------------------------------------------------------------

# The following variables are needed
# Docker image in which runs smoketest python3 code
smoketest_image=$1

# Max seconds before the test hard fails
max_wait=$2

# Flag indicating whether to delete pre-existing k8s objects
delete_existing_objects=$3

# We don't have an easy way to update base test docker images which come bundled
# with the smoketest.py file
# (.circleci/docker_unified_smoke_unit/smoketest/smoketest.py ->
# /tmp/smoketest.py) so we simply download this file from the github before running the tests.
# That's not great, but it works.
FILES=/tmp
SMOKE_TESTS_SCRIPT_BRANCH=${CIRCLE_BRANCH:-"master"}
SMOKE_TESTS_SCRIPT_REPO=${CIRCLE_PROJECT_REPONAME:-"scalyr-agent-2"}

SMOKE_TESTS_SCRIPT_URL="https://raw.githubusercontent.com/scalyr/${SMOKE_TESTS_SCRIPT_REPO}/${SMOKE_TESTS_SCRIPT_BRANCH}/.circleci/docker_unified_smoke_unit/smoketest/smoketest.py"
DOWNLOAD_SMOKE_TESTS_SCRIPT_COMMAND="sudo curl -o ${FILES}/smoketest.py ${SMOKE_TESTS_SCRIPT_URL}"

smoketest_script="${DOWNLOAD_SMOKE_TESTS_SCRIPT_COMMAND} ; source ~/.bashrc && pyenv shell 3.7.3 && python3 /tmp/smoketest.py"

# container names for all test containers
# The suffixes MUST be one of (agent, uploader, verifier) to match verify_upload::DOCKER_CONTNAME_SUFFIXES
contname_agent="ci-agent-k8s-${CIRCLE_BUILD_NUM}-agent"
contname_uploader="ci-agent-k8s-${CIRCLE_BUILD_NUM}-uploader"
contname_verifier="ci-agent-k8s-${CIRCLE_BUILD_NUM}-verifier"


# Delete existing resources
if [[ "$delete_existing_objects" == "delete_existing_k8s_objs" ]]; then
    echo ""
    echo "=================================================="
    echo "Deleting existing k8s objects"
    echo "=================================================="
    kubectl delete deployment ${contname_verifier} || truepushd
    kubectl delete deployment ${contname_uploader} || true
    kubectl delete daemonset scalyr-agent-2 || true
    kubectl delete configmap scalyr-config || true
    kubectl delete secret scalyr-api-key || true
    kubectl delete -f https://raw.githubusercontent.com/scalyr/scalyr-agent-2/release/k8s/scalyr-service-account.yaml || true
fi

echo ""
echo "=================================================="
echo "Creating k8s objects"
echo "=================================================="
# Create service account
kubectl create -f https://raw.githubusercontent.com/scalyr/scalyr-agent-2/release/k8s/scalyr-service-account.yaml

# Define api key
kubectl create secret generic scalyr-api-key --from-literal=scalyr-api-key=${SCALYR_API_KEY}

# Create configmap
kubectl create configmap scalyr-config \
--from-literal=SCALYR_K8S_CLUSTER_NAME=ci-agent-k8s-${CIRCLE_BUILD_NUM} \
--from-literal=SCALYR_SERVER=${SCALYR_SERVER} \
--from-literal=SCALYR_EXTRA_CONFIG_DIR=/etc/scalyr-agent-2/agent-extra.d

# Create an extra configmap
cat <<'EOF' >./config.json
{
  "k8s_logs": [
    {
      "attributes": { "container_name": "${k8s_container_name}" }
    }
  ]
}
EOF
kubectl create configmap scalyr-extra-config --from-file=config.json

# The following line should be commented out for CircleCI, but it necessary for local debugging
# eval $(minikube docker-env)

echo ""
echo "=================================================="
echo "Building agent image"
echo "=================================================="
# Build local image (add .ci.k8s to version)
perl -pi.bak -e 's/\s*(\S+)/$1\.ci\.k8s/' VERSION

# Build image by specifying image type through build args.
docker build -t local_k8s_image -f Dockerfile --build-arg "BUILD_TYPE=k8s" --build-arg MODE=with-coverage .

python build_package.py k8s_builder --coverage
TARBALL=$(ls scalyr-k8s-agent-*)

TEMP_DIRECTORY=~/temp_directory
mkdir $TEMP_DIRECTORY
mv $TARBALL $TEMP_DIRECTORY

pushd $TEMP_DIRECTORY
./${TARBALL} --extract-packages
docker build -t local_k8s_image .

popd

echo ""
echo "=================================================="
echo "Customizing daemonset YAML & starting agent"
echo "=================================================="
# Create DaemonSet, referring to local image.  Launch agent.
# Use YAML from branch
cp .circleci/scalyr-agent-2-with-extra-config.yaml .
perl -pi.bak -e 's/image\:\s+(\S+)/image: local_k8s_image/' scalyr-agent-2-with-extra-config.yaml
perl -pi.bak -e 's/imagePullPolicy\:\s+(\S+)/imagePullPolicy: Never/' scalyr-agent-2-with-extra-config.yaml

kubectl create -f ./scalyr-agent-2-with-extra-config.yaml
# Capture agent pod
agent_hostname=$(kubectl get pods | fgrep scalyr-agent-2 | awk {'print $1'})
echo "Agent pod == ${agent_hostname}"

# Launch Uploader container (only writes to stdout, but needs to query Scalyr to verify agent liveness)
# You MUST provide scalyr server, api key and importantly, the agent_hostname container ID for the agent-liveness
# query to work (uploader container waits for agent to be alive before uploading data)
echo ""
echo "=================================================="
echo "Starting uploader"
echo "=================================================="
kubectl run ${contname_uploader} --image=${smoketest_image} -- \
bash -c "${smoketest_script} \
${contname_uploader} ${max_wait} \
--mode uploader \
--scalyr_server ${SCALYR_SERVER} \
--read_api_key ${READ_API_KEY} \
--agent_hostname ${agent_hostname}"

# Capture uploader pod
uploader_hostname=$(kubectl get pods | fgrep ${contname_uploader} | awk {'print $1'})
echo "Uploader pod == ${uploader_hostname}"

# Launch synchronous Verifier image (writes to stdout and also queries Scalyr)
# Like the Uploader, the Verifier also waits for agent to be alive before uploading data
echo ""
echo "=================================================="
echo "Starting verifier"
echo "=================================================="
kubectl run -it --restart=Never ${contname_verifier} --image=${smoketest_image} -- \
bash -c "${smoketest_script} \
${contname_verifier} ${max_wait} \
--mode verifier \
--scalyr_server ${SCALYR_SERVER} \
--read_api_key ${READ_API_KEY} \
--agent_hostname ${agent_hostname} \
--uploader_hostname ${uploader_hostname} \
--debug true"


echo "Stopping agent"
k8s_docker_id=$(docker ps | grep k8s_scalyr-agent_scalyr-agent-2 | awk {'print$1'})
docker stop ${k8s_docker_id}
echo "Agent stopped copying .coverage results."
docker cp ${k8s_docker_id}:/.coverage .
