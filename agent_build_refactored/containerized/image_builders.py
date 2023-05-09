import collections
import dataclasses
import enum
import pathlib as pl
import shutil
import subprocess
import tarfile
from typing import List, Dict, Type

from agent_build_refactored.tools import UniqueDict
from agent_build_refactored.tools.constants import Architecture, SOURCE_ROOT, REQUIREMENTS_DEV_COVERAGE
from agent_build_refactored.build_python.build_python_steps import (
    ALL_PYTHON_TOOLCHAINS,
    CRuntime,
    AgentLibsVenvToolchain
)
from agent_build_refactored.tools.runner import Runner, RunnerStep


from agent_build_refactored.managed_packages.managed_packages_builders import (
    AGENT_SUBDIR_NAME,
    AGENT_LIBS_REQUIREMENTS_CONTENT
)
from agent_build_refactored.build_python.build_python_steps import create_python_files, create_agent_libs_venv_files
from agent_build_refactored.prepare_agent_filesystem import add_config, render_agent_executable_script, build_agent_linux_fhs_common_files

DEFAULT_SUPPORTED_IMAGE_ARCHITECTURES = [
    Architecture.X86_64,
]


def _create_agent_libs_venv_toolchains() -> Dict[CRuntime, Dict[Architecture, AgentLibsVenvToolchain]]:
    """
    Prepare toolchains for building agent libs venv steps.
    """
    result = collections.defaultdict(dict)
    for c_runtime, toolchains in ALL_PYTHON_TOOLCHAINS.items():
        for architecture, python_toolchain in toolchains.items():
            toolchain = AgentLibsVenvToolchain.create(
                python_toolchain=python_toolchain,
                requirements_file_content=AGENT_LIBS_REQUIREMENTS_CONTENT,
                test_requirements_file_content=REQUIREMENTS_DEV_COVERAGE,
            )
            result[c_runtime][architecture] = toolchain

    return result


BUILD_AGENT_LIBS_VENV_TOOLCHAINS = _create_agent_libs_venv_toolchains()


class BaseDistro(enum.Enum):
    UBUNTU = "ubuntu"
    ALPINE = "alpine"


BASE_DISTROS_TO_C_RUNTIMES = {
    BaseDistro.UBUNTU: CRuntime.GLIBC,
    BaseDistro.ALPINE: CRuntime.MUSL,
}


class ImageType(enum.Enum):
    K8S = "k8s"
    DOCKER_JSON = "docker-json"
    DOCKER_SYSLOG = "docker-syslog"
    DOCKER_API = "docker-api"


