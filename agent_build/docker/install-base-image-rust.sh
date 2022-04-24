# Install rust and cargo. It is needed to build some of the Python dependencies of the agent.
# NOTE: We don't use "-" at the end since context names which end just with "-" don't appear to
# be valid anymore with new Docker / buildx versions. See https://github.com/scalyr/scalyr-agent-2/pull/845
# for details

set -e

if [ "$TARGETVARIANT" != "v7" ]; then
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
  PATH="/root/.cargo/bin:${PATH}"
  rustup toolchain install nightly
  rustup default nightly
fi