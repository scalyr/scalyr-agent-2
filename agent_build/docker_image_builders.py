# Copyright 2014-2021 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
This module defines all possible packages of the Scalyr Agent and how they can be built.
"""
import collections
import concurrent.futures
import argparse
import dataclasses
import enum
import json
import logging
import pathlib as pl
import re
import tarfile
import shutil
import os
import time
from typing import List, Type, Dict, ClassVar

from agent_build.tools.runner import (
    Runner,
    ArtifactRunnerStep,
    RunnerStep,
    GitHubActionsSettings,
)
from agent_build.prepare_agent_filesystem import build_linux_lfs_agent_files, add_config
from agent_build.tools.constants import SOURCE_ROOT, DockerPlatform, DockerPlatformInfo
from agent_build.tools import (
    check_output_with_log,
    UniqueDict,
    LocalRegistryContainer,
    check_call_with_log,
)

log = logging.getLogger(__name__)

__PARENT_DIR__ = pl.Path(__file__).absolute().parent
__SOURCE_ROOT__ = __PARENT_DIR__.parent

IMAGES_PYTHON_VERSION = "3.8.13"

_AGENT_BUILD_PATH = SOURCE_ROOT / "agent_build"
_AGENT_REQUIREMENT_FILES_PATH = _AGENT_BUILD_PATH / "requirement-files"
_TEST_REQUIREMENTS_FILE_PATH = (
    _AGENT_REQUIREMENT_FILES_PATH / "testing-requirements.txt"
)

# Get version of the coverage lib for the test version of the images.
# Parse version from requirements file in order to be in sync with it.
TEST_IMAGE_COVERAGE_VERSION = re.search(
    r"coverage==([\d\.]+)", _TEST_REQUIREMENTS_FILE_PATH.read_text()
).group(1)


class ContainerImageBaseDistro(enum.Enum):
    """
    Enum type which represents different distribution types which can be base for our particular images.
    """

    DEBIAN = "debian"
    ALPINE = "alpine"

    @property
    def as_python_image_suffix(self):
        suffixes = {
            ContainerImageBaseDistro.DEBIAN: "slim",
            ContainerImageBaseDistro.ALPINE: "alpine",
        }
        return suffixes[self]


@dataclasses.dataclass
class BaseDistroSpec:
    name: str
    python_base_image: str


class BaseImagePlatformBuilderStep(ArtifactRunnerStep):
    """
    Runner step which builds one particular platform of the base image for the agent's final docker image.
    This step, as a result, produces tarball with base image for a particular platform/architecture of the final docker
    image. All such images will be used together to build base multi-arch image.
    """

    def __init__(
        self,
        base_distro: BaseDistroSpec,
        # python_base_image: str,
        # base_distro: ContainerImageBaseDistro,
        image_platform: DockerPlatformInfo,
        base_image_name_prefix: str,
    ):
        """
        :param python_base_image: Name of the base docker image with python.
        :param base_distro: Distro type of the base image, e.g. debian, alpine.
        :param image_platform: Target platform/architecture of the result base image.
        """

        # self.base_distro = base_distro
        # self.image_platform = image_platform
        #
        # platform_dashed_str = image_platform.to_dashed_str
        #
        # self.base_result_image_name_with_tag = (
        #     f"{base_image_name_prefix}:{platform_dashed_str}"
        # )
        # self.result_image_tarball_name = (
        #     f"{base_image_name_prefix }-{platform_dashed_str}.tar"
        # )

        name = f"{base_image_name_prefix}-{image_platform.to_dashed_str}"

        super(BaseImagePlatformBuilderStep, self).__init__(
            name=name,
            script_path="agent_build/docker/build_base_platform_image.sh",
            tracked_files_globs=[
                _AGENT_BUILD_PATH / "docker/base.Dockerfile",
                _AGENT_BUILD_PATH / "docker/install-base-dependencies.sh",
                _AGENT_BUILD_PATH / "docker/install-python-libs.sh",
                _AGENT_BUILD_PATH / "docker/install-python-libs-build-dependencies.sh",
                _AGENT_REQUIREMENT_FILES_PATH / "docker-image-requirements.txt",
                _AGENT_REQUIREMENT_FILES_PATH / "compression-requirements.txt",
                _AGENT_REQUIREMENT_FILES_PATH / "main-requirements.txt",
            ],
            environment_variables={
                "PYTHON_BASE_IMAGE": base_distro.python_base_image,
                "DISTRO_NAME": base_distro.name,
                "RESULT_IMAGE_TARBALL_NAME": f"{name}.tar",
                "PLATFORM": str(image_platform),
                "COVERAGE_VERSION": TEST_IMAGE_COVERAGE_VERSION,
            },
            github_actions_settings=GitHubActionsSettings(
                cacheable=True, pre_build_in_separate_job=True
            ),
        )


class BaseImageBuilderStep(ArtifactRunnerStep):
    def __init__(
        self,
        base_distro: BaseDistroSpec,
        supported_platforms: List[DockerPlatformInfo],
    ):
        self.base_image_name_prefix = f"agent-base-image-{base_distro.name}"

        required_steps = {}
        for plat in supported_platforms:
            # platform_step_name = f"{base_image_name_prefix}-{plat.to_dashed_str}"
            # result_image_name_tarball_name = f"{platform_step_name}.tar"
            platform_step = BaseImagePlatformBuilderStep(
                base_distro=base_distro,
                image_platform=plat,
                base_image_name_prefix=self.base_image_name_prefix,
            )

            required_step_env_var_name = (
                f"_BASE_PLATFORM_IMAGE_STEP_{platform_step.name}"
            )
            required_steps[required_step_env_var_name] = platform_step

        super(BaseImageBuilderStep, self).__init__(
            name=self.base_image_name_prefix,
            script_path="agent_build/docker/build_base_image.py",
            tracked_files_globs=["agent_build/tools/steps_libs/container.py"],
            required_steps=required_steps,
            environment_variables={
                "BASE_IMAGE_NAME_PREFIX": self.base_image_name_prefix,
            },
            github_actions_settings=GitHubActionsSettings(
                cacheable=True,
            ),
        )
        self.base_distro = base_distro

        # self.python_base_image = python_base_image
        # self.base_distro = base_distro
        # self.builx_builder_name = "agent_image_buildx_builder"
        # self._previous_buildx_builder_name = None

    def __post_init__(self):
        pass

    @property
    def result_agent_base_image_name(self) -> str:
        return


@dataclasses.dataclass
class AgentImageTypeSpec:
    name: str
    base_config_path: pl.Path
    result_image_name: str
    additional_config_paths: List[pl.Path] = None
    additional_result_image_names: List[str] = dataclasses.field(default_factory=list)
    # Name of the stage in the dockerfile which has to be picked for this particular image type.
    # Image types with specialized final docker images (for example k8s, docker-syslog) has to use their own
    # stage name, other has to use the 'common stage.'
    image_type_stage_name: str = "common"


class AgentImageFilesystemBuilder(Runner):
    def __init__(
        self,
        base_config_path: pl.Path,
        additional_config_paths: List[pl.Path] = None,
    ):

        super(AgentImageFilesystemBuilder, self).__init__()
        self.base_config_path = base_config_path
        self.additional_config_paths = additional_config_paths

    def build_filesystem_tarball(self, output_dir: str):
        """
        Build tarball with agent's filesystem.
        :param output_dir: Path to directory where result filesystem tarball is stored.
        """

        output_dir_path = pl.Path(output_dir)
        package_root_path = output_dir_path / "package_root"

        build_linux_lfs_agent_files(
            copy_agent_source=True,
            output_path=package_root_path,
        )

        add_config(
            base_config_source_path=self.base_config_path,
            output_path=package_root_path / "etc/scalyr-agent-2",
            additional_config_paths=self.additional_config_paths,
        )

        # Need to create some docker specific directories.
        pl.Path(package_root_path / "var/log/scalyr-agent-2/containers").mkdir()

        container_tarball_path = self.output_path / "scalyr-agent.tar.gz"

        # Do a manual walk over the contents of root so that we can use `addfile` to add the tarfile... which allows
        # us to reset the owner/group to root.  This might not be that portable to Windows, but for now, Docker is
        # mainly Posix.
        with tarfile.open(container_tarball_path, "w:gz") as container_tar:

            for root, dirs, files in os.walk(package_root_path):
                to_copy = []
                for name in dirs:
                    to_copy.append(os.path.join(root, name))
                for name in files:
                    to_copy.append(os.path.join(root, name))

                for x in to_copy:
                    file_entry = container_tar.gettarinfo(
                        x, arcname=str(pl.Path(x).relative_to(package_root_path))
                    )
                    file_entry.uname = "root"
                    file_entry.gname = "root"
                    file_entry.uid = 0
                    file_entry.gid = 0

                    if file_entry.isreg():
                        with open(x, "rb") as fp:
                            container_tar.addfile(file_entry, fp)
                    else:
                        container_tar.addfile(file_entry)

        output_dir_path.parent.mkdir(exist_ok=True, parents=True)
        shutil.copy2(container_tarball_path, output_dir_path)


_AGENT_DOCKER_IMAGE_SUPPORTED_PLATFORMS = [
    DockerPlatform.AMD64.value,
    # DockerPlatform.ARM64.value,
    # DockerPlatform.ARMV7.value,
]


AGENT_DOCKER_JSON_SPEC = AgentImageTypeSpec(
    name="docker-json",
    base_config_path=SOURCE_ROOT / "docker" / "docker-json-config",
    result_image_name="scalyr-agent-docker-json",
)


AGENT_DOCKER_SYSLOG_SPEC = AgentImageTypeSpec(
    name="docker-syslog",
    base_config_path=SOURCE_ROOT / "docker" / "docker-syslog-config",
    result_image_name="scalyr-agent-docker-syslog",
    additional_result_image_names=["scalyr-agent-docker"],
    image_type_stage_name="docker-syslog",
)


AGENT_DOCKER_API_SPEC = AgentImageTypeSpec(
    name="docker-api",
    base_config_path=SOURCE_ROOT / "docker" / "docker-api-config",
    result_image_name="scalyr-agent-docker-api",
)


AGENT_K8S_SPEC = AgentImageTypeSpec(
    name="k8s",
    base_config_path=SOURCE_ROOT / "docker" / "k8s-config",
    result_image_name="scalyr-k8s-agent",
    image_type_stage_name="k8s",
)


AGENT_K8S_WITH_OPENMETRICS_SPEC = AgentImageTypeSpec(
    name="k8s-with-openmetrics",
    base_config_path=SOURCE_ROOT / "docker" / "k8s-config-with-openmetrics-monitor",
    result_image_name="scalyr-k8s-agent-with-openmetrics-monitor",
    image_type_stage_name="k8s",
)


AGENT_K8S_RESTART_AGENT_ON_MONITOR_DEATH_SPEC = AgentImageTypeSpec(
    name="k8s-restart-agent-on-monitor-death",
    base_config_path=SOURCE_ROOT / "docker" / "k8s-config-with-openmetrics-monitor",
    result_image_name="scalyr-k8s-agent-with-openmetrics-monitor",
    additional_config_paths=[
        SOURCE_ROOT / "docker" / "k8s-config-restart-agent-on-monitor-death"
    ],
    image_type_stage_name="k8s",
)


class ContainerImageBuilder(Runner):
    """
    The base builder for all docker and kubernetes based images. It builds base images for each particular
        platform/architecture and then use them to build a final multi-arch image.
    """

    # Dataclass instance that contains all information haw to build base images for this final image.
    BASE_IMAGE_BUILDER_STEP: BaseImageBuilderStep

    IMAGE_TYPE_SPEC: AgentImageTypeSpec

    # Tag of the result image to publish to the Dockerhub.
    TAG_SUFFIX: str = None

    def __init__(
        self,
        # registry: str = None,
        # tags: List[str] = None,
        # user: str = None,
        # push: bool = False,
        work_dir: pl.Path,
        platforms: List = None,
        # only_filesystem_tarball: str = None,
        # image_output_path: str = None,
        # use_test_version: bool = False,
    ):

        platforms = platforms
        self.platforms = None
        required_steps = []
        if platforms is None:
            # self.base_platform_builder_steps = type(self).BASE_IMAGE_BUILDER_STEP.platform_steps
            required_steps.append(type(self).BASE_IMAGE_BUILDER_STEP)
        else:
            # If only some platforms are specified, then use only those base image builder steps.
            required_steps.append(
                BaseImageBuilderStep(
                    base_distro=type(self).BASE_IMAGE_BUILDER_STEP.base_distro,
                    supported_platforms=platforms,
                )
            )

        super(ContainerImageBuilder, self).__init__(
            work_dir=work_dir, required_steps=required_steps
        )

    # def run(self, required_steps: List[RunnerStep] = None):
    #     #required_steps = []
    #     # if self.platforms is None:
    #     #     # self.base_platform_builder_steps = type(self).BASE_IMAGE_BUILDER_STEP.platform_steps
    #     #     required_steps["BASE_STEP"] = type(self).BASE_IMAGE_BUILDER_STEP
    #     # else:
    #     #     # If only some platforms are specified, then use only those base image builder steps.
    #     #     self.base_platform_builder_steps = []
    #     #     for plat in self.platforms:
    #     #         for step in type(self).BASE_IMAGE_BUILDER_STEP.platform_steps:
    #     #             if str(step.image_platform) == str(plat):
    #     #                 required_steps.append(step)
    #     #                 break
    #
    #     super(ContainerImageBuilder, self).run(
    #         required_steps=[type(self).BASE_IMAGE_BUILDER_STEP]
    #     )

    @classmethod
    def get_all_required_steps(cls):
        steps = super(ContainerImageBuilder, cls).get_all_required_steps()
        steps.append(cls.BASE_IMAGE_BUILDER_STEP)
        return steps

    # def build_filesystem_tarball(self, output_dir: str):
    #     """
    #     Build tarball with agent's filesystem.
    #     :param output_dir: Path to directory where result filesystem tarball is stored.
    #     """
    #
    #     output_dir_path = pl.Path(output_dir)
    #     package_root_path = output_dir_path / "package_root"
    #
    #     build_linux_lfs_agent_files(
    #         copy_agent_source=True,
    #         output_path=package_root_path,
    #     )
    #
    #     add_config(
    #         base_config_source_path=type(self).IMAGE_TYPE_SPEC.base_config_path,
    #         output_path=package_root_path / "etc/scalyr-agent-2",
    #         additional_config_paths=type(self).IMAGE_TYPE_SPEC.additional_config_paths,
    #     )
    #
    #     # Need to create some docker specific directories.
    #     pl.Path(package_root_path / "var/log/scalyr-agent-2/containers").mkdir()
    #
    #     container_tarball_path = self.output_path / "scalyr-agent.tar.gz"
    #
    #     # Do a manual walk over the contents of root so that we can use `addfile` to add the tarfile... which allows
    #     # us to reset the owner/group to root.  This might not be that portable to Windows, but for now, Docker is
    #     # mainly Posix.
    #     with tarfile.open(container_tarball_path, "w:gz") as container_tar:
    #
    #         for root, dirs, files in os.walk(package_root_path):
    #             to_copy = []
    #             for name in dirs:
    #                 to_copy.append(os.path.join(root, name))
    #             for name in files:
    #                 to_copy.append(os.path.join(root, name))
    #
    #             for x in to_copy:
    #                 file_entry = container_tar.gettarinfo(
    #                     x, arcname=str(pl.Path(x).relative_to(package_root_path))
    #                 )
    #                 file_entry.uname = "root"
    #                 file_entry.gname = "root"
    #                 file_entry.uid = 0
    #                 file_entry.gid = 0
    #
    #                 if file_entry.isreg():
    #                     with open(x, "rb") as fp:
    #                         container_tar.addfile(file_entry, fp)
    #                 else:
    #                     container_tar.addfile(file_entry)
    #
    #     output_dir_path.parent.mkdir(exist_ok=True, parents=True)
    #     shutil.copy2(container_tarball_path, output_dir_path)

    def build_container_filesystem(self, output_path: pl.Path):
        """
        Build tarball with agent's filesystem.
        :param output_path: Path to directory where result filesystem is stored.
        """

        output_path = pl.Path(output_path)
        package_root_path = output_path / "root"
        if package_root_path.exists():
            shutil.rmtree(package_root_path)
        package_root_path.mkdir(parents=True)

        build_linux_lfs_agent_files(
            copy_agent_source=True,
            output_path=package_root_path,
        )

        add_config(
            base_config_source_path=type(self).IMAGE_TYPE_SPEC.base_config_path,
            output_path=package_root_path / "etc/scalyr-agent-2",
            additional_config_paths=type(self).IMAGE_TYPE_SPEC.additional_config_paths,
        )

        # Need to create some docker specific directories.
        pl.Path(package_root_path / "var/log/scalyr-agent-2/containers").mkdir()

    @classmethod
    def get_all_result_image_names(cls, tags: List[str] = None):
        result_names = collections.defaultdict(list)
        all_image_names = [
            cls.IMAGE_TYPE_SPEC.result_image_name,
            *cls.IMAGE_TYPE_SPEC.additional_result_image_names,
        ]

        tags = tags or ["latest"]

        for image_name in all_image_names:
            for tag in tags:
                final_tag = tag
                if cls.TAG_SUFFIX:
                    final_tag = f"{final_tag}-{cls.TAG_SUFFIX}"

                result_names[image_name].append(final_tag)

        return result_names

    def build(
        self,
        output_registry_dir: pl.Path,
    ):
        """
        Builds final image
        :param registry: Registry (or repository) name where to push the result image.
        :param tags: The tag that will be applied to every registry that is specified. Can be used multiple times.
        :param user: User name prefix for the image name.
        :param push: Push the result docker image.
        :param platforms: Comma delimited list of platforms to build (and optionally push) the image for.
        :param only_filesystem_tarball: Build only the tarball with the filesystem of the agent. This argument has to
            accept path to the directory where the tarball is meant to be built. Used by the Dockerfile itself and does
            not require to be run manually.
        :param output_registry_dir: Path where result image tarball has to be stored.
        :param use_test_version: Build a special version of image with additional measuring tools (such as coverage).
            Used only for testing."
        """

        self.run()

        output_registry_dir_path = output_registry_dir and pl.Path(output_registry_dir)
        result_registry_data_root = output_registry_dir_path / "registry"

        # Cleanup, if needed.
        if result_registry_data_root.exists():
            shutil.rmtree(result_registry_data_root)
        result_registry_data_root.mkdir(parents=True)

        base_image_builder_step = type(self).BASE_IMAGE_BUILDER_STEP
        base_image_registry_path = base_image_builder_step.get_output_directory(
            work_dir=self.work_dir
        )

        # Create registry container with base images and registry container for result images.
        with LocalRegistryContainer(
            name="base_image_registry",
            registry_port=0,
            registry_data_path=base_image_registry_path / "registry",
        ) as src_registry, LocalRegistryContainer(
            name="result_image_registry",
            registry_port=0,
            registry_data_path=result_registry_data_root,
        ) as result_registry:

            image_names_options = []

            all_result_image_names = type(self).get_all_result_image_names()
            for name, tags in all_result_image_names.items():
                for tag in tags:
                    final_name = f"{name}:{tag}"

                    final_name = (
                        f"localhost:{result_registry.real_registry_port}/{final_name}"
                    )
                    image_names_options.extend(["-t", final_name])

            additional_options = ["--push" if True else "--load"]

            # for plat_step in type(self).BASE_IMAGE_BUILDER_STEP.platform_steps:
            #     additional_options.extend(["--platform", str(plat_step.image_platform)])
            for plat in _AGENT_DOCKER_IMAGE_SUPPORTED_PLATFORMS:
                additional_options.extend(["--platform", str(plat)])

            base_image_name = (
                f"{type(self).BASE_IMAGE_BUILDER_STEP.base_image_name_prefix}"
            )
            full_base_image_name = (
                f"localhost:{src_registry.real_registry_port}/{base_image_name}"
            )

            check_call_with_log(
                [
                    "docker",
                    "buildx",
                    "build",
                    *image_names_options,
                    "--build-arg",
                    f"PYTHON_BASE_IMAGE={type(self).BASE_IMAGE_BUILDER_STEP.base_distro.python_base_image}",
                    "--build-arg",
                    f"BASE_IMAGE_NAME={full_base_image_name}",
                    "--build-arg",
                    f"BUILDER_FQDN={type(self).get_fully_qualified_name()}",
                    "--build-arg",
                    f"IMAGE_TYPE_STAGE_NAME={type(self).IMAGE_TYPE_SPEC.image_type_stage_name}",
                    *additional_options,
                    "-f",
                    str(SOURCE_ROOT / "agent_build/docker/final.Dockerfile"),
                    str(SOURCE_ROOT),
                ]
            )

            # Also write a special JSON file near the registry folder where we list all created images and tags,
            registry_images_info_file_path = (
                output_registry_dir_path / "images-info.json"
            )
            registry_images_info_file_path.write_text(
                json.dumps(all_result_image_names)
            )

    def publish(
        self,
        src_registry_data_path: pl.Path,
        tags: List[str],
        user: str,
        dest_registry_host: str = None,
        dest_registry_tls_skip_verify: bool = False,
        dest_registry_creds: str = None,
    ):

        published_image_names = []

        src_registry_images_info_file_path = src_registry_data_path / "images-info.json"
        src_registry_images_info = json.loads(
            src_registry_images_info_file_path.read_text()
        )

        with LocalRegistryContainer(
            name=f"image-publish-src-registry",
            registry_port=0,
            registry_data_path=src_registry_data_path / "registry",
        ) as src_reg_container:

            src_registry_host = f"localhost:{src_reg_container.real_registry_port}"
            for image_name, dest_image_tags in (
                type(self).get_all_result_image_names(tags=tags).items()
            ):

                src_image_tag = src_registry_images_info[image_name][0]

                final_src_image_name = (
                    f"{src_registry_host}/{image_name}:{src_image_tag}"
                )

                for dest_tag in dest_image_tags:
                    final_dest_image_name = f"{user}/{image_name}:{dest_tag}"
                    if dest_registry_host:
                        final_dest_image_name = (
                            f"{dest_registry_host}/{final_dest_image_name}"
                        )

                    additional_options = []

                    if dest_registry_tls_skip_verify:
                        additional_options.append("--dest-tls-verify=false")

                    if dest_registry_creds:
                        additional_options.extend(["--dest-creds", dest_registry_creds])

                    check_call_with_log(
                        [
                            "skopeo",
                            "copy",
                            "--all",
                            "--src-tls-verify=false",
                            *additional_options,
                            f"docker://{final_src_image_name}",
                            f"docker://{final_dest_image_name}",
                        ],
                        description=f"Copy image '{final_src_image_name}' to '{final_dest_image_name}'",
                    )

                    published_image_names.append(final_dest_image_name)

        return published_image_names

    @classmethod
    def add_command_line_arguments(cls, parser: argparse.ArgumentParser):
        super(ContainerImageBuilder, cls).add_command_line_arguments(parser)

        parser.add_argument(
            "--platforms",
            dest="platforms",
            help="Comma separated list of supported image platforms.",
        )

        subparsers = parser.add_subparsers(dest="command")

        build_filesystem_tarball_parser = subparsers.add_parser(
            "build-container-filesystem"
        )
        build_filesystem_tarball_parser.add_argument(
            "--output",
            dest="output",
            required=True,
            help="Path to the directory there the result is stored.",
        )

        build_parser = subparsers.add_parser("build")
        build_parser.add_argument(
            "--output-registry-dir",
            dest="output_registry_dir",
            required=True,
            help="Path to the directory where registry data root with result image is stored.",
        )
        publish_parser = subparsers.add_parser("publish", help="")
        publish_parser.add_argument(
            "--src-registry-data-dir",
            dest="src_registry_data_dir",
            required=True,
            help="Path to the directory with registry data that contains images to publish.",
        )
        publish_parser.add_argument(
            "--dest-registry-host",
            dest="dest_registry_host",
            required=False,
            default="docker.io",
            help="URL to the target registry to save result images.",
        )
        publish_parser.add_argument(
            "--dest-registry-tls-skip-verify",
            dest="dest_registry_tls_skip_verify",
            required=False,
            action="store_true",
            help="If set, skopeo (tools that publishes images) won't check for secure connection. That's needed to"
            "push images to local registry.",
        )
        publish_parser.add_argument(
            "--dest-registry-creds",
            dest="dest_registry_creds",
            required=False,
            help="Colon-separated user name and password to target registry to publish.",
        )
        publish_parser.add_argument(
            "--tags", dest="tags", help="Comma-separated tags to publish."
        )
        publish_parser.add_argument(
            "--user", dest="user", required=True, help="Registry user."
        )

    @classmethod
    def handle_command_line_arguments(
        cls,
        args,
    ):
        super(ContainerImageBuilder, cls).handle_command_line_arguments(args)

        work_dir = pl.Path(args.work_dir)

        if args.platforms:
            platforms = args.platforms.split(",")
        else:
            platforms = None

        builder = cls(work_dir=work_dir, platforms=platforms)

        if args.command == "build":
            builder.build(output_registry_dir=pl.Path(args.output_registry_dir))
            exit(0)
        elif args.command == "build-container-filesystem":
            builder.build_container_filesystem(output_path=pl.Path(args.output))
        elif args.command == "publish":
            tags = args.tags and args.tags.split(",") or []

            builder.publish(
                src_registry_data_path=pl.Path(args.src_registry_data_dir),
                tags=tags,
                user=args.user,
                dest_registry_host=args.dest_registry_host,
                dest_registry_tls_skip_verify=args.dest_registry_tls_skip_verify,
                dest_registry_creds=args.dest_registry_creds,
            )
        else:
            if args.command is None:
                raise RuntimeError("Unspecified command.")
            else:
                raise RuntimeError(f"Unknown command: {args.command}")


