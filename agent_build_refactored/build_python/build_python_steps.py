import dataclasses
import pathlib as pl
from typing import Dict


from agent_build_refactored.tools.constants import Architecture, DockerPlatform
from agent_build_refactored.tools.runner import RunnerStep, EnvironmentRunnerStep, DockerImageSpec

from agent_build_refactored.managed_packages.build_dependencies_versions import (
    PYTHON_PACKAGE_SSL_1_1_1_VERSION,
    PYTHON_PACKAGE_SSL_3_VERSION,
    EMBEDDED_PYTHON_VERSION,
    EMBEDDED_PYTHON_PIP_VERSION,
    RUST_VERSION,
)

OPENSSL_VERSION_TYPE_1_1_1 = "1_1_1"
OPENSSL_VERSION_TYPE_3 = "3"

# Name of the subdirectory of the agent packages.
AGENT_SUBDIR_NAME = "scalyr-agent-2"

AGENT_OPT_DIR = pl.Path("/opt") / AGENT_SUBDIR_NAME
PYTHON_INSTALL_PREFIX = f"{AGENT_OPT_DIR}/python3"

EMBEDDED_PYTHON_SHORT_VERSION = ".".join(EMBEDDED_PYTHON_VERSION.split(".")[:2])



PYTHON_PACKAGE_SSL_VERSIONS = {
    OPENSSL_VERSION_TYPE_1_1_1: PYTHON_PACKAGE_SSL_1_1_1_VERSION,
    OPENSSL_VERSION_TYPE_3: PYTHON_PACKAGE_SSL_3_VERSION,
}

STEPS_SCRIPTS_DIR = pl.Path(__file__).parent.absolute() / "steps"


# Simple dataclass to store information about base environment step.
@dataclasses.dataclass
class BuildEnvInfo:
    # Script to run.
    script_name: str
    # Docker image to use.
    image: str


BUILD_ENV_CENTOS_6 = BuildEnvInfo(
    script_name="install_gcc_centos_6.sh", image="centos:6"
)
BUILD_ENV_CENTOS_7 = BuildEnvInfo(
    script_name="install_gcc_centos_7.sh", image="centos:7"
)

SUPPORTED_ARCHITECTURES = [
    Architecture.X86_64,
    Architecture.ARM64,
]

SUPPORTED_ARCHITECTURES_TO_BUILD_ENVIRONMENTS = {
    Architecture.X86_64: BUILD_ENV_CENTOS_6,
    Architecture.ARM64: BUILD_ENV_CENTOS_7,
}


# Version of the  Python build dependencies.
_PYTHON_BUILD_DEPENDENCIES_VERSIONS = {
    "XZ_VERSION": "5.2.6",
    "OPENSSL_1_1_1_VERSION": PYTHON_PACKAGE_SSL_VERSIONS[OPENSSL_VERSION_TYPE_1_1_1],
    "OPENSSL_3_VERSION": PYTHON_PACKAGE_SSL_VERSIONS[OPENSSL_VERSION_TYPE_3],
    "LIBFFI_VERSION": "3.4.2",
    "UTIL_LINUX_VERSION": "2.38",
    "NCURSES_VERSION": "6.3",
    "LIBEDIT_VERSION_COMMIT": "0cdd83b3ebd069c1dee21d81d6bf716cae7bf5da",  # tag - "upstream/3.1-20221030"
    "GDBM_VERSION": "1.23",
    "ZLIB_VERSION": "1.2.13",
    "BZIP_VERSION": "1.0.8",
}

# Step that downloads all Python dependencies.
DOWNLOAD_PYTHON_DEPENDENCIES = RunnerStep(
    name="download_build_dependencies",
    script_path=STEPS_SCRIPTS_DIR / "download_build_dependencies/download_build_dependencies.sh",
    tracked_files_globs=[
        STEPS_SCRIPTS_DIR / "download_build_dependencies/gnu-keyring.gpg",
        STEPS_SCRIPTS_DIR / "download_build_dependencies/gpgkey-5C1D1AA44BE649DE760A.gpg",
    ],
    base=DockerImageSpec(name="ubuntu:22.04", platform=DockerPlatform.AMD64.value),
    environment_variables={
        **_PYTHON_BUILD_DEPENDENCIES_VERSIONS,
        "PYTHON_VERSION": EMBEDDED_PYTHON_VERSION,
    },
)


