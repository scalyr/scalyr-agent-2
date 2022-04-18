import os
import subprocess
import pathlib as pl

SOURCE_ROOT = pl.Path(os.environ["SOURCE_ROOT"])
STEP_OUTPUT_PATH = pl.Path(os.environ["STEP_OUTPUT_PATH"])
REGISTRY_OUTPUT_PATH = STEP_OUTPUT_PATH / "output_registry"

_CONTAINER_NAME = "agent_base_image_registry_step"
_BUILDX_BUILDER_NAME = "agent_image_buildx_builder"


def kill_registry_container():
    subprocess.check_call([
        "docker",
        "rm",
        "-f",
        _CONTAINER_NAME
    ])

def main(
    platform_to_build: str,
    base_image_tag_suffix: str,
    coverage_version: str
):
    # Prepare buildx builder, first check if there is already existing builder.
    builders_list_output = subprocess.check_output([
        "docker",
        "buildx",
        "ls"
    ]).decode().strip()

    # Builder is not found, create new one.
    if _BUILDX_BUILDER_NAME not in builders_list_output:
        subprocess.check_call([
            "docker",
            "buildx",
            "create",
            "--driver-opt=network=host",
            "--name",
            _BUILDX_BUILDER_NAME
        ])

    # Use needed builder.
    subprocess.check_call([
        "docker",
        "buildx",
        "use",
        _BUILDX_BUILDER_NAME
    ])

    # Clear previously created container, ix exists
    kill_registry_container()

    # Spin up local registry in container.
    subprocess.check_call([
        "docker",
        "run"
        "-d",
        "--rm",
        "-p",
        "5005:5000",
        "-v",
        f"{REGISTRY_OUTPUT_PATH}:/var/lib/registry",
        "--name",
        _CONTAINER_NAME,
        "registry:2"
    ])




    def build_image(
        build_test_version: bool
    ):
        tag_suffix = base_image_tag_suffix
        coverage_args = []
        if build_test_version:
            tag_suffix = f"{tag_suffix}-testing"
            coverage_args = [
                "--build-arg",
                f"COVERAGE_VERSION={coverage_version}"
            ]

        subprocess.check_call([
            "docker",
            "buildx",
            "-t",
            f"localhost:5005/agent_base_image:${tag_suffix}",
            "-f",
            f"${SOURCE_ROOT}/agent_build/docker/Dockerfile.base",
            "--push",
            "--build-arg",
            f"BASE_IMAGE_SUFFIX={base_image_tag_suffix}",
            *coverage_args,
            "--platform",
            platform_to_build,
            str(SOURCE_ROOT)
        ])

    build_image(False)
    build_image(True)


if __name__ == '__main__':
    main(
        platform_to_build=os.environ["PLATFORM_TO_BUILD"],
        base_image_tag_suffix=os.environ["BASE_IMAGE_SUFFIX"],
        coverage_version=os.environ["USE_COVERAGE_VERSION"]
    )