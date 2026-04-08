# A directory containing two requirements files:
# - requirements.txt: The python requirements file for scalyr-agent-2 package
# - test_requirements.txt : The python requirements file needed to run the scalyr-agent-2 tests
variable "REQUIREMENTS_DIR" {
  default = "."
}

# The directory containing all of the files (python source, config files, etc)
# required for the Scalyr Agent.
variable "AGENT_FILESYSTEM_DIR" {
  default = "."
}

# The base image to use when creating the image to actually run the
# Scalyr Agent. This is usually based on some distribution.
# This can be overridden on the command line to use different base images
target "runtime-base" {
  context = "base_images"
  dockerfile = "ubuntu.Dockerfile"
  target = "runtime-base"
  output = ["type=cacheonly"]
}

# The base image to use when building Scalyr Agent's dependencies. These
# dependencies are eventually copied over to the runtime image.
# This can be overridden on the command line to use different base images
target "dependencies-builder-base" {
  context = "base_images"
  dockerfile = "ubuntu.Dockerfile"
  target = "dependencies-builder-base"
  output = ["type=cacheonly"]
}

target "requirements-libs" {
  context = "."
  dockerfile = "dependencies.Dockerfile"
  contexts = {
    base = "target:dependencies-builder-base"
    requirements = "${REQUIREMENTS_DIR}"
  }
  output = ["type=cacheonly"]
}

# Base image for all of the different image-based builds, such as
# k8s, syslog, etc.
target "container-images" {
  context = "."
  dockerfile = "Dockerfile"
  contexts = {
    requirements-libs = "target:requirements-libs"
    agent-filesystem = "${AGENT_FILESYSTEM_DIR}"
    base = "target:runtime-base"
  }
}

target "container-images-docker-syslog" {
  inherits = ["container-images"]
  target = "final-docker-syslog"
}

target "container-images-docker-api" {
  inherits = ["container-images"]
  target = "final-docker-api"
}

target "container-images-docker-json" {
  inherits = ["container-images"]
  target = "final-docker-json"
}

target "container-images-k8s" {
  inherits = ["container-images"]
  target = "final-k8s"
}