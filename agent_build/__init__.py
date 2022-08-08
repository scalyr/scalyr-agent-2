from agent_build.tools.environment_deployments.deployments import CacheableBuilder, ShellScriptDeploymentStep, EnvironmentShellScriptStep
from agent_build.tools.constants import Architecture, SOURCE_ROOT


# Step that runs small script which installs requirements for the test/dev environment.
INSTALL_TEST_REQUIREMENT_STEP = EnvironmentShellScriptStep(
    name="install_test_requirements",
    script_path= SOURCE_ROOT / "agent_build/tools/environment_deployments/steps/deploy-test-environment.sh",
    tracked_file_globs=[SOURCE_ROOT / "agent_build/requirement-files/*.txt"],
    cacheable=True
)


class BuildTestEnvironment(CacheableBuilder):
    BASE_ENVIRONMENT = INSTALL_TEST_REQUIREMENT_STEP