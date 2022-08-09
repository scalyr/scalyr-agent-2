

docker buildx build \
  -f "${SOURCE_ROOT}/agent_build/docker/final.Dockerfile" \
  --output "type=oci,dest=${RESULT_IMAGE_TARBALL}" \
  ${SOURCE_ROOT}