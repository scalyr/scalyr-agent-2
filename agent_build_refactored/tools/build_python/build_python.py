from agent_build_refactored.tools.runner import EnvironmentRunnerStep, ArtifactRunnerStep, GitHubActionsSettings, DockerImageSpec
from agent_build_refactored.tools.constants import EMBEDDED_PYTHON_VERSION, EMBEDDED_PYTHON_SHORT_VERSION, Architecture, DockerPlatform

install_build_dependencies_steps = {}

INSTALL_GCC_7_GLIBC_X86_64 = EnvironmentRunnerStep(
        name="install_gcc_7",
        script_path="agent_build_refactored/tools/build_python/steps/install_gcc_7.sh",
        base=DockerImageSpec(
            name="centos:6",
            platform=DockerPlatform.AMD64.value
        ),
        github_actions_settings=GitHubActionsSettings(
            cacheable=True
        )
    )


def create_build_dependencies_step(
        base_image: EnvironmentRunnerStep
):

    return EnvironmentRunnerStep(
        name="install_build_dependencies",
        script_path="agent_build_refactored/tools/build_python/steps/install_build_dependencies.sh",
        base=base_image,
        environment_variables={
            "PERL_VERSION": "5.36.0",
            "ZX_VERSION": "5.2.6",
            "TEXTINFO_VERSION": "6.8",
            "M4_VERSION": "1.4.19",
            "LIBTOOL_VERSION": "2.4.6",
            "AUTOCONF_VERSION": "2.71",
            "AUTOMAKE_VERSION": "1.16",
            "HELP2MAN_VERSION": "1.49.2",
            "LIBLZMA_VERSION": "4.32.7",
            "OPENSSL_VERSION": "1.1.1k",
            "LIBFFI_VERSION": "3.4.2",
            "UTIL_LINUX_VERSION": "2.38",
            "NCURSES_VERSION": "6.3",
            "LIBEDIT_VERSION": "20210910-3.1",
            "GDBM_VERSION": "1.23",
            "ZLIB_VERSION": "1.2.13",
            "BZIP_VERSION": "1.0.8",
            "RUST_VERSION": "1.63.0",
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True
        )
    )


INSTALL_BUILD_DEPENDENCIES_GLIBC_X86_64 = create_build_dependencies_step(
    base_image=INSTALL_GCC_7_GLIBC_X86_64
)


def create_build_python_step(
        base_step: EnvironmentRunnerStep
):
    return ArtifactRunnerStep(
        name="build_python",
        script_path="agent_build_refactored/tools/build_python/steps/build_python.sh",
        tracked_files_globs=[
            "agent_build_refactored/tools/build_python/files/scalyr-agent-python",
            "agent_build/requirement-files/*.txt",
            "dev-requirements.txt"
        ],
        base=base_step,
        environment_variables={
            "PYTHON_VERSION": EMBEDDED_PYTHON_VERSION,
            "PYTHON_SHORT_VERSION": EMBEDDED_PYTHON_SHORT_VERSION,
            "PYTHON_INSTALL_PREFIX": "/usr",
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True
        )
    )


BUILD_PYTHON_GLIBC_X86_64 = create_build_python_step(
    base_step=INSTALL_BUILD_DEPENDENCIES_GLIBC_X86_64
)


def create_install_rust_step(base_image: EnvironmentRunnerStep):
    return EnvironmentRunnerStep(
        name="install_rust",
        script_path="agent_build_refactored/tools/build_python/steps/install_rust.sh",
        base=base_image,
        environment_variables={
            "RUST_VERSION": "1.63.0",
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True
        )

    )


# INSTALL_RUST_GLIBC_X64 = create_install_rust_step(
#     base_image=INSTALL_BUILD_DEPENDENCIES_GLIBC_X64
# )


def create_prepare_python_environment_step(
        base_image_step: EnvironmentRunnerStep,
        build_python_step: ArtifactRunnerStep,

):
    return EnvironmentRunnerStep(
        name="prepare_python_environment",
        script_path="agent_build_refactored/tools/build_python/steps/prepare_python_environment.sh",
        tracked_files_globs=[
            "agent_build/requirement-files/*.txt",
            "dev-requirements.txt"
        ],
        base=base_image_step,
        required_steps={
            "BUILD_PYTHON": build_python_step,
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True
        )
    )



PREPARE_PYTHON_ENVIRONMENT_GLIBC_X64 = create_prepare_python_environment_step(
    base_image_step=INSTALL_BUILD_DEPENDENCIES_GLIBC_X86_64,
    build_python_step=BUILD_PYTHON_GLIBC_X86_64,
)









