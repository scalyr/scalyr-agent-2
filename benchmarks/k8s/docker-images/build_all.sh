SCRIPT_DIR=$(readlink -f "$(dirname "${BASH_SOURCE[0]}")")


docker build -t agent-benchmark/agent:2.7.17 -f "${SCRIPT_DIR}/Dockerfile.agent-2.7.17" "${SCRIPT_DIR}/../../.."
docker build -t agent-benchmark/metrics-capture -f "${SCRIPT_DIR}/Dockerfile.capture" "${SCRIPT_DIR}/../../.."
docker build -t agent-benchmark/log-writer -f "${SCRIPT_DIR}/Dockerfile.log_writer" "${SCRIPT_DIR}/../../.."


docker tag agent-benchmark/agent:2.7.17 137797084791.dkr.ecr.us-east-1.amazonaws.com/agent-benchmark/agent:2.7.17
docker tag agent-benchmark/log-writer:latest 137797084791.dkr.ecr.us-east-1.amazonaws.com/agent-benchmark/log-writer:latest
docker tag agent-benchmark/metrics-capture:latest 137797084791.dkr.ecr.us-east-1.amazonaws.com/agent-benchmark/metrics-capture:latest

#docker push 137797084791.dkr.ecr.us-east-1.amazonaws.com/agent-benchmark/agent:2.7.17
#docker push 137797084791.dkr.ecr.us-east-1.amazonaws.com/agent-benchmark/log-writer:latest
#docker push 137797084791.dkr.ecr.us-east-1.amazonaws.com/agent-benchmark/metrics-capture:latest