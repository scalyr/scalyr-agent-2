FROM base as build
ARG COMMAND
ARG ROOT_DIR
COPY --from=root_dir / ${ROOT_DIR}
ARG CWD="/"
WORKDIR "${CWD}"
SHELL ["/bin/bash", "-c"]
RUN /bin/bash -c "$COMMAND"


FROM scratch
ARG OUTPUT_DIR
COPY --from=build ${OUTPUT_DIR}/. /