class ContainerizedAgentBuilder(Runner):
    BASE_DISTRO: BaseDistro
    SUPPORTED_ARCHITECTURES: List[Architecture]
    IMAGE_TYPE: ImageType
    IMAGE_NAMES: str
    IMAGE_TAG_SUFFIXES: str
    CONFIG_PATH: pl.Path

    @classmethod
    def get_c_runtime(cls):
        return BASE_DISTROS_TO_C_RUNTIMES[cls.BASE_DISTRO]

    @classmethod
    def get_agent_libs_venv_toolchains(cls) -> Dict[Architecture, AgentLibsVenvToolchain]:
        toolchains = {}
        c_runtime = cls.get_c_runtime()

        c_runtime_toolchains = BUILD_AGENT_LIBS_VENV_TOOLCHAINS[c_runtime]
        for architecture, toolchain in c_runtime_toolchains.items():
            if architecture not in cls.SUPPORTED_ARCHITECTURES:
                continue
            toolchains[architecture]=toolchain

        return toolchains

    @classmethod
    def get_all_required_steps(cls) -> List[RunnerStep]:

        steps = []

        for toolchain in cls.get_agent_libs_venv_toolchains().values():
            steps.extend([
                toolchain.python_toolchain.openssl_3,
                toolchain.python_toolchain.python_with_openssl_3,
                toolchain.build_agent_libs_venv,
            ])
        return steps

    @staticmethod
    def get_platform_specific_dir_name(architecture: Architecture):
        docker_platform = architecture.as_docker_platform.value
        platform_variant = docker_platform.variant or ""
        return f"{docker_platform.os}_{docker_platform.architecture}_{platform_variant}"

    @property
    def publish_script_path(self) -> pl.Path:
        return self.output_path / "publish_image.sh"

    def render_publish_script(
            self,
            image_build_source_tarball: pl.Path,
            output_path: pl.Path
    ):
        template = SOURCE_ROOT / "agent_build_refactored/containerized/publish_image_script_template.sh"
        content = template.read_text()

        content = content.replace(
            "%{{ REPLACE_IMAGE_NAMES }}%",
            ",".join(self.IMAGE_NAMES)
        )
        content = content.replace(
            "%{{ REPLACE_IMAGE_TAG_SUFFIXES }}%",
            ",".join(self.IMAGE_TAG_SUFFIXES)
        )
        content = content.replace("%{{ REPLACE_BASE_DISTRO }}%", self.BASE_DISTRO.value)
        content = content.replace("%{{ REPLACE_IMAGE_TYPE }}%", self.IMAGE_TYPE.value)

        output_path.write_text(content)

        with output_path.open("ab") as script_file, image_build_source_tarball.open("rb") as image_tarball_file:
            chunk_size = 2**20  # 1 MB
            while True:
                data = image_tarball_file.read(chunk_size)

                if not data:
                    break
                script_file.write(data)

    def build(self):
        self.prepare_runer()

        image_build_source_dir = self.output_path / "image_build_source"
        image_build_source_dir.mkdir()

        dockerfile_path = SOURCE_ROOT / "agent_build_refactored/containerized/Dockerfile"

        shutil.copy(dockerfile_path, image_build_source_dir)

        build_context_dir = image_build_source_dir / "image_build_context"

        agent_filesystem_root = build_context_dir / "agent_filesystem_root"

        # Build 'FHS-structured' filesystem.
        build_agent_linux_fhs_common_files(
            output_path=agent_filesystem_root,
            agent_executable_name="scalyr-agent-2"
        )

        add_config(
            base_config_source_path=self.CONFIG_PATH,
            output_path=agent_filesystem_root / "etc/scalyr-agent-2",
        )

        install_root_executable_path = (
            agent_filesystem_root / f"usr/share/{AGENT_SUBDIR_NAME}/bin/scalyr-agent-2"
        )
        install_root_python_executable = agent_filesystem_root / f"usr/share/{AGENT_SUBDIR_NAME}/bin/python3"
        install_root_python_executable.symlink_to(
            "/var/opt/scalyr-agent-2/venv/bin/python3"
        )



        render_agent_executable_script(
            #python_executable=pl.Path("/var/opt/scalyr-agent-2/venv/bin/python3"),
            python_executable=pl.Path(f"/usr/share/{AGENT_SUBDIR_NAME}/bin/python3"),
            agent_main_script_path=pl.Path("/usr/share/scalyr-agent-2/py/scalyr_agent/agent_main.py"),
            output_file=install_root_executable_path
        )

        # Also link agent executable to usr/sbin
        usr_sbin_executable = agent_filesystem_root / "usr/sbin/scalyr-agent-2"
        usr_sbin_executable.unlink()
        usr_sbin_executable.symlink_to("../share/scalyr-agent-2/bin/scalyr-agent-2")

        # Need to create some docker specific directories.
        pl.Path(agent_filesystem_root / "var/log/scalyr-agent-2/containers").mkdir()

        platform_args = []

        # Create architecture-dependent files, such as Python interpreter, etc.

        for toolchain in self.get_agent_libs_venv_toolchains().values():
            architecture = toolchain.python_toolchain.architecture

            arch_dir_name = self.get_platform_specific_dir_name(
                architecture=architecture
            )

            python_arch_dir = build_context_dir / "python" / arch_dir_name

            build_python_step = toolchain.python_toolchain.python_with_openssl_3
            build_python_output = build_python_step.get_output_directory(work_dir=self.work_dir)

            build_python_dependencies_step = toolchain.python_toolchain.build_python_dependencies_step
            build_python_dependencies_step_output = build_python_dependencies_step.get_output_directory(
                work_dir=self.work_dir
            )
            create_python_files(
                build_python_dependencies_step_output=build_python_dependencies_step_output,
                build_python_step_output=build_python_output,
                output=python_arch_dir,
            )

            build_agent_libs_step = toolchain.build_agent_libs_venv
            build_agent_libs_step_output = build_agent_libs_step.get_output_directory(
                work_dir=self.work_dir
            )

            venv_arch_dir = build_context_dir / "venv" / arch_dir_name / f"var/opt" / AGENT_SUBDIR_NAME / "venv"
            create_agent_libs_venv_files(
                build_libs_venv_step_output=build_agent_libs_step_output,
                output=venv_arch_dir
            )

            platform_args.extend([
                "--platform",
                str(architecture.as_docker_platform.value)
            ])

        image_build_source_tarball = self.output_path / "image_build_source.tar.gz"
        with tarfile.open(image_build_source_tarball, "w:gz") as tar:
            tar.add(
                image_build_source_dir,
                arcname=image_build_source_dir.name
            )

        # Render publishing script.
        self.render_publish_script(
            image_build_source_tarball=image_build_source_tarball,
            output_path=self.publish_script_path,
        )

    @classmethod
    def handle_command_line_arguments(
        cls,
        args,
    ):
        super(ContainerizedAgentBuilder, cls).handle_command_line_arguments(args=args)

        builder = cls(work_dir=args.work_dir)

        builder.build()

        build_dir = SOURCE_ROOT / "build"

        if build_dir.exists():
            shutil.rmtree(build_dir)

        build_dir.mkdir()


