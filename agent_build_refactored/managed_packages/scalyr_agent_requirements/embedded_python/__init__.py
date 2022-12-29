
from agent_build_refactored.tools.constants import Architecture, REQUIREMENTS_COMMON, REQUIREMENTS_COMMON_PLATFORM_DEPENDENT
from agent_build_refactored.tools.runner import ArtifactRunnerStep, GitHubActionsSettings
from agent_build_refactored.managed_packages.scalyr_agent_python3 import BUILD_EMBEDDED_PYTHON_STEPS, BUILD_AGENT_DEV_REQUIREMENTS_STEPS, INSTALL_BUILD_DEPENDENCIES_STEPS


def create_build_embedded_python_venv(
        architecture: Architecture,
        run_in_remote_docker: bool = False
):
    return ArtifactRunnerStep(
        name=f"build_embedded_python_wheels_{architecture.value}",
        script_path="agent_build_refactored/managed_packages/scalyr_agent_libs/embedded_python/build_steps/build_wheels.sh",
        base=INSTALL_BUILD_DEPENDENCIES_STEPS[architecture],
        required_steps={
            "BUILD_PYTHON": BUILD_EMBEDDED_PYTHON_STEPS[architecture],
            "BUILD_AGENT_DEV_REQUIREMENTS": BUILD_AGENT_DEV_REQUIREMENTS_STEPS[architecture]
        },
        environment_variables={
            "REQUIREMENTS_COMMON": REQUIREMENTS_COMMON,
            "REQUIREMENTS_COMMON_PLATFORM_DEPENDENT": REQUIREMENTS_COMMON_PLATFORM_DEPENDENT,
            "RUST_VERSION": "1.63.0",
        },
        github_actions_settings=GitHubActionsSettings(
            cacheable=True,
            run_in_remote_docker=run_in_remote_docker
        )
    )


BUILD_WHEELS_STEP = {
    Architecture.X86_64: create_build_embedded_python_venv(
        architecture=Architecture.X86_64,
    ),
    Architecture.ARM64: create_build_embedded_python_venv(
        architecture=Architecture.ARM64,
        run_in_remote_docker=True
    )
}