variable "BASE_DISTRO" {
  default = "ubuntu"
}

variable "REQUIREMENTS_DIR" {
  default = "."
}

variable "AGENT_FILESYSTEM_DIR" {
  default = "."
}

target "ubuntu-runtime-base" {
  context = "base_images"
  dockerfile = "ubuntu.Dockerfile"
  target = "runtime-base"
  output = ["type=cacheonly"]
}

target "ubuntu-dependencies-builder-base" {
  context = "base_images"
  dockerfile = "ubuntu.Dockerfile"
  target = "dependencies-builder-base"
  output = ["type=cacheonly"]
}

target "requirements-libs" {
  context = "."
  dockerfile = "dependencies.Dockerfile"
  contexts = {
    base = "target:${BASE_DISTRO}-dependencies-builder-base"
    requirements = "${REQUIREMENTS_DIR}"
  }
  output = ["type=cacheonly"]
}

target "container-images" {
  context = "."
  dockerfile = "Dockerfile"
  contexts = {
    requirements-libs = "target:requirements-libs"
    agent-filesystem = "${AGENT_FILESYSTEM_DIR}"
    base = "target:${BASE_DISTRO}-runtime-base"
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