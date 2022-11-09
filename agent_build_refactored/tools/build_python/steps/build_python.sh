set -e

source ~/.bashrc

mkdir /tmp/build-python
pushd /tmp/build-python
curl -L "https://github.com/python/cpython/archive/refs/tags/v${PYTHON_VERSION}.tar.gz" > python.tar.gz
tar -xvf python.tar.gz
pushd "cpython-${PYTHON_VERSION}"
mkdir build
pushd build

SUBDIR_NAME="scalyr-agent-2-dependencies"

BIN_DIR="libexec"
LIB_DIR="lib"
DATA_ROOT_DIR="share"
INCLUDE_DIR="include"

../configure \
  CFLAGS="-I/usr/local/include -I/usr/local/include/ncurses" \
  LDFLAGS="-L/usr/local/lib -L/usr/local/lib64" \
  LD_LIBRARY_PATH="/usr/local/lib:/usr/local/lib64:${LD_LIBRARY_PATH}" \
	--enable-shared \
	--with-openssl="/usr/local" \
	--with-readline=edit \
	--prefix="${PYTHON_INSTALL_PREFIX}" \
	--with-ensurepip=install \
	--bindir="${PYTHON_INSTALL_PREFIX}/${BIN_DIR}/${SUBDIR_NAME}" \
	--datarootdir="${PYTHON_INSTALL_PREFIX}/${DATA_ROOT_DIR}/${SUBDIR_NAME}" \
	--includedir="${PYTHON_INSTALL_PREFIX}/${INCLUDE_DIR}/${SUBDIR_NAME}" \
	--with-platlibdir="${LIB_DIR}/${SUBDIR_NAME}"




make -j "$(nproc)"
#make test
make DESTDIR="/tmp/python" install
popd
popd
popd

tar -czvf "${STEP_OUTPUT_PATH}/python_ddddd.tar.gz" -C /tmp/python usr


BUILT_ROOT="/tmp/python${PYTHON_INSTALL_PREFIX}"

FINAL_PACKAGE_ROOT="/tmp/final${PYTHON_INSTALL_PREFIX}"

mkdir -p "${FINAL_PACKAGE_ROOT}/${BIN_DIR}"
mkdir -p "${FINAL_PACKAGE_ROOT}/${LIB_DIR}"
mkdir -p "${FINAL_PACKAGE_ROOT}/${DATA_ROOT_DIR}"
mkdir -p "${FINAL_PACKAGE_ROOT}/${INCLUDE_DIR}"

mv "${BUILT_ROOT}/${BIN_DIR}/${SUBDIR_NAME}" "${FINAL_PACKAGE_ROOT}/${BIN_DIR}/${SUBDIR_NAME}"
mv "${BUILT_ROOT}/${LIB_DIR}/${SUBDIR_NAME}" "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
mv "${BUILT_ROOT}/${INCLUDE_DIR}/${SUBDIR_NAME}" "${FINAL_PACKAGE_ROOT}/${INCLUDE_DIR}/${SUBDIR_NAME}"

cp -ar ${BUILT_ROOT}/bin/. "${FINAL_PACKAGE_ROOT}/${BIN_DIR}/${SUBDIR_NAME}"
cp -ar ${BUILT_ROOT}/libexec/. "${FINAL_PACKAGE_ROOT}/${BIN_DIR}/${SUBDIR_NAME}"
cp -ar ${BUILT_ROOT}/lib/. "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
cp -ar ${BUILT_ROOT}/share/. "${FINAL_PACKAGE_ROOT}/${DATA_ROOT_DIR}/${SUBDIR_NAME}"
cp -ar ${BUILT_ROOT}/include/. "${FINAL_PACKAGE_ROOT}/${INCLUDE_DIR}/${SUBDIR_NAME}"

rm -r ${BUILT_ROOT}/bin
rm -r ${BUILT_ROOT}/libexec
rm -r ${BUILT_ROOT}/lib
rm -r ${BUILT_ROOT}/share
rm -r ${BUILT_ROOT}/include


function die() {
    message=$1
    >&2 echo "${message}"
    exit 1
}

# Check that there's nothing left in the original install directory.
BUILT_ROOT_CONTENT=$(find "${BUILT_ROOT}")
test $( echo -n "${BUILT_ROOT_CONTENT}" | wc -l) = 0 || die "Some files are still remaining not copied to a final package folder. Files: ${BUILT_ROOT_CONTENT}"

