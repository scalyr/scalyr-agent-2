from agent_build_refactored.tools.constants import Architecture, DockerPlatform, PYTHON_PACKAGE_SSL_VERSION, EMBEDDED_PYTHON_VERSION, AGENT_SUBDIR_NAME
from agent_build_refactored.tools.runner import EnvironmentRunnerStep, ArtifactRunnerStep, DockerImageSpec, GitHubActionsSettings

EMBEDDED_PYTHON_SHORT_VERSION = ".".join(EMBEDDED_PYTHON_VERSION.split(".")[:2])


# Step that prepares initial environment for X86_64 build environment.
_PREPARE_BUILD_BASE_X86_64 = EnvironmentRunnerStep(
        name="install_gcc_7",
        script_path="agent_build_refactored/managed_packages/scalyr_agent_python3/embedded_python/build_steps/install_gcc_7_amd64.sh",
        base=DockerImageSpec(
            name="centos:6",
            platform=DockerPlatform.AMD64.value
        ),
        github_actions_settings=GitHubActionsSettings(
            cacheable=True
        )
    )

# Step that prepares initial environment for X86_64 build environment.
_PREPARE_BUILD_BASE_ARM64 = EnvironmentRunnerStep(
        name="install_gcc_7_arm64",
        script_path="agent_build_refactored/managed_packages/scalyr_agent_python3/embedded_python/build_steps/install_gcc_7_arm64.sh",
        base=DockerImageSpec(
            name="centos:7",
            platform=DockerPlatform.ARM64.value
        ),
        github_actions_settings=GitHubActionsSettings(
            cacheable=True,
            run_in_remote_docker=True
        )
    )


_PREPARE_BUILD_BASE_STEPS = {
    Architecture.X86_64: _PREPARE_BUILD_BASE_X86_64,
    Architecture.ARM64: _PREPARE_BUILD_BASE_ARM64
}

def create_build_dependencies_step(
        architecture: Architecture,
        run_in_remote_docker: bool = False

) -> EnvironmentRunnerStep:
    """
    This function creates step that installs Python build requirements, to a given environment.
    :param base_image: Environment step runner with the target environment.
    :param run_in_remote_docker: If possible, run this step in remote docker engine.
    :return: Result step.
    """

    build_dependencies_versions = {
        "XZ_VERSION": "5.2.6",
        "PERL_VERSION": "5.36.0",
        "TEXINFO_VERSION": "6.8",
        "M4_VERSION": "1.4.19",
        "LIBTOOL_VERSION": "2.4.6",
        "AUTOCONF_VERSION": "2.71",
        "AUTOMAKE_VERSION": "1.16",
        "HELP2MAN_VERSION": "1.49.2",
        "LZMA_VERSION": "4.32.7",
        "OPENSSL_VERSION": PYTHON_PACKAGE_SSL_VERSION,
        "LIBFFI_VERSION": "3.4.2",
        "UTIL_LINUX_VERSION": "2.38",
        "NCURSES_VERSION": "6.3",
        "LIBEDIT_VERSION": "20210910-3.1",
        "GDBM_VERSION": "1.23",
        "ZLIB_VERSION": "1.2.13",
        "BZIP_VERSION": "1.0.8",
    }

    download_build_dependencies = ArtifactRunnerStep(
        name="download_build_dependencies",
        script_path="agent_build_refactored/managed_packages/scalyr_agent_python3/embedded_python/build_steps/download_build_dependencies/download_build_dependencies.sh",
        tracked_files_globs=[
            "agent_build_refactored/managed_packages/scalyr_agent_python3/embedded_python/build_steps/download_build_dependencies/gnu-keyring.gpg",
            "agent_build_refactored/managed_packages/scalyr_agent_python3/embedded_python/build_steps/download_build_dependencies/gpgkey-5C1D1AA44BE649DE760A.gpg",
        ],
        base=DockerImageSpec(
            name="ubuntu:22.04",
            platform=DockerPlatform.AMD64.value
        ),
        environment_variables={
            **build_dependencies_versions
        }

    )
    openssl_configure_platforms = {
        Architecture.X86_64: "linux-x86_64",
        Architecture.ARM64: "linux-aarch64"
    }

    base_image = _PREPARE_BUILD_BASE_STEPS[architecture]

    return EnvironmentRunnerStep(
        name="install_build_dependencies",
        script_path="agent_build_refactored/managed_packages/scalyr_agent_python3/embedded_python/build_steps/install_build_dependencies.sh",
        base=base_image,
        required_steps={
            "DOWNLOAD_BUILD_DEPENDENCIES": download_build_dependencies
        },
        environment_variables={
            "OPENSSL_CONFIGURE_PLATFORM": openssl_configure_platforms[base_image.architecture],
            **build_dependencies_versions,
        },
        github_actions_settings=GitHubActionsSettings(
            run_in_remote_docker=run_in_remote_docker
        )
    )

