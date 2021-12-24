# Copyright 2014-2021 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import shutil
import subprocess
import pathlib as pl
from typing import List

import mock
import pytest

from agent_build.tools import constants
from agent_build.tools import common
from agent_build.tools.environment_deployments import deployments

common.init_logging()

_PARENT_REL_DIR = pl.Path(__file__).parent.relative_to(constants.SOURCE_ROOT)
_REL_EXAMPLE_DEPLOYMENT_STEPS_PATH = _PARENT_REL_DIR / "fixtures/example_steps"


# This is just an example of the deployment step. It is used only in tests.
class ExampleStep(deployments.ShellScriptDeploymentStep):
    @property
    def script_path(self) -> pl.Path:
        return _REL_EXAMPLE_DEPLOYMENT_STEPS_PATH / "install-requirements-and-download-webdriver.sh"

    @property
    def _tracked_file_globs(self) -> List[pl.Path]:
        return [
            *super(ExampleStep, self)._tracked_file_globs,
            _REL_EXAMPLE_DEPLOYMENT_STEPS_PATH / "requirements-*.txt",
    ]


@pytest.fixture
def example_deployment(request):

    if request.param == "in_docker":
        name = "example_environment_in_docker"
        # This is the same example of the deployment by that run in docker. It is used only for tests.
        deployment = deployments.Deployment(
            name=name,
            step_classes=[ExampleStep],
            architecture=constants.Architecture.X86_64,
            base_docker_image="python:3.8",
        )
    else:
        name = "example_environment"
        # This is just an example of the deployment. It is used only for tests.
        deployment = deployments.Deployment(
            name=name,
            step_classes=[ExampleStep],
        )
    yield deployment
    deployments.ALL_DEPLOYMENTS.pop(name)


@pytest.fixture
def in_ci_cd(request):
    original_in_ci_cd = common.IN_CICD
    common.IN_CICD = request.param
    yield
    common.IN_CICD = original_in_ci_cd


@pytest.mark.parametrize(
    ["example_deployment"], [["locally"], ["in_docker"]], indirect=True
)
@pytest.mark.parametrize(
    ["in_ci_cd"], [[True]], indirect=True
)
def test_example_deployment(
    example_deployment: deployments.Deployment,
    in_ci_cd: bool
):
    example_deployment_step = example_deployment.steps[0]
    deployment_step_cache_path = example_deployment_step.cache_directory
    if deployment_step_cache_path.exists():
        shutil.rmtree(deployment_step_cache_path)

    if example_deployment.in_docker:
        subprocess.check_call(
            ["docker", "image", "rm", "-f", example_deployment.result_image_name]
        )

    # mock real save docker image function to skip real image saving and to save time.
    def step_save_image_mock(image_name: str, output_path: pl.Path):
        output_path.touch()

    with mock.patch.object(deployments, "save_docker_image", step_save_image_mock):
        example_deployment.deploy()

    # Check if the deployment created all needed cache directories.
    if example_deployment.in_docker:
        # IF that's a in docker deployment, then look for a serialized docker result image.
        cached_docker_image_path = (
            deployment_step_cache_path / example_deployment_step.result_image_name
        )
        assert cached_docker_image_path.is_file()
    else:
        # If not in docker, then look for directories that were cached by shell script.
        pip_cache_directory = deployment_step_cache_path / "pip"
        assert pip_cache_directory.is_dir()

        webdriver_cache_directory = deployment_step_cache_path / "webdriver"
        assert webdriver_cache_directory.is_dir()

        # also check if those cache directories are not empty
        assert list(pip_cache_directory.iterdir())
        assert list(webdriver_cache_directory.iterdir())

    assert example_deployment_step.cache_key == deployment_step_cache_path.name


def test_deployment_step_with_untracked_file(caplog, capsys):
    """
    Run another invalid deployment that tries to access file that is not tracked.
    """

    class ExampleInvalidStepWithUntrackedFiles(deployments.ShellScriptDeploymentStep):
        @property
        def script_path(self) -> pl.Path:
            return _REL_EXAMPLE_DEPLOYMENT_STEPS_PATH / "install-with-untracked-file.sh"

    deployment = deployments.Deployment(
        name="example_environment_untracked",
        step_classes=[ExampleInvalidStepWithUntrackedFiles],
    )

    try:
        with pytest.raises(deployments.DeploymentStepError):
            deployment.deploy()

        captured_output = capsys.readouterr()

        assert "No such file or directory" in captured_output.err
        assert "VERSION" in captured_output.err
        assert "HINT: Make sure that you have specified all files." in caplog.text
    finally:
        deployments.ALL_DEPLOYMENTS.pop("example_environment_untracked")
