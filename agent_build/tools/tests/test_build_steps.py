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
import collections
import dataclasses
import shutil
import subprocess
import pathlib as pl
import tempfile
import textwrap
from typing import List, Optional, Union

import mock
import pytest

from agent_build.tools import constants
from agent_build.tools import common
from agent_build.tools.environment_deployments import deployments
from agent_build.tools import build_step

common.init_logging()

_PARENT_DIR = pl.Path(__file__).parent
_BUILD_STEPS_DIR = _PARENT_DIR / "fixtures/build_step_scripts"


def get_initial_artifact_class(
):
    class InitialArtifactStep(build_step.ScriptBuildStep):
        IS_BASE_STEP = True

        def __init__(
                self,
                input_value: str,
                script_path: pl.Path,
                base_step: Optional[Union[build_step.ScriptBuildStep.DockerImageSpec, str]]=None,
                dependency_steps=None
        ):
            super(InitialArtifactStep, self).__init__(
                script_path=script_path,
                base_step=base_step,
                dependency_steps=dependency_steps
            )

            self._add_input("INPUT", input_value)

            if isinstance(base_step, build_step.ScriptBuildStep.DockerImageSpec):
                self._add_input("IN_DOCKER", "1")

    return InitialArtifactStep


def test_artifact_build_shell_step():
    step_cls = get_initial_artifact_class(
        script_suffix="sh"
    )

    step = step_cls(
        input_value="TEST"
    )

    step.run()

    result_file_path = step.output_directory / "result.txt"
    assert result_file_path.exists()
    assert result_file_path.read_text() == "TEST_shell\n"


_DEBIAN_OS_RELEASE_CONTENT = """PRETTY_NAME="Debian GNU/Linux 11 (bullseye)"
NAME="Debian GNU/Linux"
VERSION_ID="11"
VERSION="11 (bullseye)"
VERSION_CODENAME=bullseye
ID=debian
HOME_URL="https://www.debian.org/"
SUPPORT_URL="https://www.debian.org/support"
BUG_REPORT_URL="https://bugs.debian.org/"
"""

@pytest.fixture(scope="session")
def test_dir():
    temp_dir = constants.SOURCE_ROOT / "build_test"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)

    temp_dir.mkdir(parents=True)
    yield temp_dir

@dataclasses.dataclass
class StepFixture:
    step: dict

def _get_docker_image_spec_or_none(
        docker_image: str = None
):
    if not docker_image:
        return None

    return build_step.ScriptBuildStep.DockerImageSpec(
        name=docker_image,
        architecture=constants.Architecture.X86_64
    )


class BaseStep(build_step.ScriptBuildStep):
    IS_BASE_STEP = True

def spawn_step(
        script_type,
        in_docker,
        input_value: str,
        result_file: pl.Path,
        build_root: pl.Path,
        is_base_step: bool
):

    if in_docker:
        if script_type == "shell":
            docker_image = "debian:bullseye"
        else:
            docker_image = "python:3.8-bullseye"
    else:
        docker_image = None

    if script_type == "shell":
        script_ext = ".sh"

    else:
        script_ext = ".py"

    if is_base_step:
        script_path = _BUILD_STEPS_DIR / f"base_step{script_ext}"
        step = build_step.PrepareEnvironmentStep(
            script_path=script_path,
            build_root=build_root,

            base_step=_get_docker_image_spec_or_none(docker_image),
            additional_settings={
                "INPUT": input_value,
                "RESULT_FILE_PATH": str(result_file)
            }
        )


    return step


_BASE_STEP_SCRIPTS={
    "shell": _BUILD_STEPS_DIR / "base_step.sh",
    "python": _BUILD_STEPS_DIR / "base_step.py"
}

_FINAL_STEP_SCRIPTS={
    "shell": _BUILD_STEPS_DIR / "final_step.sh",
    "python": _BUILD_STEPS_DIR / "final_step.py"
}

_DEPENDENCY_STEP_SCRIPTS={
    "shell": _BUILD_STEPS_DIR / "dependency_step.sh",
    "python": _BUILD_STEPS_DIR / "dependency_step.py"
}