def create_install_build_environment_steps() -> Dict[
    Architecture, EnvironmentRunnerStep
]:
    """
    Create steps that create build environment with gcc and other tools for python compilation.
    """
    steps = {}
    for architecture in SUPPORTED_ARCHITECTURES:
        run_in_remote_docker = architecture != Architecture.X86_64

        build_env_info = SUPPORTED_ARCHITECTURES_TO_BUILD_ENVIRONMENTS[architecture]

        step = EnvironmentRunnerStep(
            name=f"install_build_environment_{architecture.value}",
            script_path=STEPS_SCRIPTS_DIR / f"install_build_environment/{build_env_info.script_name}",
            base=DockerImageSpec(
                name=build_env_info.image,
                platform=architecture.as_docker_platform.value,
            ),
            run_in_remote_docker_if_available=run_in_remote_docker,
        )
        steps[architecture] = step

    return steps


# Steps that prepares build environment.
INSTALL_BUILD_ENVIRONMENT_STEPS = create_install_build_environment_steps()


def create_build_python_dependencies_steps() -> Dict[Architecture, RunnerStep]:
    """
    This function creates step that builds Python dependencies.
    """

    steps = {}
    for architecture in SUPPORTED_ARCHITECTURES:
        run_in_remote_docker = architecture != Architecture.X86_64

        step = RunnerStep(
            name=f"build_python_dependencies_{architecture.value}",
            script_path=STEPS_SCRIPTS_DIR / "build_python_dependencies.sh",
            base=INSTALL_BUILD_ENVIRONMENT_STEPS[architecture],
            dependency_steps={
                "DOWNLOAD_BUILD_DEPENDENCIES": DOWNLOAD_PYTHON_DEPENDENCIES
            },
            environment_variables={
                **_PYTHON_BUILD_DEPENDENCIES_VERSIONS,
            },
            run_in_remote_docker_if_available=run_in_remote_docker,
        )
        steps[architecture] = step

    return steps


# Steps that build Python dependencies.
BUILD_PYTHON_DEPENDENCIES_STEPS = create_build_python_dependencies_steps()


def create_build_openssl_steps(
    openssl_version_type: str,
) -> Dict[Architecture, RunnerStep]:
    """
    Create steps that build openssl library with given version.
    :param openssl_version_type: type of the OpenSSL, eg. 1_1_1, or 3
    :return:
    """
    steps = {}

    if openssl_version_type == OPENSSL_VERSION_TYPE_3:
        script_name = "build_openssl_3.sh"
    else:
        script_name = "build_openssl_1_1_1.sh"

    for architecture in SUPPORTED_ARCHITECTURES:
        run_in_remote_docker = architecture != Architecture.X86_64

        step = RunnerStep(
            name=f"build_openssl_{openssl_version_type}_{architecture.value}",
            script_path=STEPS_SCRIPTS_DIR / "build_openssl" / script_name,
            base=INSTALL_BUILD_ENVIRONMENT_STEPS[architecture],
            dependency_steps={
                "DOWNLOAD_BUILD_DEPENDENCIES": DOWNLOAD_PYTHON_DEPENDENCIES,
            },
            environment_variables={
                "OPENSSL_VERSION": PYTHON_PACKAGE_SSL_VERSIONS[openssl_version_type],
            },
            run_in_remote_docker_if_available=run_in_remote_docker,
        )
        steps[architecture] = step

    return steps


# Steps that build OpenSSL Python dependency, 1.1.1 and 3 versions.
BUILD_OPENSSL_1_1_1_STEPS = create_build_openssl_steps(
    openssl_version_type=OPENSSL_VERSION_TYPE_1_1_1
)
BUILD_OPENSSL_3_STEPS = create_build_openssl_steps(
    openssl_version_type=OPENSSL_VERSION_TYPE_3
)