# Check that everything is located inside special sub-directories and theres no any other files or directories which are
# outside of them.
BIN_CONTENT=$(ls ${FINAL_PACKAGE_ROOT}/${BIN_DIR})
LIB_CONTENT=$(ls ${FINAL_PACKAGE_ROOT}/${LIB_DIR})
DATA_ROOT_CONTENT=$(ls ${FINAL_PACKAGE_ROOT}/${DATA_ROOT_DIR})
INCLUDE_CONTENT=$(ls ${FINAL_PACKAGE_ROOT}/${INCLUDE_DIR})

test "${BIN_CONTENT}" = "${SUBDIR_NAME}" \
  || die "Installation's '${FINAL_PACKAGE_ROOT}/${BIN_DIR}' directory has to contain only 1 ${SUBDIR_NAME} directory. Actual content: ${BIN_CONTENT}"

test "${LIB_CONTENT}" = "${SUBDIR_NAME}" \
  || die "Installation's '${FINAL_PACKAGE_ROOT}/${LIB_DIR}' directory has to contain only 1 ${SUBDIR_NAME} directory. Actual content: ${LIB_CONTENT}"

test "${DATA_ROOT_CONTENT}" = "${SUBDIR_NAME}" \
  || die "Installation's '${FINAL_PACKAGE_ROOT}/${DATA_ROOT_DIR}' directory has to contain only 1 ${SUBDIR_NAME} directory. Actual content: ${DATA_ROOT_CONTENT}"

test "${INCLUDE_CONTENT}" = "${SUBDIR_NAME}" \
  || die "Installation's '${FINAL_PACKAGE_ROOT}/${INCLUDE_DIR}' directory has to contain only 1 ${SUBDIR_NAME} directory. Actual content: ${INCLUDE_CONTENT}"

short_python_version="${PYTHON_VERSION%.*}"
# Some files and libraries for sure won't be used after the installation, so we can delete them
# to reduce the size of the future package.
lib_python_dir="${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}/python${short_python_version}"
rm -r ${lib_python_dir}/config-3.*-*-linux-gnu
rm -r ${lib_python_dir}/lib2to3
rm -r ${lib_python_dir}/test
rm -r ${lib_python_dir}/tkinter
find ${lib_python_dir} -type f -name '*.py[co]' -delete -o -type d -name __pycache__ -exec rm -r {} \;


# Copy Python dependency shared libraries.
cp -a /usr/local/lib/libz.so* "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
cp -a /usr/local/lib/libbz2.so* "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
cp -a /usr/local/lib/libedit.so* "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
cp -a /usr/local/lib/libncurses.so* "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
cp -a /usr/local/lib/liblzma.so* "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
cp -a /usr/local/lib/libuuid.so* "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
cp -a /usr/local/lib/libgdbm.so* "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
cp -a /usr/local/lib/libgdbm_compat.so* "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
cp -a /usr/local/lib64/libffi.so* "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
cp -a /usr/local/lib64/libcrypto.so* "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"
cp -a /usr/local/lib64/libssl.so* "${FINAL_PACKAGE_ROOT}/${LIB_DIR}/${SUBDIR_NAME}"

# Copy wrapper for Python interpreter executable.
cp -a "${SOURCE_ROOT}/agent_build_refactored/tools/build_python/files/scalyr-agent-python" "${FINAL_PACKAGE_ROOT}/${BIN_DIR}/scalyr-agent-2-python3"

tar -czvf "${STEP_OUTPUT_PATH}/python.tar.gz" -C /tmp/final usr


cp -a "${FINAL_PACKAGE_ROOT}" /


CFLAGS="-I/usr/include/scalyr-agent-2-dependencies/python${PYTHON_SHORT_VERSION}" \
  /usr/libexec/scalyr-agent-2-python3 -m pip install --root /tmp/all-dependencies -r "${SOURCE_ROOT}/dev-requirements.txt"

tar -czvf "${STEP_OUTPUT_PATH}/deeeeeep.tar.gz" -C /tmp/all-dependencies usr


mv /tmp/all-dependencies/usr/lib /tmp/all-dependencies/usr/lib_tmp
mkdir /tmp/all-dependencies/usr/lib
mv /tmp/all-dependencies/usr/lib_tmp/* /tmp/all-dependencies/usr/lib
rm -r /tmp/all-dependencies/usr/lib_tmp

ls /tmp/all-dependencies/usr
cp -a /tmp/all-dependencies/usr/lib/python${PYTHON_SHORT_VERSION}/.  /tmp/all-dependencies/usr/lib/scalyr-agent-2-dependencies/python${PYTHON_SHORT_VERSION}
rm -r /tmp/all-dependencies/usr/lib/python${PYTHON_SHORT_VERSION}


ls /tmp/all-dependencies
tar -czvf "${STEP_OUTPUT_PATH}/all-dependencies.tar.gz" -C /tmp/all-dependencies usr


