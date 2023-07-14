FROM toolset as prepare_source
ADD . /tmp/source
RUN rm -r /tmp/source/.git

ARG AGENT_SOURCE_TARBALL_FILENAME
RUN tar cfz /tmp/${AGENT_SOURCE_TARBALL_FILENAME} -C /tmp/source .

FROM scratch
ARG AGENT_SOURCE_TARBALL_FILENAME
COPY --from=prepare_source /tmp/source.tar.gz /${AGENT_SOURCE_TARBALL_FILENAME}



