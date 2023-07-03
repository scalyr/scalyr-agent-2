FROM prepare_build_base_with_python as build

ARG PATH_SEP
ARG PYTHON_INSTALL_PREFIX
ARG PORTABLE_RUNNER_NAME

WORKDIR /tmp/source

ADD agent_build agent_build
ADD agent_build_refactored agent_build_refactored
ADD tests/end_to_end_tests tests/end_to_end_tests
ADD VERSION VERSION
ADD dev-requirements-new.txt dev-requirements-new.txt

RUN python3 -m PyInstaller \
    --onefile \
    --name ${PORTABLE_RUNNER_NAME} \
    --add-data tests/end_to_end_tests${PATH_SEP}tests/end_to_end_tests \
    --add-data agent_build${PATH_SEP}agent_build \
    --add-data agent_build_refactored${PATH_SEP}agent_build_refactored \
    --add-data VERSION${PATH_SEP}. \
    --add-data dev-requirements-new.txt${PATH_SEP}. \
    tests/end_to_end_tests/run_in_remote_machine/portable_pytest_runner/pytest_runer_main.py

FROM scratch
ARG PORTABLE_RUNNER_NAME
COPY --from=build /tmp/source/dist/${PORTABLE_RUNNER_NAME} /