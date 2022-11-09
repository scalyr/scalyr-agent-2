from agent_build_refactored.tools.runner import EnvironmentRunnerStep, ArtifactRunnerStep, GitHubActionsSettings, \
    DockerImageSpec
from agent_build_refactored.tools.constants import DockerPlatform
from agent_build_refactored.tools.build_python.python_builder import INSTALL_BUILD_DEPENDENCIES_GLIBC_X64, \
    BUILD_PYTHON_GLIBC_X64





def create_prepare_build_environment_step(
        base_image_spec: DockerImageSpec,
        build_python_step: ArtifactRunnerStep
):
    return EnvironmentRunnerStep(
        name="prepare_package_build_environment",
        script_path="/Users/arthur/work/agents/scalyr-agent-2/agent_build_refactored/tools/prepare_build_environment/steps/prepare_build_environment.sh",
        base=base_image_spec,
        required_steps={
            "BUILD_PYTHON": build_python_step,
        },
        environment_variables={
            "FPM_VERSION": "1.14.2",
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True
        )
    )


PREPARE_BUILD_ENVIRONMENT_GLIBC_X64 = create_prepare_build_environment_step(
    base_image_spec=DockerImageSpec(
        name="ubuntu:22.04",
        platform=DockerPlatform.AMD64.value
    ),
    build_python_step=BUILD_PYTHON_GLIBC_X64
)

