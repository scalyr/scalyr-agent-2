import argparse
import pathlib as pl
import shutil
import subprocess
from typing import List

from agent_build_refactored.tools.constants import SOURCE_ROOT
from agent_build_refactored.tools.runner import Runner, RunnerStep
from agent_build_refactored.containerized.image_builders import ALL_AGENT_IMAGE_BUILDERS


TEST_IMAGES_REQUIREMENTS_BUILDERS = {}


for builder_name, image_builder in ALL_AGENT_IMAGE_BUILDERS.items():
    class TestImageRequirementsBuilder(Runner):
        CLASS_NAME_ALIAS = f"{builder_name}_test_image_requirements_builder"
        ADD_TO_GLOBAL_RUNNER_COLLECTION = True

        @classmethod
        def get_all_required_steps(cls) -> List[RunnerStep]:
            venv_toolchains = image_builder.get_agent_libs_venv_toolchains()
            return [
                *[t.build_agent_libs_venv for t in venv_toolchains.values()]
            ]

        @property
        def test_image_build_context(self) -> pl.Path:
            return self.output_path / "test_image_build_context"

        def build(self):
            self.prepare_runer()

            venv_toolchains = image_builder.get_agent_libs_venv_toolchains()

            for architecture, toolchain in venv_toolchains.items():

                arch_dir = image_builder.get_platform_specific_dir_name(
                    architecture=architecture
                )
                venv_test_libs_dir = self.test_image_build_context / "venv_test_libs_root" / arch_dir
                venv_test_libs_dir.mkdir(parents=True)

                build_agent_libs_venv = toolchain.build_agent_libs_venv
                build_agent_libs_venv_output = build_agent_libs_venv.get_output_directory(work_dir=self.work_dir)
                shutil.copytree(
                    build_agent_libs_venv_output / "venv_test_libs_root",
                    venv_test_libs_dir,
                    dirs_exist_ok=True,
                    symlinks=True
                )


    TEST_IMAGES_REQUIREMENTS_BUILDERS[builder_name] = TestImageRequirementsBuilder


def build_test_image(
    image_builder_name: str,
    prod_image_name: str,
    dst_registry_host: str,
):
    # Build requirements for the test variant of the image.
    requirements_builder_cls = TEST_IMAGES_REQUIREMENTS_BUILDERS[image_builder_name]

    requirements_builder = requirements_builder_cls()

    requirements_builder.build()

    # Build test variant of the image and push it to the registry for test variant images.
    dockerfile_path = SOURCE_ROOT / "tests/end_to_end_tests/containerized_agent_tests/Dockerfile"

    platform_args = []

    image_builder_cls = ALL_AGENT_IMAGE_BUILDERS[image_builder_name]

    for architecture in image_builder_cls.SUPPORTED_ARCHITECTURES:
        platform_args.extend([
            "--platform",
            str(architecture.as_docker_platform.value)
        ])

    test_image_name = image_builder_cls.IMAGE_NAMES[0]

    full_test_image_name = f"{dst_registry_host}/{test_image_name}"

    subprocess.run(
        [
            "docker",
            "buildx",
            "build",
            "-f",
            str(dockerfile_path),
            "-t",
            full_test_image_name,
            *platform_args,
            "--build-context",
            f"prod_image=docker-image://{prod_image_name}",
            "--push",
            str(requirements_builder.test_image_build_context)
        ],
        check=True
    )

    return full_test_image_name


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--image-builder-name",
        required=True
    )
    parser.add_argument(
        "--prod-image-name",
        required=True
    )

    parser.add_argument(
        "--dst-registry-host",
        required=True
    )

    args = parser.parse_args()
    image_name = build_test_image(
        image_builder_name=args.image_builder_name,
        prod_image_name=args.prod_image_name,
        dst_registry_host=args.dst_rehistry_host
    )

    print(image_name)
