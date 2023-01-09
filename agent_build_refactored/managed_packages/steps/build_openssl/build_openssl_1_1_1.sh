set -e


mkdir /tmp/build-openssl_1_1_1
pushd /tmp/build-openssl_1_1_1
tar -xvf "${DOWNLOAD_BUILD_DEPENDENCIES}/openssl_1_1_1/openssl.tar.gz"
pushd "openssl-${OPENSSL_VERSION}"
./config
make -j "$(nproc)"
make DESTDIR="${STEP_OUTPUT_PATH}/openssl" install_sw
popd
popd