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

# orjson is wheel is not available for armv7 + musl yet so we exclude it here. We can't exclude it
# with pip environment markers since they are not specific enough.
if [ "$TARGETVARIANT" = "v7" ] && [ "$BASE_IMAGE_SUFFIX" = "alpine" ]; then
  sed -i '/^orjson/d' agent_build/requirement-files/main-requirements.txt;
fi

# Right now we don't support lz4 on server side yet so we don't include this dependency since it doesn't offer pre built
# wheel and it substantially slows down base image build
sed -i '/^lz4/d' agent_build/requirement-files/compression-requirements.txt

# Workaround so we can use pre-built orjson wheel for musl. We need to pin pip to older version for
# manylinux2014 wheel format to work.
# See https://github.com/ijl/orjson/issues/8 for details.
# If we don't that and we include orjson and zstandard, we need rust chain and building the image
# will be very slow due to cross compilation in emulated environment (QEMU)
# TODO: Remove once orjson and zstandard musl wheel is available - https://github.com/pypa/auditwheel/issues/305#issuecomment-922251777
echo 'manylinux2014_compatible = True' > /usr/local/lib/python3.8/_manylinux.py

# Install agent dependencies.
pip3 install --upgrade pip
pip3 --no-cache-dir install --root /tmp/dependencies -r agent_build/requirement-files/docker-image-requirements.txt

# Clean up files which were installed to use manylinux2014 workaround
rm /usr/local/lib/python3.8/_manylinux.py