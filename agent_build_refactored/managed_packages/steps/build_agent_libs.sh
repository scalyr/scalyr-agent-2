# Copyright 2014-2022 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This script is meant to be executed by the instance of the 'agent_build_refactored.tools.runner.RunnerStep' class.
# Every RunnerStep provides common environment variables to its script:
#   SOURCE_ROOT: Path to the projects root.
#   STEP_OUTPUT_PATH: Path to the step's output directory.
#
# This script downloads and builds Python libraries that are required by the agent.
# it produces two directories:
#     - dev_libs - root for all project requirement libraries. Mainly supposed to be used in various build and testing
#         tools and images.
#     - agent_libs: root for the agent_libs package. It contains only libraries that are required by the agent.

set -e

source ~/.bashrc

# Copy python interpreter, which is built by the previous step.
cp -a "${BUILD_PYTHON}/python/." /

# First install Rust, in order to be able to build some of required libraries.
cd ~
export PATH="/usr/local/bin:/root/.cargo/bin:${PATH}"
export PKG_CONFIG_PATH="/usr/local/lib64/pkgconfig:${PKG_CONFIG_PATH}"
curl --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain "${RUST_VERSION}"
cargo install cargo-update -v

REQUIREMENTS_FILES_PATH="${SOURCE_ROOT}/agent_build/requirement-files"

#
# Build dev libs.
#
DEV_LIBS_BUILD_ROOT="/tmp/dev-libs"
#CFLAGS="-I/usr/include/${SUBDIR_NAME}/python${PYTHON_SHORT_VERSION}" \
#  /usr/libexec/scalyr-agent-2-python3 -m pip install --root "${DEV_LIBS_BUILD_ROOT}" -r "${SOURCE_ROOT}/dev-requirements.txt"

/usr/libexec/${SUBDIR_NAME}/scalyr-agent-2-python3 -m pip install --root "${DEV_LIBS_BUILD_ROOT}" -r "${SOURCE_ROOT}/dev-requirements.txt"

# Uncomment this in order to save dev libs files with original filesystem structure. May be useful for debugging.
# cp -a "${DEV_LIBS_BUILD_ROOT}" "${STEP_OUTPUT_PATH}/dev_libs_original"

DEV_LIBS_ROOT="${STEP_OUTPUT_PATH}/dev_libs"

# Also fix structure of the result filesystem, since pip also does not fully respect sub-directories and some files
# are located outside of them.
mkdir -p "${DEV_LIBS_ROOT}/usr/lib"
mv "${DEV_LIBS_BUILD_ROOT}/usr/lib/${SUBDIR_NAME}" "${DEV_LIBS_ROOT}/usr/lib"
cp -a "${DEV_LIBS_BUILD_ROOT}/usr/lib/python${PYTHON_SHORT_VERSION}"  "${DEV_LIBS_ROOT}/usr/lib/${SUBDIR_NAME}"
rm -r "${DEV_LIBS_BUILD_ROOT}/usr/lib/python${PYTHON_SHORT_VERSION}"

mkdir -p "${DEV_LIBS_ROOT}/usr/libexec"
mv "${DEV_LIBS_BUILD_ROOT}/usr/bin" "${DEV_LIBS_ROOT}/usr/libexec/${SUBDIR_NAME}"

function die() {
    message=$1
    >&2 echo "${message}"
    exit 1
}
# Check if there are any files that have been left uncopied from the build root.
REMAINING_DEV_FILES=$(find "${DEV_LIBS_BUILD_ROOT}" -type f)
test "$(echo -n "${REMAINING_DEV_FILES}" | wc -l)" = "0" || die "There are still files that are remaining non-copied to a result dev libs directory. Files: '${REMAINING_DEV_FILES}'"


#
# Build agent libs.
#
AGENT_LIBS_BUILD_ROOT="/tmp/agent-libs"
/usr/libexec/${SUBDIR_NAME}/scalyr-agent-2-python3 -m pip install -v --force-reinstall --root "${AGENT_LIBS_BUILD_ROOT}"  \
  -r "${REQUIREMENTS_FILES_PATH}/main-requirements.txt" \
  -r "${REQUIREMENTS_FILES_PATH}/compression-requirements.txt"

# Uncomment this in order to save agent libs files with original filesystem structure. May be useful for debugging.
# cp -a "${AGENT_LIBS_BUILD_ROOT}" "${STEP_OUTPUT_PATH}/agent_libs_original"

AGENT_LIBS_ROOT="${STEP_OUTPUT_PATH}/agent_libs"

# Also fix structure of the result filesystem, since pip also does not fully respect sub-directories and some files
# are located outside of them.
mkdir -p "${AGENT_LIBS_ROOT}/usr/lib"
mv "${AGENT_LIBS_BUILD_ROOT}/usr/lib/${SUBDIR_NAME}" "${AGENT_LIBS_ROOT}/usr/lib"
cp -a "${AGENT_LIBS_BUILD_ROOT}/usr/lib/python${PYTHON_SHORT_VERSION}"  "${AGENT_LIBS_ROOT}/usr/lib/${SUBDIR_NAME}"
rm -r "${AGENT_LIBS_BUILD_ROOT}/usr/lib/python${PYTHON_SHORT_VERSION}"

mkdir -p "${AGENT_LIBS_ROOT}/usr/libexec"
mv "${AGENT_LIBS_BUILD_ROOT}/usr/bin" "${AGENT_LIBS_ROOT}/usr/libexec/${SUBDIR_NAME}"

# Check if there are any files that have been left uncopied from the build root.
REMAINING_AGENT_FILES=$(find "${AGENT_LIBS_BUILD_ROOT}" -type f)
test "$(echo -n "${REMAINING_AGENT_FILES}" | wc -l)" = "0" || die "There are still files that are remaining non-copied to a result agent libs directory. Files: '${REMAINING_AGENT_FILES}'"