class ContainerImageBuilderDebian(ContainerImageBuilder):
    BASE_IMAGE_BUILDER_STEP = BaseImageBuilderStep(
        base_distro=BaseDistroSpec(
            name="debian",
            python_base_image=f"python:{IMAGES_PYTHON_VERSION}-slim",
        ),
        supported_platforms=_AGENT_DOCKER_IMAGE_SUPPORTED_PLATFORMS,
    )


class ContainerImageBuilderAlpine(ContainerImageBuilder):
    BASE_IMAGE_BUILDER_STEP = BaseImageBuilderStep(
        BaseDistroSpec(
            name="alpine", python_base_image=f"python:{IMAGES_PYTHON_VERSION}-alpine"
        ),
        supported_platforms=_AGENT_DOCKER_IMAGE_SUPPORTED_PLATFORMS,
    )


# Final image builder classes for Debian-base images.
class DockerJsonDebian(ContainerImageBuilderDebian):
    IMAGE_TYPE_SPEC = AGENT_DOCKER_JSON_SPEC


class DockerSyslogDebian(ContainerImageBuilderDebian):
    IMAGE_TYPE_SPEC = AGENT_DOCKER_SYSLOG_SPEC


class DockerApiDebian(ContainerImageBuilderDebian):
    IMAGE_TYPE_SPEC = AGENT_DOCKER_API_SPEC


