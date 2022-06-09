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

import os
import subprocess
import pathlib as pl

import mock
import pytest

import agent_build.tools.common
from agent_build.tools import common
from agent_build.tools.builder import EnvironmentBuilderStep, ArtifactBuilderStep
from agent_build.tools.builder import DockerImageSpec

common.init_logging()

_PARENT_DIR = pl.Path(__file__).parent
_FIXTURES_PATH = _PARENT_DIR / "fixtures"
_BUILD_STEPS_DIR = _PARENT_DIR / "fixtures/build_step_scripts"


def _get_docker_image_spec_or_none(
        docker_image: str = None
):
    if not docker_image:
        return None

    return DockerImageSpec(
        name=docker_image,
        architecture=agent_build.tools.common.Architecture.X86_64
    )


_DOCKER_IMAGES_TO_SCRIPT_TYPES = {
    "shell": "debian:bullseye",
    "python": "python:3.8-bullseye"
}


@pytest.fixture(scope="session")
def test_docker_images():

    result = {}
    for script_type, image_name in _DOCKER_IMAGES_TO_SCRIPT_TYPES.items():

        dockerfile_path = _FIXTURES_PATH / "Dockerfile"

        test_image_name = f"{image_name}_test"
        subprocess.check_output([
            "docker",
            "build",
            "-f",
            str(dockerfile_path),
            "--build-arg",
            f"BASE_IMAGE_NAME={image_name}",
            "-t",
            test_image_name,
            str(_FIXTURES_PATH)
        ])

        result[script_type] = test_image_name

    return result

@pytest.fixture
def create_artifact_step(
        test_docker_images
):
    def create(
        script_type: str,
        in_docker: bool
    ):
        # Set path to a file that has to be created during the run of the base step.
        if in_docker:
            docker_image = _get_docker_image_spec_or_none(
                test_docker_images[script_type]
            )
        else:
            docker_image = None

        scripts_path = _FIXTURES_PATH / "artifact_step"
        if script_type == "shell":
            script_path =  scripts_path / "artifact_step.sh"
        else:
            script_path = scripts_path / "artifact_step.py"

        step = ArtifactBuilderStep(
            name="artifact_build_step",
            script_path=script_path,
            base_step=docker_image,
            additional_settings={
                "INPUT": "TEST_ARTIFACT_STEP",
            },
        )

        return step

    return create

@pytest.mark.parametrize(
    ["script_type", "in_docker"],
    [
        ("shell", True),
        ("shell", False),
        ("python", True),
        ("python", False)
    ]
)
def test_artifact_step(
    script_type,
    in_docker,
    tmp_path,
    create_artifact_step

):

    step = create_artifact_step(
        script_type=script_type,
        in_docker=in_docker
    )

    build_root_path = tmp_path / "build_root"

    with mock.patch.object(step, "_run", wraps=step._run) as _run_mock:
        # build_root_path = pl.Path("/Users/arthur/work/agents/scalyr-agent-2/build_test")
        step.run(build_root=build_root_path)

        # Full run has to be done on the first time
        assert _run_mock.call_count == 1

    cached_result_file_path = step.output_directory / "result.txt"

    assert cached_result_file_path.is_file()

    expected_result_content = f"TEST_ARTIFACT_STEP\n{script_type}"

    if in_docker:
        expected_result_content = f"{expected_result_content}\ndocker"

    assert cached_result_file_path.read_text().strip() == expected_result_content

    # Create identical step and run it for the second time to check if it reuses existing results instead of full run.
    step2 = create_artifact_step(
        script_type=script_type,
        in_docker=in_docker
    )

    step2.run(build_root=build_root_path)
    # with mock.patch.object(step2, "_run", wraps=step2._run) as _run_mock:
    #     step2.run(build_root=build_root_path)
    #     # The internal "_run" method has to be skipped, since we reused existing results.
    #     assert _run_mock.call_count == 0


