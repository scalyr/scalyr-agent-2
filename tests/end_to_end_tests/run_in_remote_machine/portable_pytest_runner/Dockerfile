FROM prepare_build_base_with_python as build

ARG PATH_SEP
ARG PYTHON_INSTALL_PREFIX
ARG PORTABLE_RUNNER_NAME

WORKDIR /tmp/source

ADD tests/end_to_end_tests/run_in_remote_machine/portable_pytest_runner/pytest_runer_main.py tests/end_to_end_tests/run_in_remote_machine/portable_pytest_runner/pytest_runer_main.py

RUN python3 -m PyInstaller \
    --onefile \
    --name ${PORTABLE_RUNNER_NAME} \
    tests/end_to_end_tests/run_in_remote_machine/portable_pytest_runner/pytest_runer_main.py

FROM scratch
ARG PORTABLE_RUNNER_NAME
COPY --from=build /tmp/source/dist/${PORTABLE_RUNNER_NAME} /