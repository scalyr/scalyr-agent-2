#!/usr/bin/env bash

set -e

SCRIPT_PATH="${0}"

REGISTRY="docker.io"

IMAGE_NAMES="%{{ REPLACE_IMAGE_NAMES }}%"
TAG_SUFFIXES="%{{ REPLACE_IMAGE_TAG_SUFFIXES }}%"
BASE_DISTRO="%{{ REPLACE_BASE_DISTRO }}%"
IMAGE_TYPE="%{{ REPLACE_IMAGE_TYPE }}%"

USER_NAME=""
TAGS=""

function print_usage() {
cat <<EOF
Usage $0 [options] where options are:
    -h,--help            Display this help message."
    --registry           Hostname of the target registry. Default - '${REGISTRY}'
    --user-name          Name of the user in the registry.
    --image-names        A comma-separated list of the names for the published image/repository
                         inside the registry. Default - '${IMAGE_NAMES}'
    --tags               A comma-separated list of the tags for the image.
    --tag-suffixes         A comma-separated list of suffixes that is applied to all tags.
                          Default - '${TAG_SUFFIXES}'
                         For example if tag is '2.1.1' and  suffix is 'alpine' then final
                         tag of a published image has to be '2.1.1-alpine'

EOF
}

# Handle the options
while (( $# > 0)); do
  case "$1" in

    -h|--help)
      print_usage;
      exit 0;;

    --registry)
      REGISTRY="$2";
      shift
      shift;;

    --user-name)
      USER_NAME="$2";
      shift
      shift;;

    --image-names)
      IMAGE_NAMES="$2";
      shift
      shift;;

    --tags)
      TAGS="$2";
      shift
      shift;;

    --tag-suffixes)
      TAG_SUFFIXES="$2";
      shift
      shift;;

    *)
      echo "Unrecognized option: $1";
      exit 1;
      break;;
  esac
done

if [ -z "${TAGS}" ]; then
  echo -e "The --tags option must be specified"
  exit 1
fi

# Split the comma-separated lists in the two environment variables into bash arrays.
IFS=',' read -r -a IMAGE_NAMES_LIST <<< "$IMAGE_NAMES"
IFS=',' read -r -a TAGS_LIST <<< "$TAGS"
IFS=',' read -r -a TAG_SUFFIXES_LIST <<< "$TAG_SUFFIXES"

# Create a list of all images tags by taking the cross product of REPOS and TAGS.
IMAGE_BUILD_TAG_ARGS=()

FULL_IMAGE_NAMES=()

for image_name in "${IMAGE_NAMES_LIST[@]}"; do
  for tag in "${TAGS_LIST[@]}"; do
    for tag_suffix in "${TAG_SUFFIXES_LIST[@]}"; do
      full_image_name="${image_name}:${tag}${tag_suffix}"

      if [ -n "${USER_NAME}" ]; then
        full_image_name"${USER_NAME}/${full_image_name}"
      fi

      full_image_name="${REGISTRY}/${full_image_name}"
      FULL_IMAGE_NAMES+=("${full_image_name}")
      IMAGE_BUILD_TAG_ARGS+=("-t" "${full_image_name}")
    done
  done
done


PAYLOAD_LINE=$(grep -n -a "# __PAYLOAD_TARBALL_BEGINS__" "${SCRIPT_PATH}" | head -2 | tail -1 | cut -f1 -d:)


IMAGE_SOURCE_DIR="$(pwd)/agent_image"

function create_output_dir() {
    if [ -d "${IMAGE_SOURCE_DIR}" ]; then
      echo -e "Output directory ${IMAGE_SOURCE_DIR} already exists"
      exit 1
  fi
  mkdir -p "${IMAGE_SOURCE_DIR}"
}

function extract_payload() {
  create_output_dir
  tail -n "+$((PAYLOAD_LINE+1))" "${SCRIPT_PATH}" | tar xf - -C "${IMAGE_SOURCE_DIR}" --strip-components=1
}

extract_payload

docker buildx build \
  -f "${IMAGE_SOURCE_DIR}/Dockerfile" \
  --build-arg "BASE_DISTRO=${BASE_DISTRO}" \
  --build-arg "IMAGE_TYPE=${IMAGE_TYPE}" \
  "${IMAGE_BUILD_TAG_ARGS[@]}" \
  "--push" \
  "${IMAGE_SOURCE_DIR}/image_build_context"


for full_image_name in "${FULL_IMAGE_NAMES[@]}"; do
  echo "${full_image_name}"
done

exit 0
# This is a beginning of the embedded tarball with all needed content for the image that has to be build by this  script.
# __PAYLOAD_TARBALL_BEGINS__