ALL_AGENT_IMAGE_BUILDERS: Dict[str, Type[ContainerizedAgentBuilder]] = UniqueDict()

# Mapping of the image types to their result names.
IMAGE_TYPES_TO_RESULT_IMAGE_NAMES = {
    ImageType.K8S: ["scalyr-k8s-agent"],
    ImageType.DOCKER_JSON: ["scalyr-agent-docker-json"],
    ImageType.DOCKER_SYSLOG: ["scalyr-agent-docker-syslog", "scalyr-agent-docker"],
    ImageType.DOCKER_API: ["scalyr-agent-docker-api"]
}

# Mapping of the image base distros to suffixes for the result images.
BASE_DISTROS_TO_RESULT_IMAGE_TAG_SUFFIXES = {
    BaseDistro.UBUNTU: ["", "-ubuntu"],
    BaseDistro.ALPINE: ["-alpine"]
}


def _capitalize_str(string: str):
    """Return string but with capital first letter."""
    chars = list(string)
    chars[0] = chars[0].upper()
    return "".join(chars)


for distro in BaseDistro:
    for image_type in ImageType:
        class_alias_prefix = f"{_capitalize_str(distro.value)}{_capitalize_str(image_type.value)}"

        class _ContainerizedBuilder(ContainerizedAgentBuilder):
            BASE_DISTRO = distro
            SUPPORTED_ARCHITECTURES = DEFAULT_SUPPORTED_IMAGE_ARCHITECTURES[:]
            IMAGE_TYPE = image_type
            IMAGE_NAMES = IMAGE_TYPES_TO_RESULT_IMAGE_NAMES[image_type][:]
            IMAGE_TAG_SUFFIXES = BASE_DISTROS_TO_RESULT_IMAGE_TAG_SUFFIXES[distro][:]
            CONFIG_PATH = SOURCE_ROOT / "docker" / f"{image_type.value}-config"
            CLASS_NAME_ALIAS = f"{class_alias_prefix}ContainerizedAgentBuilder"
            ADD_TO_GLOBAL_RUNNER_COLLECTION = True

        builder_name = f"containerized-{image_type.value}-{distro.value}"
        ALL_AGENT_IMAGE_BUILDERS[builder_name] = _ContainerizedBuilder






