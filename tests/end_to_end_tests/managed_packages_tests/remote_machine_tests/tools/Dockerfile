ARG REPO_TYPE

FROM toolset as build
RUN gpg2 --with-colons --fingerprint test | awk -F: '$1 == "pub" {{print $5;}}' > /tmp/sign_key_fingerprint.txt
RUN gpg2 \
    --armor  \
    --export  \
    $(cat /tmp/sign_key_fingerprint.txt) > /tmp/repo_public_key.gpg

COPY --from=packages / /tmp/packages

FROM build as build_apt_repo
RUN aptly repo create -distribution=scalyr scalyr
RUN aptly repo add scalyr /tmp/packages
RUN aptly publish -architectures=amd64,arm64,all -distribution=scalyr repo scalyr
RUN cp -r ~/.aptly/public /tmp/repo


FROM build as build_yum_repo
RUN mkdir -p /tmp/repo
RUN cp /tmp/packages/*.rpm /tmp/repo
RUN createrepo_c /tmp/repo
ARG METADATA_FILE_PATH=/tmp/repo/repodata/repomd.xml
RUN gpg2 \
    --local-user \
    $(cat /tmp/sign_key_fingerprint.txt) \
    --output "${METADATA_FILE_PATH}.asc" \
    --detach-sign \
    --armor "${METADATA_FILE_PATH}"


FROM build_${REPO_TYPE}_repo as build_repo

FROM scratch
COPY --from=build_repo /tmp/repo /repo
COPY --from=build  /tmp/repo_public_key.gpg /repo_public_key.gpg



