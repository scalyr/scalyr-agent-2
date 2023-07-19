FROM prod_image as build
ARG REQUIREMENTS_FILE_CONTENT
RUN echo "${REQUIREMENTS_FILE_CONTENT}" > /tmp/requirements.txt
RUN python3 -m pip install -r /tmp/requirements.txt --root /tmp/root

FROM scratch
COPY --from=build /tmp/root /