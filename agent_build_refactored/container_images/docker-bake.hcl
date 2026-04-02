variable "BASE_DISTRO" {
  default = "ubuntu"
}

variable "REQUIREMENTS_DIR" {
  default = "."
}

variable "AGENT_FILESYSTEM_DIR" {
  default = "."
}

target "ubuntu_runtime_base" {
  context = "base_images"
  dockerfile = "ubuntu.Dockerfile"
  target = "runtime_base"
  output = ["type=cacheonly"]
}

target "ubuntu_dependencies_builder_base" {
  context = "base_images"
  dockerfile = "ubuntu.Dockerfile"
  target = "dependencies_builder_base"
  output = ["type=cacheonly"]
}

target "requirements_libs" {
  context = "."
  dockerfile = "dependencies.Dockerfile"
  contexts = {
    base = "target:${BASE_DISTRO}_dependencies_builder_base"
    requirements = "${REQUIREMENTS_DIR}"
  }
  output = ["type=cacheonly"]
}

target "container_images" {
  context = "."
  dockerfile = "Dockerfile"
  contexts = {
    requirements_libs = "target:requirements_libs"
    agent_filesystem = "${AGENT_FILESYSTEM_DIR}"
    base = "target:${BASE_DISTRO}_runtime_base"
  }
}

target "container_images_docker_syslog" {
  inherits = ["container_images"]
  target = "final-docker-syslog"
}

target "container_images_docker_api" {
  inherits = ["container_images"]
  target = "final-docker-api"
}

target "container_images_docker_json" {
  inherits = ["container_images"]
  target = "final-docker-json"
}

target "container_images_k8s" {
  inherits = ["container_images"]
  target = "final-k8s"
}