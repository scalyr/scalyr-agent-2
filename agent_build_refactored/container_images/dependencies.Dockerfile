FROM base as build_requirement_libs
RUN python3 -m pip install --upgrade setuptools --root /tmp/requirements_root
COPY --from=requirements / /tmp/specs/

RUN ls /tmp/specs/
RUN python3 -m pip install -r /tmp/specs/requirements.txt --root /tmp/requirements_root
RUN python3 -m pip install -r /tmp/specs/test_requirements.txt --root /tmp/test_requirements_root

FROM scratch as requirement_libs
COPY --from=build_requirement_libs /tmp/requirements_root /requirements
COPY --from=build_requirement_libs /tmp/test_requirements_root /test_requirements
