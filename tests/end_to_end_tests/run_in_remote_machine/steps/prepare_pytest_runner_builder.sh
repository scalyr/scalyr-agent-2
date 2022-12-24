set -e

REQUIREMENT_DIR="${SOURCE_ROOT}/agent_build/requirement-files"

python3 -m pip install \
  pytest==7.2.0 \
  PyInstaller==5.7.0 \
  -r "${REQUIREMENT_DIR}/requests-requirements.txt"