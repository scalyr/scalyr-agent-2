#----------------------------------------------------------------------------------------
# Runs agent smoketest for docker:
#    - Assumes that the current scalyr-agent-2 root directory contains the test branch and that
#       the VERSION file can be overwritten (ie. the scalyr-agent-2 directory is a "throwaway" copy.
#    - Launch agent docker image
#    - Launch uploader docker image (writes lines to stdout)
#    - Launch verifier docker image (polls for liveness of agent and
#       uploader as well as verifies expected uploaded lines)
#
# Expects the following env vars:
#   SCALYR_API_KEY
#   SCALYR_SERVER
#   READ_API_KEY (Read api key. 'SCALYR_' prefix intentionally omitted to suppress in status -v)
#
# Expects following positional args:
#   $1 : smoketest image tag
#   $2 : 'syslog' or 'json' agent docker mode to test
#   $3 : max secs until test hard fails
#
# e.g. usage
#   smoketest_docker.sh scalyr/scalyr-agent-ci-smoketest:v1.1 json 300
#----------------------------------------------------------------------------------------

# The following variables are needed
# Docker image in which runs smoketest python3 code
# smoketest_image="scalyr/scalyr-agent-ci-smoketest:v1.1"
smoketest_image=$1

# Chooses json or syslog docker test.  Incorporated into container name which is then used by
# Verifier to choose the appropriate code to execute).
# syslog_or_json="json"
syslog_or_json=$2

# Max seconds before the test hard fails
max_wait=$3

#----------------------------------------------------------------------------------------
# Everything below this script should be fully controlled by above variables
#----------------------------------------------------------------------------------------

# Smoketest code (built into smoketest image)
smoketest_script="/usr/bin/python3 /tmp/smoketest.py"

# Erase variables (to avoid subtle config bugs in development)
syslog_driver_option=""
syslog_driver_portmap=""
jsonlog_containers_mount=""
if [[ $syslog_or_json == "syslog" ]]; then
    syslog_driver_option="--log-driver=syslog --log-opt syslog-address=tcp://127.0.0.1:601"
    syslog_driver_portmap="-p 601:601"
else
    jsonlog_containers_mount="-v /var/lib/docker/containers:/var/lib/docker/containers"
fi

# container names for all test containers
# The suffixes MUST be one of (agent, uploader, verifier) to match verify_upload::DOCKER_CONTNAME_SUFFIXES
contname_agent="ci_agent_docker_${syslog_or_json}_agent"
contname_uploader="ci_agent_docker_${syslog_or_json}_uploader"
contname_verifier="ci_agent_docker_${syslog_or_json}_verifier"


# Kill leftover containers
function kill_and_delete_docker_test_containers() {
    for cont in $contname_agent $contname_uploader $contname_verifier
    do
        if [[ -n `docker ps | grep $cont` ]]; then
            docker kill $cont
        fi
        if [[ -n `docker ps -a | grep $cont` ]]; then
            docker rm $cont;
        fi
    done
}
kill_and_delete_docker_test_containers
echo `pwd`

# Build agent docker image packager with fake version
fakeversion=`cat VERSION`
fakeversion="${fakeversion}.ci"
echo $fakeversion > ./VERSION
echo "Building docker image"
python build_package.py docker_${syslog_or_json}_builder

# Extract and build agent docker image
./scalyr-docker-agent-${syslog_or_json}-${fakeversion} --extract-packages
agent_image="agent-ci/scalyr-agent-docker-${syslog_or_json}:${fakeversion}"
docker build -t ${agent_image} .


# Launch Agent container (which begins gathering stdout logs)
docker run -d --name ${contname_agent} \
-e SCALYR_API_KEY=${SCALYR_API_KEY} -e SCALYR_SERVER=${SCALYR_SERVER} \
-v /var/run/docker.sock:/var/scalyr/docker.sock \
${jsonlog_containers_mount} ${syslog_driver_portmap} \
${agent_image}

# Capture agent short container ID
short_cid_agent=$(docker ps --format "{{.ID}}" --filter "name=$contname_agent")
echo "Agent container ID == ${short_cid_agent}"

# Launch Uploader container (only writes to stdout, but needs to query Scalyr to verify agent liveness)
# You MUST provide scalyr server, api key and importantly, the short_cid_agent container ID for the agent-liveness
# query to work
docker run ${syslog_driver_option}  -d --name ${contname_uploader} ${smoketest_image} \
${smoketest_script} ${contname_uploader} ${max_wait} \
--mode uploader \
--scalyr_server ${SCALYR_SERVER} \
--read_api_key ${READ_API_KEY} \
--short_cid_agent ${short_cid_agent}

# Capture uploader short container ID
short_cid_uploader=$(docker ps --format "{{.ID}}" --filter "name=$contname_uploader")
echo "Uploader container ID == ${short_cid_uploader}"

# Launch synchronous Verifier image (writes to stdout and also queries Scalyr)
docker run ${syslog_driver_option} -it --name ${contname_verifier} ${smoketest_image} \
${smoketest_script} ${contname_verifier} ${max_wait} \
--mode verifier \
--scalyr_server ${SCALYR_SERVER} \
--read_api_key ${READ_API_KEY} \
--short_cid_agent ${short_cid_agent} \
--short_cid_uploader ${short_cid_uploader}


kill_and_delete_docker_test_containers