def create_build_python_steps(
    build_openssl_steps: Dict[Architecture, RunnerStep],
    name_suffix: str,
) -> Dict[Architecture, RunnerStep]:
    """
    Function that creates step instances that build Python interpreter.
    :return: Result steps mapped to architectures..
    """

    steps = {}

    for architecture in SUPPORTED_ARCHITECTURES:
        run_in_remote_docker = architecture != Architecture.X86_64

        additional_options = ""

        # TODO: find out why enabling LTO optimization of ARM ends with error.
        # Disable it for now.
        if architecture == Architecture.X86_64:
            additional_options += "--with-lto"

        build_python = RunnerStep(
            name=f"build_python_{name_suffix}_{architecture.value}",
            script_path=STEPS_SCRIPTS_DIR / "build_python.sh",
            base=INSTALL_BUILD_ENVIRONMENT_STEPS[architecture],
            dependency_steps={
                "DOWNLOAD_BUILD_DEPENDENCIES": DOWNLOAD_PYTHON_DEPENDENCIES,
                "BUILD_PYTHON_DEPENDENCIES": BUILD_PYTHON_DEPENDENCIES_STEPS[
                    architecture
                ],
                "BUILD_OPENSSL": build_openssl_steps[architecture],
            },
            environment_variables={
                "PYTHON_VERSION": EMBEDDED_PYTHON_VERSION,
                "PYTHON_SHORT_VERSION": EMBEDDED_PYTHON_SHORT_VERSION,
                "ADDITIONAL_OPTIONS": additional_options,
                "INSTALL_PREFIX": PYTHON_INSTALL_PREFIX,
                "PIP_VERSION": EMBEDDED_PYTHON_PIP_VERSION,
            },
            run_in_remote_docker_if_available=run_in_remote_docker,
        )

        steps[architecture] = build_python

    return steps


# Create steps that build Python interpreter with OpenSSl 1.1.1 and 3
BUILD_PYTHON_WITH_OPENSSL_1_1_1_STEPS = create_build_python_steps(
    build_openssl_steps=BUILD_OPENSSL_1_1_1_STEPS, name_suffix="1_1_1"
)
BUILD_PYTHON_WITH_OPENSSL_3_STEPS = create_build_python_steps(
    build_openssl_steps=BUILD_OPENSSL_3_STEPS, name_suffix="3"
)


def create_build_dev_requirements_steps() -> Dict[Architecture, RunnerStep]:
    """
    Create steps that build all agent project requirements.
    """
    steps = {}
    for architecture in SUPPORTED_ARCHITECTURES:
        run_in_remote_docker = architecture != Architecture.X86_64

        if architecture == Architecture.X86_64:
            rust_target_platform = "x86_64-unknown-linux-gnu"
        elif architecture == Architecture.ARM64:
            rust_target_platform = "aarch64-unknown-linux-gnu"
        else:
            raise Exception(f"Unknown architecture '{architecture.value}'")

        build_dev_requirements_step = RunnerStep(
            name=f"build_dev_requirements_{architecture.value}",
            script_path=STEPS_SCRIPTS_DIR / "build_dev_requirements.sh",
            tracked_files_globs=[
                "dev-requirements-new.txt",
            ],
            base=INSTALL_BUILD_ENVIRONMENT_STEPS[architecture],
            dependency_steps={
                "BUILD_PYTHON_DEPENDENCIES": BUILD_PYTHON_DEPENDENCIES_STEPS[
                    architecture
                ],
                "BUILD_OPENSSL": BUILD_OPENSSL_1_1_1_STEPS[architecture],
                "BUILD_PYTHON": BUILD_PYTHON_WITH_OPENSSL_1_1_1_STEPS[architecture],
            },
            environment_variables={
                "RUST_VERSION": RUST_VERSION,
                "RUST_PLATFORM": rust_target_platform,
                "PYTHON_INSTALL_PREFIX": PYTHON_INSTALL_PREFIX,
            },
            run_in_remote_docker_if_available=run_in_remote_docker,
        )
        steps[architecture] = build_dev_requirements_step

    return steps


# Create steps that build and install all agent dev requirements.
BUILD_DEV_REQUIREMENTS_STEPS = create_build_dev_requirements_steps()