# Step that installs Python build requirements to the build environment.
INSTALL_BUILD_DEPENDENCIES_STEPS = {
    Architecture.X86_64: create_build_dependencies_step(
        architecture=Architecture.X86_64,
    ),
    Architecture.ARM64: create_build_dependencies_step(
        architecture=Architecture.ARM64,
        run_in_remote_docker=True
    )
}


def create_build_embedded_python_step(
        architecture: Architecture,
        libssl_dir: str,
        run_in_remote_docker: bool = False
) -> ArtifactRunnerStep:
    """
    Function that creates step instance that build Python interpreter.
    :param base_step: Step with environment where to build.
    :param libssl_dir: Name of the directory where ssl library is located because it may vary on some distibutions.
    :param run_in_remote_docker: If possible, run this step in remote docker engine.
    :return: Result step.
    """

    python_config_architectures = {
        Architecture.X86_64: "x86_64",
        Architecture.ARM64: "aarch64"
    }

    base_step = INSTALL_BUILD_DEPENDENCIES_STEPS[architecture]

    return ArtifactRunnerStep(
        name=f"build_python_embedded_{architecture.value}",
        script_path="agent_build_refactored/managed_packages/scalyr_agent_python3/embedded_python/build_steps/build_python.sh",
        tracked_files_globs=[
            "agent_build_refactored/managed_packages/scalyr_agent_python3/embedded_python/files/python3",
        ],
        base=base_step,
        environment_variables={
            "PYTHON_VERSION": EMBEDDED_PYTHON_VERSION,
            "PYTHON_SHORT_VERSION": EMBEDDED_PYTHON_SHORT_VERSION,
            "PYTHON_INSTALL_PREFIX": "/usr",
            "LIBSSL_DIR": libssl_dir,
            "PYTHON_CONFIG_ARCHITECTURE": python_config_architectures[base_step.architecture],
            "SUBDIR_NAME": AGENT_SUBDIR_NAME
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True,
            run_in_remote_docker=run_in_remote_docker
        )
    )

# Create steps that builds Python interpreter.
BUILD_EMBEDDED_PYTHON_STEPS = {
    Architecture.X86_64: create_build_embedded_python_step(
        architecture=Architecture.X86_64,
        libssl_dir="/usr/local/lib64"
    ),
    Architecture.ARM64: create_build_embedded_python_step(
        architecture=Architecture.ARM64,
        libssl_dir="/usr/local/lib",
        run_in_remote_docker=True
    )
}




def create_build_agent_dev_requirements_step(
        architecture: Architecture,
        run_in_remote_docker: bool = False
):
    """
    Function that creates step that installs agent requirement libraries.
    :param base_step: Step with environment where to build.
    :param build_python_step: Required step that builds Python.
    :param run_in_remote_docker: If possible, run this step in remote docker engine.
    :return: Result step.
    """

    base_step = INSTALL_BUILD_DEPENDENCIES_STEPS[architecture]
    build_python_step = BUILD_EMBEDDED_PYTHON_STEPS[architecture]

    return ArtifactRunnerStep(
        name=f"build_agent_dev_requirements_{base_step.architecture.value}",
        script_path="agent_build_refactored/managed_packages/scalyr_agent_python3/embedded_python/build_steps/build_dev_requirements.sh",
        tracked_files_globs=[
            "dev-requirements-new.txt"
        ],
        base=base_step,
        required_steps={
            "BUILD_PYTHON": build_python_step
        },
        environment_variables={
            "PYTHON_SHORT_VERSION": EMBEDDED_PYTHON_SHORT_VERSION,
            "RUST_VERSION": "1.63.0",
            "SUBDIR_NAME": AGENT_SUBDIR_NAME
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True,
            run_in_remote_docker=run_in_remote_docker
        )
    )


