FROM prepare_build_base_with_python as build
ARG REQUIREMENTS
RUN echo "${REQUIREMENTS}" > /tmp/requirements.txt

ARG SUBDIR_NAME="scalyr-agent-2"
ARG PYTHON_INSTALL_PREFIX
ARG VENV_DIR="/var/opt/${SUBDIR_NAME}/venv"
RUN "${PYTHON_INSTALL_PREFIX}/bin/python3" -m venv "${VENV_DIR}"

## Install version of pip that we need to venv
#RUN "${VENV_DIR}/bin/python3" -m pip install -v \
#  --cache-dir /tmp/pip_cache \
#  "pip==${PIP_VERSION}"

# Install requirements to venv.
"${VENV_DIR}/bin/python3" -m pip install -v \
  -r /tmp/requirements.txt

# Remove cache files.
find "${VENV_DIR}" -name "__pycache__" -type d -prune -exec rm -r {} \;

# Copy result venv to result output.
cp -a "${VENV_DIR}" /tmp/venv${VENV_DIR}

FROM scratch
COPY --from=build /tmp/venv /