@pytest.fixture
def create_environment_step(test_docker_images):
    def create(
        script_type,
        in_docker,
        result_file_path,
    ):
        # Set path to a file that has to be created during the run of the base step.
        if in_docker:
            docker_image = _get_docker_image_spec_or_none(
                test_docker_images[script_type]
            )
        else:
            docker_image = None

        scripts_path = _FIXTURES_PATH / "environment_step"
        if script_type == "shell":
            script_path = scripts_path / "environment_step.sh"
        else:
            script_path = scripts_path / "environment_step.py"

        step = EnvironmentBuilderStep(
            name="environment_build_step",
            script_path=script_path,
            base_step=docker_image,
            additional_settings={
                "INPUT": "TEST_ENVIRONMENT_STEP",
                "RESULT_FILE_PATH": str(result_file_path),
            },
        )
        return step

    return create


@pytest.mark.parametrize(
    ["script_type", "in_docker"],
    [
        ("shell", True),
        ("shell", False),
        ("python", True),
        ("python", False)
    ]
)
def test_environment_step(
        script_type,
        in_docker,
        tmp_path,
        create_environment_step
):
    # Set path to a file that has to be created during the run of the base step.
    if in_docker:
        result_file_path = pl.Path("/tmp/base.txt")
    else:
        result_file_path = tmp_path / "base.txt"

    step = create_environment_step(
        script_type=script_type,
        in_docker=in_docker,
        result_file_path=result_file_path
    )

    build_root_path = tmp_path / "build_root"
    # build_root_path = pl.Path("/Users/arthur/work/agents/scalyr-agent-2/build_test")

    with mock.patch.object(step, "_run", wraps=step._run) as _run_mock:
        step.run(build_root=build_root_path)
        # Full run has to be done on the first time
        assert _run_mock.call_count == 1

    if in_docker:
        result_file_content = subprocess.check_output([
            "docker",
            "run", "-i", "--rm",
            step.result_image.name,
            "cat",
            str(result_file_path)
        ]).decode().strip()

        image_file_path = step.output_directory / f"{step.result_image.name}.tar"
        assert image_file_path.is_file()
    else:
        assert result_file_path.is_file()
        result_file_content = result_file_path.read_text().strip()

    expected_result_content = f"TEST_ENVIRONMENT_STEP\n{script_type}"

    if in_docker:
        expected_result_content = f"{expected_result_content}\ndocker"

    assert result_file_content == expected_result_content

    # Create identical step and run it for the second time to check if it reuses existing results instead of full run.
    step2 = create_environment_step(
        script_type=script_type,
        in_docker=in_docker,
        result_file_path=result_file_path
    )
    with mock.patch.object(step2, "_run", wraps=step2._run) as _run_mock:
        step2.run(build_root=build_root_path)

        if in_docker:
            # If environment step runs in docker and results are reused, then the internal "_run" method is skipped
            # because result is saved as entire image.
            assert _run_mock.call_count == 0
        else:
            # If environment step does not run in docker, it still has to perform internal "_run" method even if cached
            # results are presented.
            assert _run_mock.call_count == 1


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
def test_complex_step(
        script_type,
        in_docker,
        dependency_script_type,
        dependency_in_docker,
        tmp_path,
        create_environment_step,
        create_artifact_step
):
    """
    Test a step that also has one artifact step as a dependency and another step as a base.
    """
    # Set path to a file that has to be created during the run of the base step.
    if in_docker:
        base_step_result_file_path = pl.Path("/tmp/base.txt")
    else:
        base_step_result_file_path = tmp_path / "base.txt"

    base_step = create_environment_step(
        script_type=script_type,
        in_docker=in_docker,
        result_file_path=base_step_result_file_path
    )

    dependency_step = create_artifact_step(
        script_type=dependency_script_type,
        in_docker=dependency_in_docker
    )

    scripts_path = _FIXTURES_PATH / "complex_step"
    if script_type == "shell":
        script_path = scripts_path / "complex_step.sh"
    else:
        script_path = scripts_path / "complex_step.py"

    final_step = ArtifactBuilderStep(
        name="FinalStep",
        script_path=script_path,
        base_step=base_step,
        dependency_steps=[dependency_step],
        additional_settings={
            "INPUT": "FINAL_ARTIFACT_STEP",
            "BASE_RESULT_FILE_PATH": str(base_step_result_file_path)
        },
    )

    build_root = tmp_path / "build_root"

    final_step.run(
        build_root=build_root
    )

    final_step_result_file = final_step.output_directory / "result.txt"
    assert final_step_result_file.exists()

    expected_result_content = f"TEST_ENVIRONMENT_STEP\n{script_type}"
    if in_docker:
        expected_result_content += "\ndocker"

    expected_result_content += f"\nTEST_ARTIFACT_STEP\n{dependency_script_type}"
    if dependency_in_docker:
        expected_result_content += "\ndocker"

    expected_result_content += f"\nFINAL_ARTIFACT_STEP\n{script_type}"
    if in_docker:
        expected_result_content += "\ndocker"

    result_file_content = final_step_result_file.read_text().strip()

    assert result_file_content == expected_result_content


