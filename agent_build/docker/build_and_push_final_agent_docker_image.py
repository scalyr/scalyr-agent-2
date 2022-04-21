import os
import pathlib as pl
import subprocess
import sys
import time

from agent_build.tools import common, constants


def main(
        base_image_registry_path: pl.Path,
        base_image_tag_suffix: str,
        build_type: str,
        output_path: pl.Path
):
    base_image_registry_port = 5003
    base_image_registry = common.LocalRegistryContainer(
        name="agent_base_registry",
        registry_port=base_image_registry_port,
        registry_data_path=base_image_registry_path
    )
    base_image_registry.start()

    base_image_full_name = f"localhost:{base_image_registry_port}/agent_base_image:{base_image_tag_suffix}"

    command_options = [
        "docker",
        "buildx",
        "build",
        "-t",
        "final",
        "-f",
        str(constants.SOURCE_ROOT / "agent_build/docker/Dockerfile"),
        "--build-arg",
        f"BASE_IMAGE=localhost:5000/{base_image_full_name}",
        "--build-arg",
        f"BASE_IMAGE_SUFFIX={base_image_tag_suffix}",
        "--build-arg",
        f"BUILD_TYPE={build_type}",
        "--build-arg",
        f"BASE_IMAGE={base_image_full_name}",
        str(constants.SOURCE_ROOT)
    ]

    subprocess.check_call([
        *command_options
    ])


if __name__ == '__main__':
    main(
        base_image_registry_path=pl.Path(sys.argv[1]) / "output_registry",
        base_image_tag_suffix=os.environ["BASE_IMAGE_TAG_SUFFIX"],
        build_type=os.environ["BUILD_TYPE"],
        output_path=pl.Path(os.environ["STEP_OUTPUT_PATH"])
    )