def create_build_agent_libs_venv_steps(
        requirements_file_content: str
) -> Dict[Architecture, RunnerStep]:
    """
    Function that creates steps that install agent requirement libraries.
    :return: Result steps dict mapped to architectures..
    """

    steps = {}
    for architecture in SUPPORTED_ARCHITECTURES:

        run_in_remote_docker = architecture != Architecture.X86_64

        build_agent_libs_step = RunnerStep(
            name=f"build_agent_libs_venv_{architecture.value}",
            script_path=STEPS_SCRIPTS_DIR / "build_agent_libs_venv.sh",
            tracked_files_globs=[
                "dev-requirements-new.txt",
            ],
            base=INSTALL_BUILD_ENVIRONMENT_STEPS[architecture],
            dependency_steps={
                "BUILD_OPENSSL": BUILD_OPENSSL_1_1_1_STEPS[architecture],
                "BUILD_PYTHON": BUILD_PYTHON_WITH_OPENSSL_1_1_1_STEPS[architecture],
                "BUILD_DEV_REQUIREMENTS": BUILD_DEV_REQUIREMENTS_STEPS[architecture],
            },
            environment_variables={
                "PYTHON_INSTALL_PREFIX": PYTHON_INSTALL_PREFIX,
                "SUBDIR_NAME": AGENT_SUBDIR_NAME,
                "REQUIREMENTS": requirements_file_content,
                "PIP_VERSION": EMBEDDED_PYTHON_PIP_VERSION,
            },
            run_in_remote_docker_if_available=run_in_remote_docker,
        )
        steps[architecture] = build_agent_libs_step

    return steps


def create_prepare_toolset_steps() -> Dict[Architecture, EnvironmentRunnerStep]:
    """
    Create steps that prepare environment with all needed tools.
    """
    steps = {}
    for architecture in SUPPORTED_ARCHITECTURES:
        base_image = DockerImageSpec(
            name="ubuntu:22.04", platform=architecture.as_docker_platform.value
        )

        prepare_toolset_step = EnvironmentRunnerStep(
            name=f"prepare_toolset_{architecture.value}",
            script_path=STEPS_SCRIPTS_DIR / "prepare_toolset.sh",
            base=base_image,
            dependency_steps={
                "BUILD_OPENSSL_1_1_1": BUILD_OPENSSL_1_1_1_STEPS[architecture],
                "BUILD_PYTHON_1_1_1": BUILD_PYTHON_WITH_OPENSSL_1_1_1_STEPS[
                    architecture
                ],
                "BUILD_OPENSSL_3": BUILD_OPENSSL_3_STEPS[architecture],
                "BUILD_PYTHON_3": BUILD_PYTHON_WITH_OPENSSL_3_STEPS[architecture],
                "BUILD_DEV_REQUIREMENTS": BUILD_DEV_REQUIREMENTS_STEPS[architecture],
            },
            environment_variables={
                "PYTHON_INSTALL_PREFIX": PYTHON_INSTALL_PREFIX,
                "FPM_VERSION": "1.14.2",
            },
        )

        steps[architecture] = prepare_toolset_step

    return steps


PREPARE_TOOLSET_STEPS = create_prepare_toolset_steps()


def create_prepare_python_environment_steps() -> Dict[
    Architecture, EnvironmentRunnerStep
]:
    """
    Create steps that prepare environment with all needed tools.
    """
    steps = {}
    for architecture in SUPPORTED_ARCHITECTURES:

        prepare_toolset_step = EnvironmentRunnerStep(
            name=f"prepare_python_environment_{architecture.value}",
            script_path=STEPS_SCRIPTS_DIR / "prepare_python_environment.sh",
            base=DockerImageSpec(
                name=SUPPORTED_ARCHITECTURES_TO_BUILD_ENVIRONMENTS[architecture].image,
                platform=architecture.as_docker_platform.value,
            ),
            dependency_steps={
                "BUILD_OPENSSL_1_1_1": BUILD_OPENSSL_1_1_1_STEPS[architecture],
                "BUILD_PYTHON_1_1_1": BUILD_PYTHON_WITH_OPENSSL_1_1_1_STEPS[
                    architecture
                ],
                "BUILD_OPENSSL_3": BUILD_OPENSSL_3_STEPS[architecture],
                "BUILD_PYTHON_3": BUILD_PYTHON_WITH_OPENSSL_3_STEPS[architecture],
                "BUILD_DEV_REQUIREMENTS": BUILD_DEV_REQUIREMENTS_STEPS[architecture],
            },
            environment_variables={
                "PYTHON_INSTALL_PREFIX": PYTHON_INSTALL_PREFIX,
            },
        )

        steps[architecture] = prepare_toolset_step

    return steps


PREPARE_PYTHON_ENVIRONMENT_STEPS = create_prepare_python_environment_steps()