def test_steps_id_consistency(tmp_path):
    """
    Test that essential input step information such as additional_settings,
    docker_image and used_files will be reflected in an id of a step,
    and the same step with the same inputs always produces the same id.
    """

    script_path = _FIXTURES_PATH / "id_consistency" / "sample_script.sh"

    step = ArtifactBuilderStep(
        name="step",
        script_path=script_path,
        base_step=None,
        additional_settings={
            "NAME": "VALUE"
        },
    )

    same_step = ArtifactBuilderStep(
        name="step",
        script_path=script_path,
        base_step=None,
        additional_settings={
            "NAME": "VALUE"
        },
    )

    assert step.id == same_step.id

    # Change additional settings
    changed_base = ArtifactBuilderStep(
        name="step",
        script_path=script_path,
        base_step=None,
        additional_settings={
            "NAME": "ANOTHER_VALUE",
        },
    )

    assert step.id != changed_base.id

    # Simulate the case where the script file is changed.
    # Mock pathlib.Path's read_bytes method to return content of another file if it's a script file of the current step.
    original_path_read_bytes = pl.Path.read_bytes

    def path_read_bytes_mock(path):
        if path == script_path:
            mocked_path = _FIXTURES_PATH / "id_consistency" / "changed_sample_script.sh"
            return original_path_read_bytes(mocked_path)

        return original_path_read_bytes(path)

    with mock.patch("pathlib.Path.read_bytes", path_read_bytes_mock):
        changed_script_step = ArtifactBuilderStep(
            name="step",
            script_path=script_path,
            base_step=None,
            additional_settings={
                "NAME": "VALUE",
            },
        )
        changed_id = changed_script_step.id

    assert step.id != changed_id

    # Add docker image, also expect the change of the id.
    step_with_docker_image = ArtifactBuilderStep(
        name="step",
        script_path=script_path,
        base_step=_get_docker_image_spec_or_none("ubuntu"),
        additional_settings={
            "NAME": "VALUE",
        },
    )

    assert step.id != step_with_docker_image.id


def test__id_consistency_with_dependency_step():
    """
    Verify that changing in the dependency step also affects id of the parent step.
    """
    script_path = _FIXTURES_PATH / "id_consistency" / "sample_script.sh"

    dependency_step = ArtifactBuilderStep(
        name="dependency_step",
        script_path=script_path,
        base_step=None,
        additional_settings={
            "NAME": "VALUE"
        },
    )

    final_step = ArtifactBuilderStep(
        name="final_step",
        script_path=script_path,
        base_step=None,
        dependency_steps=[dependency_step],
    )

    same_final_step = ArtifactBuilderStep(
        name="final_step",
        script_path=script_path,
        base_step=None,
        dependency_steps=[dependency_step],
    )

    assert final_step.id == same_final_step.id

    # Mocking the id of the dependency step to return different value.
    # The final step's id also has to be changed.
    mocked_dependency_step_id = dependency_step.id + "1"
    with mock.patch.object(ArtifactBuilderStep, "id", new_callable=mock.PropertyMock) as id_mock:
        id_mock.return_value = mocked_dependency_step_id
        changed_final_step = ArtifactBuilderStep(
            name="final_step",
            script_path=script_path,
            base_step=None,
            dependency_steps=[dependency_step],
        )
        changed_final_step_id = changed_final_step.id

    assert final_step.id != changed_final_step_id


