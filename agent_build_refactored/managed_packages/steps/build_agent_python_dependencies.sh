set -e

source ~/.bashrc

# tar -xvf "${BUILD_PYTHON}/python.tar.gz" -C /

REQUIREMENTS_FILES_PATH="${SOURCE_ROOT}/agent_build/requirement-files"

/usr/libexec/scalyr-agent-2-python3 -c "import encodings"
/usr/libexec/scalyr-agent-2-python3 --version


AGENT_DEPENDENCIES_PATH="/tmp/agent_dependencies"
/usr/libexec/scalyr-agent-2-python3 -m pip install -v --force-reinstall --root "${AGENT_DEPENDENCIES_PATH}"  \
  -r "${REQUIREMENTS_FILES_PATH}/main-requirements.txt" \
  -r "${REQUIREMENTS_FILES_PATH}/compression-requirements.txt"


tar -czvf "${STEP_OUTPUT_PATH}/deeeeeepiiis.tar.gz" -C "${AGENT_DEPENDENCIES_PATH}" usr


function die() {
    message=$1
    >&2 echo "${message}"
    exit 1
}

SUBDIR_NAME="scalyr-agent-2-dependencies"

RESULT_ROOT="${STEP_OUTPUT_PATH}/agent_dependencies"

#mkdir -p "${AGENT_DEPENDENCIES_PATH}/usr/lib/lib/${SUBDIR_NAME}"
#ls ${AGENT_DEPENDENCIES_PATH}/usr/lib/lib
cp -a "${AGENT_DEPENDENCIES_PATH}/usr/lib/python${PYTHON_SHORT_VERSION}/."  "${AGENT_DEPENDENCIES_PATH}/usr/lib/${SUBDIR_NAME}/python${PYTHON_SHORT_VERSION}"
rm -r "${AGENT_DEPENDENCIES_PATH}/usr/lib/python${PYTHON_SHORT_VERSION}"


mkdir -p "${STEP_OUTPUT_PATH}/agent_dependencies/usr"
mv "${AGENT_DEPENDENCIES_PATH}/usr/lib" "${STEP_OUTPUT_PATH}/agent_dependencies/usr"

mkdir -p "${STEP_OUTPUT_PATH}/agent_dependencies/usr/libexec"
mv "${AGENT_DEPENDENCIES_PATH}/usr/bin" "${STEP_OUTPUT_PATH}/agent_dependencies/usr/libexec/${SUBDIR_NAME}"

REMAINING_FILES=$(find "${AGENT_DEPENDENCIES_PATH}" -type f)
test "$(echo -n "${REMAINING_FILES}" | wc -l)" = "0" || die "There are still files that are remaining non-copied to a result directory. Files: '${REMAINING_FILES}'"

