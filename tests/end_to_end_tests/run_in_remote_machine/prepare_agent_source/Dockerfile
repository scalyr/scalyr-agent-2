FROM toolset as prepare_source
ADD . /tmp/source
RUN rm -r /tmp/source/.git
RUN tar cfz /tmp/source.tar.gz -C /tmp/source .

FROM scratch
ARG AGENT_SOURCE_TARBALL_FILENAME
COPY --from=prepare_source /tmp/source.tar.gz /${AGENT_SOURCE_TARBALL_FILENAME}



