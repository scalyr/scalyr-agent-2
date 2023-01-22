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
This module defines all agent docker images to build.
In order to keep builds in the GitHub Actions CI/CD fast, we first create the "base" image with all prepared
dependencies in it. This base image is build inside the tools.RunnerStep and can be cached by CI/CD.
The base image is build and stored in registry (because docker cannot store multi-arch images) and data
folder of that registry is a final result of the step.

Details note:
    The base image step actually also consists of other "platform-specific" steps, where each of them is responsible
     for the building of one base image for a particular platform (amd64, arm64, ...), so the base image step itself
     just combines those platform-specific images to a multi-arch one.
"""
import collections
import argparse
import dataclasses
import json
import logging
import pathlib as pl
import re
import shutil
from typing import List, Type, Dict

from agent_build_refactored.prepare_agent_filesystem import (
    build_linux_fhs_agent_files,
    add_config,
)
from agent_build_refactored.tools.constants import (
    SOURCE_ROOT,
    AGENT_BUILD_PATH,
    DockerPlatform,
    DockerPlatformInfo,
)
from agent_build_refactored.tools import (
    UniqueDict,
    LocalRegistryContainer,
    check_call_with_log,
)
from agent_build_refactored.tools.runner import (
    Runner,
    ArtifactRunnerStep,
    GitHubActionsSettings,
)

log = logging.getLogger(__name__)

# Python version that is used in docker images.
IMAGES_PYTHON_VERSION = "3.8.13"

_AGENT_REQUIREMENT_FILES_PATH = AGENT_BUILD_PATH / "requirement-files"
_TEST_REQUIREMENTS_FILE_PATH = (
    _AGENT_REQUIREMENT_FILES_PATH / "testing-requirements.txt"
)

# Get version of the coverage lib for the test version of the images.
# Parse version from requirements file in order to be in sync with it.
TEST_IMAGE_COVERAGE_VERSION = re.search(
    r"coverage==([\d\.]+)", _TEST_REQUIREMENTS_FILE_PATH.read_text()
).group(1)


@dataclasses.dataclass
class BaseDistroSpec:
    """
    Dataclass  which stores information about distribution on which the docker image has to be based on.
    """

    # Short name of the distribution, e.g. 'debian', 'alpine'
    name: str
    # Name of the base image with Python, e.g. python:slim, python-alpine,
    python_base_image: str


class BaseImagePlatformBuilderStep(ArtifactRunnerStep):
    """
    Runner step which builds one particular platform of the base image for the agent's final docker image.
    This step, as a result, produces tarball with base image for a particular platform/architecture of the final docker
    image. All such images will be used together to build base multi-arch image.
    NOTE: We do a per-platform image build to be able to build each such platform image in parallel in Ci/CD.
    """

    def __init__(
        self,
        base_distro: BaseDistroSpec,
        image_platform: DockerPlatformInfo,
        base_image_name_prefix: str,
    ):
        """
        :param base_distro: Spec of the base distro with all its needed information.
        :param image_platform: Target platform/architecture of the result base image.
        :param base_image_name_prefix: main prefix for the result image name.
        """

        super(BaseImagePlatformBuilderStep, self).__init__(
            name=f"{base_image_name_prefix}-{image_platform.to_dashed_str}",
            script_path="agent_build_refactored/docker/steps/build_base_platform_image.sh",
            tracked_files_globs=[
                "agent_build_refactored/docker/dockerfiles/base.Dockerfile",
                "agent_build_refactored/docker/dockerfiles/install-base-dependencies.sh",
                "agent_build_refactored/docker/dockerfiles/install-python-libs.sh",
                "agent_build_refactored/docker/dockerfiles/install-python-libs-build-dependencies.sh",
                "agent_build/requirement-files/docker-image-requirements.txt",
                "agent_build/requirement-files/compression-requirements.txt",
                "agent_build/requirement-files/main-requirements.txt",
            ],
            environment_variables={
                "PYTHON_BASE_IMAGE": base_distro.python_base_image,
                "DISTRO_NAME": base_distro.name,
                "RESULT_IMAGE_TARBALL_NAME": f"{base_image_name_prefix}:{image_platform.to_dashed_str}.tar",
                "PLATFORM": str(image_platform),
                "COVERAGE_VERSION": TEST_IMAGE_COVERAGE_VERSION,
            },
            github_actions_settings=GitHubActionsSettings(
                cacheable=True, pre_build_in_separate_job=True
            ),
        )


class BaseImageBuilderStep(ArtifactRunnerStep):
    """
    This step combines all platform-specific images  from its required steps into one multi-arch base image
    """

    def __init__(
        self,
        base_distro: BaseDistroSpec,
        supported_platforms: List[DockerPlatformInfo],
    ):
        """
        :param base_distro: Spec of the base distro with all its needed information.
        :param supported_platforms: List of platforms that has to be supported by the final image.
            For each platform, this step creates separate platform-specific "child" step.
        """
        self.base_image_name_prefix = f"agent-base-image-{base_distro.name}"

        required_steps = {}
        for plat in supported_platforms:
            platform_step = BaseImagePlatformBuilderStep(
                base_distro=base_distro,
                image_platform=plat,
                base_image_name_prefix=self.base_image_name_prefix,
            )

            required_steps[f"_BASE_PLATFORM_STEP_{platform_step.name}"] = platform_step

        super(BaseImageBuilderStep, self).__init__(
            name=self.base_image_name_prefix,
            script_path="agent_build_refactored/docker/steps/build_base_image.py",
            tracked_files_globs=[
                # Also add module files which are used by script.
                "agent_build_refactored/tools/steps_libs/container.py",
                "agent_build_refactored/tools/steps_libs/subprocess_with_log.py",
                "agent_build_refactored/tools/steps_libs/build_logging.py",
                "agent_build_refactored/tools/steps_libs/constants.py",
            ],
            required_steps=required_steps,
            environment_variables={
                "BASE_IMAGE_NAME_PREFIX": self.base_image_name_prefix,
            },
            github_actions_settings=GitHubActionsSettings(
                cacheable=True,
            ),
        )
        self.base_distro = base_distro
        self.supported_platforms = supported_platforms


@dataclasses.dataclass
class AgentImageTypeSpec:
    """
    Dataclass that contains all information about one of the agent image types, aka - docker-json, docker-syslog, e.g.
    """

    # Name of the image type.
    name: str

    # Path to the directory with config which has to be used by this image type.
    base_config_path: pl.Path

    # Name under which this image has to be published.
    result_image_name: str

    # List of paths to additional config paths which are copied upon the 'base_config_path' config files (and
    # overwrites if needed)
    additional_config_paths: List[pl.Path] = None

    # List of additional, alternative names to publish alongside with the 'result_image_name'.
    additional_result_image_names: List[str] = dataclasses.field(default_factory=list)

    # Name of the stage in the dockerfile which has to be picked for this particular image type.
    # Image types with specialized final docker images (for example k8s, docker-syslog) has to use their own
    # stage name, other has to use the 'common stage.'
    image_type_stage_name: str = "common"


_AGENT_DOCKER_IMAGE_SUPPORTED_PLATFORMS = [
    DockerPlatform.AMD64.value,
    DockerPlatform.ARM64.value,
    DockerPlatform.ARMV7.value,
]


class ContainerImageBuilder(Runner):
    """
    The base builder for all docker and kubernetes based images. It builds base images for each particular
        platform/architecture and then use them to build a final multi-arch image.
    """

    # Dataclass instance that contains all information haw to build base images for this final image.
    BASE_IMAGE_BUILDER_STEP: BaseImageBuilderStep

    # Spec with all information about the type of the result image.
    IMAGE_TYPE_SPEC: AgentImageTypeSpec

    # Tag of the result image to publish to the Dockerhub.
    TAG_SUFFIX: str = None

    @classmethod
    def get_name(cls):
        return (
            f"{cls.IMAGE_TYPE_SPEC.name}-{cls.BASE_IMAGE_BUILDER_STEP.base_distro.name}"
        )

    @classmethod
    def get_all_required_steps(cls):
        """
        Also add base image builder step as required to guarantee that it also will be cached.
        """
        steps = super(ContainerImageBuilder, cls).get_all_required_steps()
        steps.append(cls.BASE_IMAGE_BUILDER_STEP)
        return steps

    def build_container_filesystem(self, output_path: pl.Path):
        """
        Build tarball with agent's filesystem.
        :param output_path: Path to directory where result filesystem is stored.
        """

        output_path = pl.Path(output_path)
        package_root_path = output_path / "root"

        # Cleanup.
        if package_root_path.exists():
            shutil.rmtree(package_root_path)
        package_root_path.mkdir(parents=True)

        # Build 'FHS-structured' filesystem.
        build_linux_fhs_agent_files(
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
    def get_all_result_image_names(cls, tags: List[str] = None) -> Dict:
        """
        Generate permutation of all specified image names and tags as a collection of final image names.
        :param tags: Tags to add.
        :return Dictionary where key - image name, value - list of tags.
        """
        result_names = collections.defaultdict(list)

        all_image_names = [
            cls.IMAGE_TYPE_SPEC.result_image_name,
            *cls.IMAGE_TYPE_SPEC.additional_result_image_names,
        ]

        tags = tags or ["latest"]

        for image_name in all_image_names:
            for tag in tags:
                final_tag = tag

                # Add tag suffix if exists. It will add distro-specific suffix for each tag, for example for
                # alpine distribution with tags 'latest' and 'v2.1.1' it has to be 'latest-alpine' and '2.1.1-alpine'
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
        :param output_registry_dir: Path where result image tarball has to be stored.
        """

        # execute runner in order to execute all dependency steps.

        self.run_required()

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

        # Create registry container with base images...
        with LocalRegistryContainer(
            name="base_image_registry",
            registry_port=0,
            registry_data_path=base_image_registry_path / "registry",
            # ...and registry container for result images.
        ) as src_registry, LocalRegistryContainer(
            name="result_image_registry",
            registry_port=0,
            registry_data_path=result_registry_data_root,
        ) as result_registry:

            image_names_options = []

            # Get all names for the result image.
            all_result_image_names = type(self).get_all_result_image_names()
            for name, tags in all_result_image_names.items():
                for tag in tags:
                    final_name = f"{name}:{tag}"

                    final_name = (
                        f"localhost:{result_registry.real_registry_port}/{final_name}"
                    )
                    image_names_options.extend(["-t", final_name])

            additional_options = ["--push" if True else "--load"]

            # Get all needed platforms.
            for plat in base_image_builder_step.supported_platforms:
                additional_options.extend(["--platform", str(plat)])

            base_image_name = base_image_builder_step.base_image_name_prefix
            src_registry_host = f"localhost:{src_registry.real_registry_port}"
            full_base_image_name = f"{src_registry_host}/{base_image_name}"

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
                    str(
                        SOURCE_ROOT
                        / "agent_build_refactored/docker/dockerfiles/final.Dockerfile"
                    ),
                    str(SOURCE_ROOT),
                ],
                description=f"Build final image with names {all_result_image_names} and "
                f"platforms {base_image_builder_step.supported_platforms}",
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
        dst_registry_host: str = None,
        dst_registry_tls_skip_verify: bool = False,
        dst_registry_creds: str = None,
    ):
        """
        This method publishes previously built image to the target registry.
        It accepts path to data root of the registry where result image is stored and copies it by using
            tool 'skopeo'.
        :param src_registry_data_path: Path to the data root for the registry with image to publish.
            Inside there has to be:
             - an actual root of the registry.
             - JSON file named 'images-info.json' with all names and tags that the result has in this registry.
        :param tags: List of tags under which, the result image has to be published.
        :param user: Use name under which, the result image has to be published.
        :param dst_registry_host: Host of the destination registry. Has to be Dockerhub by default.
        :param dst_registry_tls_skip_verify: Can be set to True if we use local registry as destination ( which
            may not have HTTPS). Needed for skopeo.
        :param dst_registry_creds: Colon-separated registry username and password.
        :return: List of names of published images.
        """

        published_image_names = []

        # Read JSON info file with source image names and tags.
        src_registry_images_info_file_path = src_registry_data_path / "images-info.json"
        src_registry_images_info = json.loads(
            src_registry_images_info_file_path.read_text()
        )

        # Spin up registry with image to publish.
        with LocalRegistryContainer(
            name="image-publish-src-registry",
            registry_port=0,
            registry_data_path=src_registry_data_path / "registry",
        ) as src_reg_container:

            src_registry_host = f"localhost:{src_reg_container.real_registry_port}"

            # Enumerate through all image names under which image has to be published.
            for image_name, dst_image_tags in (
                type(self).get_all_result_image_names(tags=tags).items()
            ):

                src_image_tag = src_registry_images_info[image_name][0]

                final_src_image_name = (
                    f"{src_registry_host}/{image_name}:{src_image_tag}"
                )

                # Create final image name + tag for each needed image name and copy it to the destination
                # registry using 'skopeo copy'.
                for dst_tag in dst_image_tags:
                    final_dest_image_name = f"{user}/{image_name}:{dst_tag}"
                    if dst_registry_host:
                        final_dest_image_name = (
                            f"{dst_registry_host}/{final_dest_image_name}"
                        )

                    additional_options = []

                    if dst_registry_tls_skip_verify:
                        additional_options.append("--dest-tls-verify=false")

                    if dst_registry_creds:
                        additional_options.extend(["--dest-creds", dst_registry_creds])

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
        """
        Define CLI for the docker image builder.
        :param parser: argparse parser.
        """
        super(ContainerImageBuilder, cls).add_command_line_arguments(parser)

        subparsers = parser.add_subparsers(dest="command")

        build_filesystem_tarball_parser = subparsers.add_parser(
            "build-container-filesystem",
            help="Build only the filesystem for the docker image.",
        )
        build_filesystem_tarball_parser.add_argument(
            "--output",
            dest="output",
            required=True,
            help="Path to the directory there the result is stored.",
        )

        build_parser = subparsers.add_parser(
            "build", help="Build docker image and put it to the registry."
        )
        build_parser.add_argument(
            "--output-registry-dir",
            dest="output_registry_dir",
            required=True,
            help="Path to the directory where registry data root with result image is stored.",
        )
        publish_parser = subparsers.add_parser(
            "publish",
            help="Publish image from the previously built image to the target registry.",
        )
        publish_parser.add_argument(
            "--src-registry-data-dir",
            dest="src_registry_data_dir",
            required=True,
            help="Path to the directory with registry data that contains images to publish.",
        )
        publish_parser.add_argument(
            "--dst-registry-host",
            dest="dst_registry_host",
            required=False,
            default="docker.io",
            help="URL to the target registry to save result images.",
        )
        publish_parser.add_argument(
            "--dst-registry-tls-skip-verify",
            dest="dst_registry_tls_skip_verify",
            required=False,
            action="store_true",
            help="If set, skopeo (tools that publishes images) won't check for secure connection. That's needed to"
            "push images to local registry.",
        )
        publish_parser.add_argument(
            "--dst-registry-creds",
            dest="dst_registry_creds",
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
        """
        Handle parsed command line arguments.
        """
        super(ContainerImageBuilder, cls).handle_command_line_arguments(args)

        work_dir = pl.Path(args.work_dir)

        builder = cls(work_dir=work_dir)

        if args.command == "build":
            builder.build(output_registry_dir=pl.Path(args.output_registry_dir))
            exit(0)

        elif args.command == "build-container-filesystem":
            builder.build_container_filesystem(output_path=pl.Path(args.output))
            exit(0)
        elif args.command == "publish":
            tags = args.tags and args.tags.split(",") or []

            builder.publish(
                src_registry_data_path=pl.Path(args.src_registry_data_dir),
                tags=tags,
                user=args.user,
                dst_registry_host=args.dest_registry_host,
                dst_registry_tls_skip_verify=args.dest_registry_tls_skip_verify,
                dst_registry_creds=args.dest_registry_creds,
            )
            exit(0)
        else:
            if args.command is None:
                raise RuntimeError("Unspecified command.")
            else:
                raise RuntimeError(f"Unknown command: {args.command}")


class ContainerImageBuilderDebian(ContainerImageBuilder):
    """
    Base docker image builder class for all debian-based images.
    """

    BASE_IMAGE_BUILDER_STEP = BaseImageBuilderStep(
        base_distro=BaseDistroSpec(
            name="debian",
            python_base_image=f"python:{IMAGES_PYTHON_VERSION}-slim",
        ),
        supported_platforms=_AGENT_DOCKER_IMAGE_SUPPORTED_PLATFORMS,
    )


class ContainerImageBuilderAlpine(ContainerImageBuilder):
    """
    Base docker image builder class for all alpine-based images.
    """

    BASE_IMAGE_BUILDER_STEP = BaseImageBuilderStep(
        BaseDistroSpec(
            name="alpine", python_base_image=f"python:{IMAGES_PYTHON_VERSION}-alpine"
        ),
        supported_platforms=_AGENT_DOCKER_IMAGE_SUPPORTED_PLATFORMS,
    )


# Define spec for all possible docker image type such as docker-json, docker-syslog, etc.

# An image for running on Docker configured to fetch logs via the file system (the container log
# directory is mounted to the agent container.)  This is the preferred way of running on Docker.
AGENT_DOCKER_JSON_SPEC = AgentImageTypeSpec(
    name="docker-json",
    base_config_path=SOURCE_ROOT / "docker" / "docker-json-config",
    result_image_name="scalyr-agent-docker-json",
)

# An image for running on Docker configured to receive logs from other containers via syslog.
# This is the deprecated approach (but is still published under scalyr/scalyr-docker-agent for
# backward compatibility.)  We also publish this under scalyr/scalyr-docker-agent-syslog to help
# with the eventual migration.
AGENT_DOCKER_SYSLOG_SPEC = AgentImageTypeSpec(
    name="docker-syslog",
    base_config_path=SOURCE_ROOT / "docker" / "docker-syslog-config",
    result_image_name="scalyr-agent-docker-syslog",
    additional_result_image_names=["scalyr-agent-docker"],
    image_type_stage_name="docker-syslog",
)

# An image for running on Docker configured to fetch logs via the Docker API using docker_raw_logs: false
# configuration option.
AGENT_DOCKER_API_SPEC = AgentImageTypeSpec(
    name="docker-api",
    base_config_path=SOURCE_ROOT / "docker" / "docker-api-config",
    result_image_name="scalyr-agent-docker-api",
)

# An image for running the agent on Kubernetes.
AGENT_K8S_SPEC = AgentImageTypeSpec(
    name="k8s",
    base_config_path=SOURCE_ROOT / "docker" / "k8s-config",
    result_image_name="scalyr-k8s-agent",
    image_type_stage_name="k8s",
)


# Final image builder classes for Debian-based images.
class DockerJsonDebian(ContainerImageBuilderDebian):
    IMAGE_TYPE_SPEC = AGENT_DOCKER_JSON_SPEC


class DockerSyslogDebian(ContainerImageBuilderDebian):
    IMAGE_TYPE_SPEC = AGENT_DOCKER_SYSLOG_SPEC


class DockerApiDebian(ContainerImageBuilderDebian):
    IMAGE_TYPE_SPEC = AGENT_DOCKER_API_SPEC


class K8sDebian(ContainerImageBuilderDebian):
    IMAGE_TYPE_SPEC = AGENT_K8S_SPEC


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


DEBIAN_DOCKER_IMAGE_BUILDERS = [
    DockerJsonDebian,
    DockerSyslogDebian,
    DockerApiDebian,
]

DEBIAN_K8S_IMAGE_BUILDERS = [
    K8sDebian,
]
DEBIAN_IMAGE_BUILDERS = [*DEBIAN_DOCKER_IMAGE_BUILDERS, *DEBIAN_K8S_IMAGE_BUILDERS]

ALPINE_DOCKER_IMAGE_BUILDERS = [
    DockerJsonAlpine,
    DockerSyslogAlpine,
    DockerApiAlpine,
]
ALPINE_K8S_IMAGE_BUILDERS = [
    K8sAlpine,
]

ALPINE_IMAGE_BUILDERS = [
    *ALPINE_DOCKER_IMAGE_BUILDERS,
    *ALPINE_K8S_IMAGE_BUILDERS,
]

ALL_IMAGE_BUILDERS: Dict[str, Type[ContainerImageBuilder]] = UniqueDict(
    {b.get_name(): b for b in [*DEBIAN_IMAGE_BUILDERS, *ALPINE_IMAGE_BUILDERS]}
)
