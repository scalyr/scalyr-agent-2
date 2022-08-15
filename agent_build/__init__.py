from agent_build.tools.runner import (
    Runner,
    EnvironmentRunnerStep,
    GitHubActionsSettings,
)
from agent_build.tools.constants import Architecture, SOURCE_ROOT


# Step that runs small script which installs requirements for the test/dev environment.
INSTALL_TEST_REQUIREMENT_STEP = EnvironmentRunnerStep(
    name="install_test_requirements",
    script_path=SOURCE_ROOT / "agent_build/scripts/steps/deploy-test-environment.sh",
    tracked_files_globs=[SOURCE_ROOT / "agent_build/requirement-files/*.txt"],
    github_actions_settings=GitHubActionsSettings(cacheable=True),
)


class BuildTestEnvironment(Runner):
    BASE_ENVIRONMENT = INSTALL_TEST_REQUIREMENT_STEP