BUILD_AGENT_DEV_REQUIREMENTS_STEPS = {
    Architecture.X86_64: create_build_agent_dev_requirements_step(
        architecture=Architecture.X86_64
    ),
    Architecture.ARM64: create_build_agent_dev_requirements_step(
        architecture=Architecture.ARM64,
        run_in_remote_docker=True
    )
}


def create_prepare_toolset_step(
    architecture: Architecture,
    run_in_remote_docker: bool = False
):
    """
    Create step that prepare environment with all needed tools.
    """

    base_docker_image = DockerImageSpec(
        name="ubuntu:22.04",
        platform=architecture.as_docker_platform.value
    )

    return EnvironmentRunnerStep(
        name=f"prepare_toolset_{architecture.value}",
        script_path="agent_build_refactored/managed_packages/scalyr_agent_python3/embedded_python/build_steps/prepare_toolset.sh",
        tracked_files_globs=[
            "dev-requirements-new.txt",
        ],
        base=base_docker_image,
        required_steps={
            "BUILD_PYTHON": BUILD_EMBEDDED_PYTHON_STEPS[architecture],
            "BUILD_AGENT_DEV_REQUIREMENTS": BUILD_AGENT_DEV_REQUIREMENTS_STEPS[architecture]
        },
        environment_variables={
            "SUBDIR_NAME": AGENT_SUBDIR_NAME,
            "FPM_VERSION": "1.14.2",
            "PACKAGECLOUD_VERSION": "0.3.11",
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True,
            pre_build_in_separate_job=True,
            run_in_remote_docker=run_in_remote_docker
        )
)


PREPARE_TOOLSET_STEPS = {
    Architecture.X86_64: create_prepare_toolset_step(
        architecture=Architecture.X86_64,
    ),
    Architecture.ARM64: create_prepare_toolset_step(
        architecture=Architecture.ARM64
    )
}


def create_agent_python3_embedded_package_root_step(
        architecture: Architecture,
) -> ArtifactRunnerStep:
    return ArtifactRunnerStep(
        name="create_agent_python3_embedded_package_root",
        script_path="agent_build_refactored/managed_packages/scalyr_agent_python3/embedded_python/build_steps/build_package_root.sh",
        tracked_files_globs=[
            "agent_build_refactored/managed_packages/scalyr_agent_python3/embedded_python/files/python3",
        ],
        base=INSTALL_BUILD_DEPENDENCIES_STEPS[architecture],
        required_steps={
           "BUILD_PYTHON": BUILD_EMBEDDED_PYTHON_STEPS[architecture],
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True,
        )
    )


CREATE_AGENT_PYTHON3_EMBEDDED_PACKAGE_ROOT_STEPS = {
    Architecture.X86_64: create_agent_python3_embedded_package_root_step(
        architecture=Architecture.X86_64
    ),
    Architecture.ARM64: create_agent_python3_embedded_package_root_step(
        architecture=Architecture.ARM64
    ),
}

CREATE_AGENT_PYTHON3_SYSTEM_PACKAGE_ROOT_STEP = ArtifactRunnerStep(
    name="create_agent_python3_system_package_root",
    script_path="agent_build_refactored/managed_packages/scalyr_agent_python3/system_python/build_steps/build_package_root.sh",
    tracked_files_globs=[
        "agent_build_refactored/managed_packages/scalyr_agent_python3/system_python/files/python3",
    ],
    base=PREPARE_TOOLSET_STEPS[Architecture.X86_64],
    environment_variables={
        "SUBDIR_NAME": AGENT_SUBDIR_NAME
    },
    github_actions_settings=GitHubActionsSettings(
        cacheable=True,
    )


)
