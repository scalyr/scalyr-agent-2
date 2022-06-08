# This dockerfile just wraps specified docker image and adds dummy file '/docker'.
# This file is needed to verify if the step is realy executed in docker.
ARG BASE_IMAGE_NAME

FROM $BASE_IMAGE_NAME
RUN touch /docker