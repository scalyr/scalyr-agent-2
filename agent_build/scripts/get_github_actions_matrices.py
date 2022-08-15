import argparse
import json
import sys
import pathlib as pl

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(pl.Path(__file__).parent.parent.parent))


from agent_build.docker_image_builders import (
    DEBIAN_IMAGE_BUILDERS,
    ALPINE_IMAGE_BUILDERS,
    IMAGES_PYTHON_VERSION,
    DEBIAN_K8S_IMAGE_BUILDERS,
    ALPINE_K8S_IMAGE_BUILDERS,
    ALL_DOCKER_IMAGE_BUILDERS,
)
from tests.end_to_end_tests.container_image_tests.k8s_test.k8s_test import (
    PARAMS as K8S_TESTS_PARAMS,
    EXTENDED_PARAMS as K8S_EXTENDED_TEST_PARAMS,
)

DEFAULT_IMAGE_BUILDERS = DEBIAN_IMAGE_BUILDERS[:]

EXTENDED_IMAGE_BUILDERS = [*DEFAULT_IMAGE_BUILDERS, *ALPINE_IMAGE_BUILDERS]


def get_image_build_matrix(extended: bool):
    builders = EXTENDED_IMAGE_BUILDERS if extended else DEFAULT_IMAGE_BUILDERS

    matrix = {"include": []}

    for builder_cls in builders:
        matrix["include"].append(
            {
                "builder-name": builder_cls.get_name(),
                "distro-name": builder_cls.BASE_IMAGE_BUILDER_STEP.base_distro.name,
                "python-version": f"{IMAGES_PYTHON_VERSION}",
                "os": "ubuntu-20.04",
            }
        )

    print(json.dumps(matrix))


def get_k8s_image_test_matrix(extended: bool):
    params = K8S_EXTENDED_TEST_PARAMS if extended else K8S_TESTS_PARAMS
    matrix = {"include": []}

    for p in params:
        image_builder_name = p["image_builder_name"]
        image_builder_cls = ALL_DOCKER_IMAGE_BUILDERS[image_builder_name]
        kubernetes_version = p["kubernetes_version"]
        minikube_driver = p["minikube_driver"]
        container_runtime = p["container_runtime"]

        matrix["include"].append(
            {
                "pytest-params": f"{image_builder_name}-{kubernetes_version}-{minikube_driver}-{container_runtime}",
                "builder-name": image_builder_name,
                "distro-name": image_builder_cls.BASE_IMAGE_BUILDER_STEP.base_distro.name,
                "os": "ubuntu-20.04",
                "python-version": "3.8.13",
            }
        )

    print(json.dumps(matrix))


def main():
    parser = argparse.ArgumentParser()
    # subparsers = parser.add_subparsers(dest="command", required=True)

    parser.add_argument("matrix_name")

    parser.add_argument(
        "--extended",
        required=False,
        action="store_true"
    )

    args = parser.parse_args()

    if args.matrix_name == "image_build_matrix":
        get_image_build_matrix(extended=args.extended)
        exit(0)

    if args.matrix_name == "k8s_image_test_matrix":
        get_k8s_image_test_matrix(extended=args.extended)
        exit(0)

if __name__ == '__main__':
    main()