_DOCKER_IMAGES_TO_SCRIPT_TYPES = {
    "shell": "debian:bullseye",
    "python": "python:3.8-bullseye"
}
@pytest.mark.parametrize(
    ["dependency_script_type", "dependency_in_docker"],
    [
        ("shell", True),
        ("shell", False),
        ("python", True),
        ("python", False)
    ]
)
@pytest.mark.parametrize(
    ["in_docker"], [(False,), (True,)]
)
@pytest.mark.parametrize(
    ["script_type"], [("shell",), ("python",)]
)
def test_base_step(
        script_type,
        in_docker,
        dependency_script_type,
        dependency_in_docker,
        tmp_path
):
    # Set path to a file that has to be created during the run of the base step.
    if in_docker:
        base_step_result_file_path = pl.Path("/tmp/base.txt")
        docker_image = _get_docker_image_spec_or_none(
            _DOCKER_IMAGES_TO_SCRIPT_TYPES[script_type]
        )
    else:
        base_step_result_file_path = tmp_path / "base.txt"
        docker_image = None

    build_root = pl.Path("/Users/arthur/work/agents/scalyr-agent-2/build_test")
    base_step = build_step.PrepareEnvironmentStep(
            script_path=_BASE_STEP_SCRIPTS[script_type],
            build_root=build_root,
            base_step=docker_image,
            additional_settings={
                "INPUT": "BASE",

                "BASE_RESULT_FILE_PATH": str(base_step_result_file_path)
            }
        )

    if dependency_in_docker:
        dependency_docker_image = _get_docker_image_spec_or_none(
            _DOCKER_IMAGES_TO_SCRIPT_TYPES[dependency_script_type]
        )
    else:
        dependency_docker_image = None

    # Create a dependency step. It has to produce a file that has to be used in the final step.
    dependency_step = build_step.ArtifactStep(
        script_path=_DEPENDENCY_STEP_SCRIPTS[dependency_script_type],
        build_root=build_root,
        base_step=dependency_docker_image,
        additional_settings={
            "INPUT": "DEPENDENCY",
        }
    )

    final_step = build_step.ArtifactStep(
        script_path=_FINAL_STEP_SCRIPTS[script_type],
        build_root=build_root,
        base_step=base_step,
        dependency_steps=[dependency_step],
        additional_settings={
            "INPUT": "FINAL",
            "BASE_RESULT_FILE_PATH": str(base_step_result_file_path)
        }
    )

    final_step.run()

    if in_docker:
        # If base step run in docker we check its result file within the result image.
        result_file_content = subprocess.check_output([
            "docker",
            "run", "-i", "--rm",
            base_step.result_image_name,
            "cat",
            str(base_step_result_file_path)
        ]).decode()
    else:
        assert base_step_result_file_path.exists()
        result_file_content = base_step_result_file_path.read_text()

    assert result_file_content.strip() == f"BASE_{script_type}"

    # Check dependency step result
    dependency_step_result_file = dependency_step.output_directory / "result.txt"
    assert dependency_step_result_file.exists()
    assert dependency_step_result_file.read_text().strip() == f"DEPENDENCY_{dependency_script_type}"

    # Check final step's result file. It has to contain also text from the base step.
    final_step_result_file = final_step.output_directory / "result.txt"
    assert final_step_result_file.exists()
    assert final_step_result_file.read_text().strip() == textwrap.dedent(
        f"""
        BASE_{script_type}
        DEPENDENCY_{dependency_script_type}
        FINAL_{script_type}
        """
    ).strip()


def test_steps_id_consistency(tmp_path):

    def create_base_step(
            script_path=None,
            additional_settings=None
    ):

        script_path = script_path or _BUILD_STEPS_DIR / "base_step.sh"
        step = build_step.PrepareEnvironmentStep(
            script_path=script_path,
            build_root=tmp_path,
            base_step=None,
            additional_settings=additional_settings or {
                "NAME": "VALUE"
            }
        )

        return step

    base_step = create_base_step()
    base_step2 = create_base_step()

    assert base_step.id == base_step2.id

    changed_base = build_step.PrepareEnvironmentStep(
            script_path=_BUILD_STEPS_DIR / "base_step.sh",
            build_root=tmp_path,
            base_step=None,
            additional_settings={
                "NAME": "VALUE1",
            }
        )

    assert base_step.id != changed_base.id

    changed_base2 = build_step.PrepareEnvironmentStep(
            script_path=_BUILD_STEPS_DIR / "base_step.py",
            build_root=tmp_path,
            base_step=None,
            additional_settings={
                "NAME": "VALUE",
            }
        )

    assert base_step.id != changed_base2.id







