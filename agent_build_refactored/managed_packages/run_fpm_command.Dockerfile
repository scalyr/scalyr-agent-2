FROM toolset as build
COPY --from=work_dir / /tmp/work_dir
ARG COMMAND
ARG OUTPUT_DIR
WORKDIR ${OUTPUT_DIR}

RUN /bin/bash -c "${COMMAND}"

FROM scratch
ARG OUTPUT_DIR
COPY --from=build "${OUTPUT_DIR}" /
