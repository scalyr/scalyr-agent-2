FROM prepare_build_base_with_python as build
ARG REQUIREMENTS
RUN echo "${REQUIREMENTS}" > /tmp/requirements.txt

ARG SUBDIR_NAME="scalyr-agent-2"
ARG PYTHON_INSTALL_PREFIX
ARG VENV_DIR="/var/opt/${SUBDIR_NAME}/venv"
RUN python3 -m venv "${VENV_DIR}"

#ENV LD_LIBRARY_PATH="${PYTHON_INSTALL_PREFIX}/lib:${LD_LIBRARY_PATH}"

COPY --from=build_dev_requirements / /tmp/wheels

RUN "${VENV_DIR}/bin/python3" -m pip install \
    --no-index \
    --find-links /tmp/wheels \
    -r /tmp/requirements.txt

#RUN ls -al "${VENV_DIR}/lib/python3.11/site-packages" && false

# Remove cache files.
RUN find "${VENV_DIR}" -name "__pycache__" -type d -prune -exec rm -r {} \;

# Copy result venv to result output.
RUN cp -a "${VENV_DIR}" /tmp/venv

FROM scratch
COPY --from=build /tmp/venv/. /