@pytest.mark.parametrize(
    ["script_type", "docker_image"],
    [
        ("shell", None),
        ("python", None),
        ("shell", "debian:bullseye"),
        ("python", "python:3.8-bullseye")
    ],
)
def test_step_overall_info(
        script_type, docker_image: str
):
    """
    Verify correctness of the overall info of the step.
    If important to have correct overall_info method because unique id is built upon it.
    """

    script_path = _STEP_SCRIPTS[script_type]

    # Step that just generates an artifact which is used in further steps.
    dependency_step = CommonBuildStep(
        script_path=script_path,
        input_value="DEPENDENCY_STEP",
        base_step=_get_docker_image_spec_or_none(docker_image)
    )

    expected_dependency_step_info = {
        'name': 'initial_artifact_step',
        'used_files': [
            '.dockerignore',
            str(script_path.relative_to(constants.SOURCE_ROOT))
        ],
        'files_checksum': build_step.calculate_files_checksum(dependency_step.overall_info["used_files"]),
        'dependency_steps': [],
        'base_step': None,
        'additional_settings': {
            'INPUT': 'DEPENDENCY_STEP'
        }
    }

    # If step runs in docker, then the info object also has to contain an image information.
    if docker_image:
        expected_dependency_step_info['docker_image'] = {
            'architecture': 'x86_64',
            'name': docker_image
        }

    assert dependency_step.overall_info == expected_dependency_step_info

    base_step = CommonBuildStep(
        script_path=_STEP_SCRIPTS[script_type],
        input_value="BASE_STEP",
        base_step=_get_docker_image_spec_or_none(docker_image)
    )

    expected_base_step_info = {
        'name': 'initial_artifact_step',
        'used_files': [
            '.dockerignore',
            str(script_path.relative_to(constants.SOURCE_ROOT))
        ],
        'files_checksum': build_step.calculate_files_checksum(base_step.overall_info["used_files"]),
        'dependency_steps': [],
        'base_step': None,
        'additional_settings': {
            'INPUT': 'BASE_STEP'
        }
    }

    if docker_image:
        expected_base_step_info['docker_image'] = {
            'architecture': 'x86_64',
            'name': docker_image
        }

    assert base_step.overall_info == expected_base_step_info

    final_step = CommonBuildStep(
        script_path=script_path,
        input_value="TEST_STEP",
        base_step=base_step,
        dependency_steps=[dependency_step]
    )
    print(final_step.overall_info)

    expected_step_overall_info = {
        'name': 'initial_artifact_step',
        'used_files': [
            '.dockerignore',
            str(script_path.relative_to(constants.SOURCE_ROOT))
        ],
        'files_checksum': build_step.calculate_files_checksum(
            files=final_step.overall_info["used_files"]
        ),
        'dependency_steps': [
            dependency_step.overall_info
        ],
        'base_step': base_step.overall_info,
        'additional_settings': {
            'INPUT': 'TEST_STEP'
        }
    }

    # If step runs in docker image, then we also expect docker image info in the overall info.
    if docker_image:
        expected_step_overall_info['docker_image'] = {
            'architecture': 'x86_64',
            'name': docker_image
        }

    assert final_step.overall_info == expected_step_overall_info



@pytest.mark.parametrize(
    ["final_step_script_type", "final_step_docker_image"],
    [
        ("shell", None),
        ("python", None),
        ("shell", "debian:bullseye"),
        ("python", "python:3.8-bullseye")
    ],
)
@pytest.mark.parametrize(
    ["dependency_step_script_type", "dependency_step_docker_image"],
    [
        ("shell", None),
        ("python", None),
        ("shell", "debian:bullseye"),
        ("python", "python:3.8-bullseye")
    ],
)
def test_dependency_build_step(
    dependency_step_script_type,
    dependency_step_docker_image,
    final_step_script_type,
    final_step_docker_image


):
    dependency_step_script_path = _STEP_SCRIPTS[dependency_step_script_type]
    final_step_script_path = _STEP_SCRIPTS[final_step_script_type]

    dependency_step = CommonBuildStep(
        script_path=dependency_step_script_path,
        input_value="DEPENDENCY_STEP",
        base_step=_get_docker_image_spec_or_none(dependency_step_docker_image)
    )

    final_step = CommonBuildStep(
        script_path=final_step_script_path,
        input_value="FINAL_STEP",
        base_step=_get_docker_image_spec_or_none(final_step_docker_image),
        dependency_steps=[dependency_step]
    )

    final_step.run()

    dependency_step_result_file = dependency_step.output_directory / "result.txt"
    assert dependency_step_result_file.exists()
    assert dependency_step_result_file.read_text().strip() == f"DEPENDENCY_STEP_{dependency_step_script_type}"

    # Check an additional file in case if step1 is in docker.
    # There has to be a file with os-release content.
    dependency_step_docker_image_release_path = dependency_step.output_directory / "docker_image_release.txt"
    if dependency_step_docker_image:
        assert dependency_step_docker_image_release_path.exists()
        assert dependency_step_docker_image_release_path.read_text() == _DEBIAN_OS_RELEASE_CONTENT
    else:
        assert not dependency_step_docker_image_release_path.exists()

    final_step_result_file = final_step.output_directory / "result.txt"
    assert final_step_result_file.exists()
    assert final_step_result_file.read_text().strip() == textwrap.dedent(
        f"""
        DEPENDENCY_STEP_{dependency_step_script_type}
        FINAL_STEP_{final_step_script_type}
        """
    ).strip()

    # Check an additional file in case if step2 is in docker.
    step2_docker_release_info_file_path = final_step.output_directory / "docker_image_release.txt"
    if final_step_docker_image:
        assert step2_docker_release_info_file_path.exists()
        assert step2_docker_release_info_file_path.read_text() == _DEBIAN_OS_RELEASE_CONTENT
    else:
        assert not step2_docker_release_info_file_path.exists()