class K8sDebian(ContainerImageBuilderDebian):
    IMAGE_TYPE_SPEC = AGENT_K8S_SPEC


class K8sWithOpenMetricsDebian(ContainerImageBuilderDebian):
    IMAGE_TYPE_SPEC = AGENT_K8S_WITH_OPENMETRICS_SPEC


class K8sRestartAgentOnMonitorsDeathDebian(ContainerImageBuilderDebian):
    IMAGE_TYPE_SPEC = AGENT_K8S_RESTART_AGENT_ON_MONITOR_DEATH_SPEC


# Final image builder classes for Alpine-base images.
class DockerJsonAlpine(ContainerImageBuilderAlpine):
    IMAGE_TYPE_SPEC = AGENT_DOCKER_JSON_SPEC
    TAG_SUFFIX = "alpine"


class DockerSyslogAlpine(ContainerImageBuilderAlpine):
    IMAGE_TYPE_SPEC = AGENT_DOCKER_SYSLOG_SPEC
    TAG_SUFFIX = "alpine"


class DockerApiAlpine(ContainerImageBuilderAlpine):
    IMAGE_TYPE_SPEC = AGENT_DOCKER_API_SPEC
    TAG_SUFFIX = "alpine"


class K8sAlpine(ContainerImageBuilderAlpine):
    IMAGE_TYPE_SPEC = AGENT_K8S_SPEC
    TAG_SUFFIX = "alpine"


