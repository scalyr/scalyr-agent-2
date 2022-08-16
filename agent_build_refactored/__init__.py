from agent_build_refactored.tools.runner import (
    Runner,
    EnvironmentRunnerStep,
    GitHubActionsSettings,
)
from agent_build_refactored.tools.constants import SOURCE_ROOT, AGENT_BUILD_PATH


# Step that runs small script which installs requirements for the test/dev environment.
INSTALL_TEST_REQUIREMENT_STEP = EnvironmentRunnerStep(
    name="install_test_requirements",
    script_path=AGENT_BUILD_PATH / "scripts/steps/deploy-test-environment.sh",
    tracked_files_globs=[AGENT_BUILD_PATH / "requirement-files/*.txt"],
    github_actions_settings=GitHubActionsSettings(cacheable=True),
)


class BuildTestEnvironment(Runner):
    BASE_ENVIRONMENT = INSTALL_TEST_REQUIREMENT_STEP