@pytest.mark.parametrize(
    ["base_step_script_type", "base_step_docker_image"],
    [
        ("shell", None),
        ("python", None),
        ("shell", "debian:bullseye"),
        ("python", "python:3.8-bullseye")
    ]
)
@pytest.mark.parametrize(
    ["final_step_script_type"],
    [
        ("shell",),
        ("python",)
    ]
)
def test_base_build_step(
    base_step_script_type,
    base_step_docker_image,
    final_step_script_type,
):
    """
    Verify the case where the final step is executed upon its base step.
    In other words, the final step has to be run in the environment that is created inside base step.
    """
    base_step_script_path = _BASE_STEP_SCRIPTS[base_step_script_type]
    final_step_script_path = _STEP_SCRIPTS[final_step_script_type]

    temp_dir = None

    if base_step_docker_image:
        result_file_path = "/tmp/result.txt"
    else:
        temp_dir = tempfile.TemporaryDirectory(prefix="scalyr_build_step_test")
        result_file_path = pl.Path(temp_dir.name, "result.txt")

    base_step = BaseBuildStep(
        input_value="BASE_STEP",
        result_file_path=result_file_path,
        script_path=base_step_script_path,
        base_step=_get_docker_image_spec_or_none(base_step_docker_image)
    )

    # final_step = CommonBuildStep(
    #     script_path=final_step_script_path,
    #     input_value="FINAL_STEP",
    #     base_step=base_step,
    #     dependency_steps=[base_step]
    # )


    base_step.run()



    return

    dependency_step_result_file = base_step.output_directory / "result.txt"
    assert dependency_step_result_file.exists()
    assert dependency_step_result_file.read_text().strip() == f"DEPENDENCY_STEP_{base_step_script_type}"

    # Check an additional file in case if step1 is in docker.
    # There has to be a file with os-release content.
    dependency_step_docker_image_release_path = base_step.output_directory / "docker_image_release.txt"
    if base_step_docker_image:
        assert dependency_step_docker_image_release_path.exists()
        assert dependency_step_docker_image_release_path.read_text() == _DEBIAN_OS_RELEASE_CONTENT
    else:
        assert not dependency_step_docker_image_release_path.exists()

    final_step_result_file = final_step.output_directory / "result.txt"
    assert final_step_result_file.exists()
    assert final_step_result_file.read_text().strip() == textwrap.dedent(
        f"""
        DEPENDENCY_STEP_{base_step_script_type}
        FINAL_STEP_{final_step_script_type}
        """
    ).strip()

    # Check an additional file in case if step2 is in docker.
    step2_docker_release_info_file_path = final_step.output_directory / "docker_image_release.txt"
    if final_step_docker_image:
        assert step2_docker_release_info_file_path.exists()
        assert step2_docker_release_info_file_path.read_text() == _DEBIAN_OS_RELEASE_CONTENT
    else:
        assert not step2_docker_release_info_file_path.exists()





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
@pytest.mark.parametrize(["in_ci_cd"], [[True]], indirect=True)
def test_example_deployment(example_deployment: deployments.Deployment, in_ci_cd: bool):
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
