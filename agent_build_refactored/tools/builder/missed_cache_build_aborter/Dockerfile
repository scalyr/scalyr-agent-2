# This is a special stage that has to fail when it is not reused from cache ad has to run from the beginning.
# By using this stage we can fail the build early when we do not want to build everything from the beginning.
FROM --platform=linux/amd64 essential_ubuntu_tools as cache_check
ARG ERROR_MESSAGE
RUN echo -n "Can not continue." >> /tmp/error_mgx.txt
RUN echo " ${ERROR_MESSAGE}" >> /tmp/error_mgx.txt

# When the curl command finishes with failure, that means we allow build without cache.
# If the curl command finishes successfully, that meant that this build is not meant to be run without cache.

# If build is supposed to be run from the beginning and without cache,
# the endpoint that is queried by the curl has to be unreachable.
# When we expect that build has to be fully reused from cache, we make this endpoint available for curl,
# so the next this instruction will fail if it's not cached.
ARG URL
RUN if curl -s "${URL}" > /dev/null; then cat /tmp/error_mgx.txt ; exit 1; fi
RUN mkdir -p /tmp/empty

FROM scratch as cache_check_dummy_files
COPY --from=cache_check /tmp/empty/. /