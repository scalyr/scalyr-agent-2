import dataclasses
import pathlib as pl
import re
import shutil
import subprocess
import tarfile
from typing import Dict, List


from agent_build_refactored.tools.constants import REQUIREMENTS_COMMON, REQUIREMENTS_COMMON_PLATFORM_DEPENDENT
from agent_build_refactored.managed_packages.build_dependencies_versions import RUST_VERSION

SOURCE_PATH = pl.Path(__file__).parent.parent.parent
BUILD_PYTHON_DIR = SOURCE_PATH / "agent_build_refactored/build_dependencies"
AGENT_BUILD_OUTPUT_PATH = SOURCE_PATH / "agent_build_output"

PYTHON_INSTALL_PREFIX = "/opt/scalyr-agent-2/python3"


class BuildStep:
    def __init__(
        self,
        name: str,
        build_context: pl.Path,
        platform: str,
        dockerfile_path: pl.Path,
        dependency_build_steps: Dict[str, 'BuildStep'] = None,
        build_args: Dict[str, str] = None,
    ):

        self.name = name
        self.platform = platform
        self.build_context = build_context
        self.dockerfile_path = dockerfile_path
        self.dependency_build_steps = dependency_build_steps or {}
        self.build_args = build_args or {}

    @property
    def oci_layout_path(self):
        return AGENT_BUILD_OUTPUT_PATH / self.name

    @property
    def oci_tarball_path(self):
        return f"{self.oci_layout_path}.tar"

    def run(
        self,
        additional_cmd_args: List[str] = None
    ):

        additional_cmd_args = additional_cmd_args or []

        build_context_opts = []
        for name, dep_step in self.dependency_build_steps.items():
            dep_step.build_oci_tarball()

            if dep_step.oci_layout_path.exists():
                shutil.rmtree(dep_step.oci_layout_path)

            with tarfile.open(dep_step.oci_tarball_path) as tar:
                tar.extractall(dep_step.oci_layout_path)

            build_context_opts.extend([
                "--build-context",
                f"{name}=oci-layout://{dep_step.oci_layout_path}"
            ])

        build_args_opts = []
        for name, value in self.build_args.items():
            build_args_opts.extend([
                "--build-arg",
                f"{name}={value}"
            ])

        command_args = [
            "docker",
            "buildx",
            "build",
            str(self.build_context),
            *build_context_opts,
            *build_args_opts,
            *additional_cmd_args,
        ]

        if self.dockerfile_path:
            command_args.extend([
                "-f",
                str(self.dockerfile_path)
            ])

        subprocess.run(
            command_args,
            check=True
        )

    def build_oci_tarball(self):

        AGENT_BUILD_OUTPUT_PATH.mkdir(parents=True, exist_ok=True)
        self.run(
            additional_cmd_args=[
                "--output",
                f"type=oci,dest={self.oci_tarball_path}"
            ]
        )


def _target_arch_to_docker_platform(arch: str):
    if arch == "x86_64":
        return "linux/amd64",

    if arch == "aarch64":
        return "linux/arm/64"

    if arch == "armv7":
        return "linux/arm/v7"

    raise Exception(f"Unknown target arch: {arch}")



@dataclasses.dataclass
class ToolchainTarget:
    full_value: str
    arch: str = dataclasses.field(init=False)
    vendor: str = dataclasses.field(init=False)
    os: str = dataclasses.field(init=False)
    libc: str = dataclasses.field(init=False)
    abi: str = dataclasses.field(init=False)

    def __post_init__(self):
        target_parts = self.full_value.split("-")
        self.arch = target_parts[0]
        self.vendor = target_parts[1]
        self.os = target_parts[2]
        target_libs_abi = target_parts[3]
        m = re.search(r"^(gnu|musl)(\S*)$", target_libs_abi)
        self.libc = m.group(1)
        self.abi = m.group(2)

    @property
    def as_docker_platform(self):
        if self.arch == "x86_64":
            return "linux/amd64",

        if self.arch == "aarch64":
            return "linux/arm/64"

        if self.arch == "armv7":
            return "linux/arm/v7"

        raise Exception(f"Unknown target arch: {self.arch}")


