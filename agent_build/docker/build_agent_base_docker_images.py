import os
import subprocess
import pathlib as pl

SOURCE_ROOT = pl.Path(os.environ["SOURCE_ROOT"])
STEP_OUTPUT_PATH = pl.Path(os.environ["STEP_OUTPUT_PATH"])
ARCHITECTURE_INFO_FILE_OUTPUT_PATH =  STEP_OUTPUT_PATH / "architecture_info.txt"
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
    result_image_name: str,
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
        "run",
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

    # Also write a special file to the output where we specify a platform of the result image,
    # it will be needed to the final image builder step.
    ARCHITECTURE_INFO_FILE_OUTPUT_PATH.write_text(platform_to_build)




    def build_image(
        build_test_version: bool
    ):
        # tag_suffix = base_image_tag_suffix
        # coverage_args = []
        # if build_test_version:
        #     tag_suffix = f"{tag_suffix}-testing"
        #     coverage_args = [
        #         "--build-arg",
        #         f"COVERAGE_VERSION={coverage_version}"
        #     ]

        result_image_final_name = f"localhost:5005/{result_image_name}"

        subprocess.check_call([
            "docker",
            "buildx",
            "build",
            "-t",
            result_image_final_name,
            "-f",
            f"{SOURCE_ROOT}/agent_build/docker/Dockerfile.base-debian",
            "--push",
            "--build-arg",
            f"BASE_IMAGE_SUFFIX={base_image_tag_suffix}",
            "--platform",
            platform_to_build,
            str(SOURCE_ROOT)
        ])

        result_image_testing_final_name = f"{result_image_final_name}-testing"
        subprocess.check_call([
            "docker",
            "buildx",
            "build",
            "-t",
            result_image_testing_final_name,
            "-f",
            f"{SOURCE_ROOT}/agent_build/docker/Dockerfile.base-testing",
            "--push",
            "--build-arg",
            f"BASE_IMAGE={result_image_final_name}",
            "--build-arg",
            f"COVERAGE_VERSION={coverage_version}",
            "--platform",
            platform_to_build,
            str(SOURCE_ROOT)
        ])

    build_image(True)


if __name__ == '__main__':
    main(
        platform_to_build=os.environ["PLATFORM_TO_BUILD"],
        result_image_name=os.environ["RESULT_IMAGE_NAME"],
        base_image_tag_suffix=os.environ["BASE_IMAGE_TAG_SUFFIX"],
        coverage_version=os.environ["COVERAGE_VERSION"]
    )