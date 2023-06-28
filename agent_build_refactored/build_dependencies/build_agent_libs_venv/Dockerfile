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

COPY --from=build_dev_requirements / /tmp/wheels

# Install requirements to venv.
#ENV LD_LIBRARY_PATH="${PYTHON_INSTALL_PREFIX}/lib/openssl/embedded/libs:${LD_LIBRARY_PATH}"
ENV LD_LIBRARY_PATH="${PYTHON_INSTALL_PREFIX}/lib:${LD_LIBRARY_PATH}"

RUN "${VENV_DIR}/bin/python3" -m pip install  --force-reinstall --no-index --find-links /tmp/wheels -v \
  -r /tmp/requirements.txt

#RUN ls -al "${VENV_DIR}/lib/python3.11/site-packages" && false

# Remove cache files.
RUN find "${VENV_DIR}" -name "__pycache__" -type d -prune -exec rm -r {} \;

# Copy result venv to result output.
RUN mkdir -p /tmp/venv${VENV_DIR}
RUN cp -a "${VENV_DIR}/." /tmp/venv${VENV_DIR}

FROM scratch
COPY --from=build /tmp/venv /