class PrepareBuildEnvironmentStep(BuildStep):
    BUILD_CONTEXT = BUILD_PYTHON_DIR / "prepare_build_environment"

    def __init__(
        self,
        target: str,
    ):
        self.target = ToolchainTarget(full_value=target)
        super(PrepareBuildEnvironmentStep, self).__init__(
            name="prepare_build_environment",
            build_context=self.__class__.BUILD_CONTEXT,
            platform=self.target.as_docker_platform,
            dockerfile_path=self.__class__.BUILD_CONTEXT / "Dockerfile",
            build_args={
                "TARGET": self.target.full_value,
                "TARGET_LIBC": self.target.libc,
            }
        )


class BuildPythonStep(BuildStep):
    BUILD_CONTEXT = BUILD_PYTHON_DIR / "build_python"
    def __init__(
        self,
        prepare_build_environment_step: PrepareBuildEnvironmentStep,
        python_version: str,
    ):

        self.target = prepare_build_environment_step.target

        python_x_y_version = ".".join(python_version.split(".")[:2])

        super(BuildPythonStep, self).__init__(
            name="build_python",
            platform=self.target.as_docker_platform,
            build_context=self.__class__.BUILD_CONTEXT,
            dockerfile_path=self.__class__.BUILD_CONTEXT / "Dockerfile",
            dependency_build_steps={
                "prepare_build_environment": prepare_build_environment_step,
            },
            build_args={
                "XZ_VERSION": "5.2.6",
                "ZLIB_VERSION": "1.2.13",
                "BZIP_VERSION": "1.0.8",
                "UTIL_LINUX_VERSION": "2.38",
                "NCURSES_VERSION": "6.3",
                "LIBFFI_VERSION": "3.4.2",
                "OPENSSL_1_VERSION": "1.1.1s",
                "OPENSSL_3_VERSION": "3.0.7",
                "LIBEDIT_VERSION_COMMIT": "0cdd83b3ebd069c1dee21d81d6bf716cae7bf5da",  # tag - "upstream/3.1-20221030",
                "TCL_VERSION_COMMIT": "338c6692672696a76b6cb4073820426406c6f3f9",  # tag - "core-8-6-13"}",
                "SQLITE_VERSION_COMMIT": "e671c4fbc057f8b1505655126eaf90640149ced6",  # tag - "version-3.41.2",
                "PYTHON_VERSION": python_version,
                "PYTHON_X_Y_VERSION": python_x_y_version,
            },
        )


class BuildVenv(BuildStep):
    BUILD_CONTEXT = BUILD_PYTHON_DIR / "build_agent_libs_venv"

    def __init__(
        self,
        prepare_build_environment: PrepareBuildEnvironmentStep,
        build_python: BuildPythonStep,
        requirements_file_content: str,
    ):

        self.target = target = prepare_build_environment.target

        rust_target_platform = f"{target.arch}-unknown-{target.os}-{target.libc}{target.abi}"

        install_rust_from_package_manager = False
        if target.arch == "armv7":
            if target.libc == "musl":
                install_rust_from_package_manager = True

        if install_rust_from_package_manager:
            install_rust_stage_name = f"install_rust_from_package_manager_{target.libc}"
        else:
            install_rust_stage_name = "install_rust"

        super(BuildVenv, self).__init__(
            name="build_venv",
            build_context=self.__class__.BUILD_CONTEXT,
            platform=build_python_step.platform,
            dockerfile_path=self.__class__.BUILD_CONTEXT / "Dockerfile",
            dependency_build_steps={
                "prepare_build_environment": prepare_build_environment,
                "build_python": build_python,
            },
            build_args={
                "REQUIREMENTS": requirements_file_content,
                "PYTHON_INSTALL_PREFIX": PYTHON_INSTALL_PREFIX,
                "RUST_VERSION": RUST_VERSION,
                "RUST_PLATFORM": rust_target_platform,
                "INSTALL_RUST_STAGE_NAME": install_rust_stage_name
            },
        )


prepare_build_environment_step = PrepareBuildEnvironmentStep(
    target="x86_64-unknown-linux-musl"
)

build_python_step = BuildPythonStep(
    prepare_build_environment_step=prepare_build_environment_step,
    python_version="3.11.2",
)


build_venv_step = BuildVenv(
    prepare_build_environment=prepare_build_environment_step,
    build_python=build_python_step,
    requirements_file_content=f"{REQUIREMENTS_COMMON}\n{REQUIREMENTS_COMMON_PLATFORM_DEPENDENT}"
)

build_venv_step.run(additional_cmd_args=["--load", "-t", "test"])
