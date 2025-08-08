FROM extended_base as build_requirement_libs
RUN python3 -m pip install --upgrade setuptools --root /tmp/requrements_root
RUN cp -a /tmp/requrements_root/. /
ARG AGENT_REQUIREMENTS
RUN echo "${AGENT_REQUIREMENTS}" > /tmp/requirements.txt
RUN python3 -m pip install -r /tmp/requirements.txt --root /tmp/requrements_root
ARG TEST_REQUIREMENTS
RUN echo "${TEST_REQUIREMENTS}" > /tmp/test_requirments.txt
RUN python3 -m pip install -r /tmp/test_requirments.txt --root /tmp/test_requrements_root

FROM scratch as requirement_libs
COPY --from=build_requirement_libs /tmp/requrements_root /requirements
COPY --from=build_requirement_libs /tmp/test_requrements_root /test_requirements
