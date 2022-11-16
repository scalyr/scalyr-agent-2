from agent_build_refactored.tools.runner import EnvironmentRunnerStep, ArtifactRunnerStep, GitHubActionsSettings, DockerImageSpec
from agent_build_refactored.tools.constants import EMBEDDED_PYTHON_VERSION, EMBEDDED_PYTHON_SHORT_VERSION, Architecture, DockerPlatform

install_build_dependencies_steps = {}




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


# def create_prepare_python_environment_step(
#         base_image_step: EnvironmentRunnerStep,
#         build_python_step: ArtifactRunnerStep,
#
# ):
#     return EnvironmentRunnerStep(
#         name="prepare_python_environment",
#         script_path="agent_build_refactored/tools/build_python/steps/prepare_python_environment.sh",
#         tracked_files_globs=[
#             "agent_build/requirement-files/*.txt",
#             "dev-requirements.txt"
#         ],
#         base=base_image_step,
#         required_steps={
#             "BUILD_PYTHON": build_python_step,
#         },
#         github_actions_settings=GitHubActionsSettings(
#             cacheable=True
#         )
#     )
#
#
#
# PREPARE_PYTHON_ENVIRONMENT_GLIBC_X64 = create_prepare_python_environment_step(
#     base_image_step=INSTALL_BUILD_DEPENDENCIES_GLIBC_X86_64,
#     build_python_step=BUILD_PYTHON_GLIBC_X86_64,
# )