class K8sWithOpenMetricsAlpine(ContainerImageBuilderAlpine):
    IMAGE_TYPE_SPEC = AGENT_K8S_WITH_OPENMETRICS_SPEC
    TAG_SUFFIX = "alpine"


class K8sRestartAgentOnMonitorsDeathAlpine(ContainerImageBuilderAlpine):
    IMAGE_TYPE_SPEC = AGENT_K8S_RESTART_AGENT_ON_MONITOR_DEATH_SPEC
    TAG_SUFFIX = "alpine"


_DEBIAN_IMAGE_BUILDERS = [
    DockerJsonDebian,
    DockerSyslogDebian,
    DockerApiDebian,
    K8sDebian,
    K8sWithOpenMetricsDebian,
    K8sRestartAgentOnMonitorsDeathDebian,
]

_ALPINE_IMAGE_BUILDERS = [
    DockerJsonAlpine,
    DockerSyslogAlpine,
    DockerApiAlpine,
    K8sAlpine,
    K8sWithOpenMetricsAlpine,
    K8sRestartAgentOnMonitorsDeathAlpine,
]

# Final collection of all docker image builders.
DOCKER_IMAGE_BUILDERS: Dict[str, Type[ContainerImageBuilder]] = UniqueDict(
    {
        f"{b.IMAGE_TYPE_SPEC.name}-{b.BASE_IMAGE_BUILDER_STEP.base_distro.name}": b
        for b in [
            DockerJsonDebian,
            DockerSyslogDebian,
            DockerApiDebian,
            K8sDebian,
            K8sWithOpenMetricsDebian,
            K8sRestartAgentOnMonitorsDeathDebian,
            DockerJsonAlpine,
            DockerSyslogAlpine,
            DockerApiAlpine,
            K8sAlpine,
            K8sWithOpenMetricsAlpine,
            K8sRestartAgentOnMonitorsDeathAlpine,
        ]
    }
)

a = 10
if __name__ == "__main__":
    # We use this module as script in order to generate build job matrix for GitHub Actions.
    matrix = {"include": []}

    for builder_name, builder_cls in DOCKER_IMAGE_BUILDERS.items():
        matrix["include"].append(
            {
                "builder-name": builder_name,
                "distro-name": builder_cls.BASE_IMAGE_BUILDER_STEP.base_distro.value,
                "python-version": f"{IMAGES_PYTHON_VERSION}",
                "os": "ubuntu-20.04",
            }
        )

    print(json.dumps(matrix))
