# Copyright 2014-2022 Scalyr Inc.
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

import pathlib as pl

import pytest
import mock

from agent_build.tools.runner import (
    ArtifactRunnerStep,
    DockerImageSpec,
)
from agent_build.tools.constants import DockerPlatform


@pytest.fixture
def sample_artifact_step_script():
    return pl.Path(__file__).parent / "fixtures/sample_artifact_step.sh"


_FIXTURES_PATH = pl.Path(__file__).parent / "fixtures"
_SAMPLE_ARTIFACT_STEP_SCRIPT_PATH = _FIXTURES_PATH / "sample_artifact_step.sh"


def _create_artifact_step(
    name="artifact_test_step",
    script_path: pl.Path = None,
    tracked_files_globs=None,
    environment_variables=None,
    base=None,
):
    if not script_path:
        script_path = _SAMPLE_ARTIFACT_STEP_SCRIPT_PATH

    if not tracked_files_globs:
        tracked_files_globs = [_FIXTURES_PATH / "sample_tracked_*.txt"]

    if not environment_variables:
        environment_variables = {"INPUT": "Hello"}

    return ArtifactRunnerStep(
        name=name,
        script_path=script_path,
        tracked_files_globs=tracked_files_globs,
        base=base,
        environment_variables=environment_variables,
    )


_BASE_DOCKER_IMAGES = {
    "ubuntu_20_04": DockerImageSpec(
        name="ubuntu:20.04", platform=DockerPlatform.AMD64.value
    )
}


@pytest.fixture
def step_base_image(request):
    param = getattr(request, "param", None)
    return _BASE_DOCKER_IMAGES.get(param)


@pytest.fixture
def sample_artifact_step(step_base_image):
    return _create_artifact_step(base=step_base_image)


class TestStepId:
    def test_same_id(self, sample_artifact_step):
        step = _create_artifact_step()
        assert step == sample_artifact_step

    def test_different_name(self, sample_artifact_step):
        step = _create_artifact_step(
            name="different_name",
        )
        assert step != sample_artifact_step

    def test_different_env_var_name(self, sample_artifact_step):
        step = _create_artifact_step(environment_variables={"INPUT2": "Hello"})
        assert step != sample_artifact_step

    def test_different_env_var_value(self, sample_artifact_step):
        step = _create_artifact_step(environment_variables={"INPUT": "Bye"})
        assert step != sample_artifact_step

    def test_different_step_script(self, sample_artifact_step, tmp_path):
        # Modify step's script, that also has to lead to the changing of the id

        # Create mock file with slightly changes content
        mock_script_path = tmp_path / _SAMPLE_ARTIFACT_STEP_SCRIPT_PATH.name
        sample_step_script_content = _SAMPLE_ARTIFACT_STEP_SCRIPT_PATH.read_text()

        sample_step_script_modified_content = f"{sample_step_script_content}\n#modified"
        mock_script_path.write_text(sample_step_script_modified_content)

        original_read_bytes = pl.Path.read_bytes

        def mock_read_bytes(self):
            if self == pl.Path(_SAMPLE_ARTIFACT_STEP_SCRIPT_PATH):
                return original_read_bytes(mock_script_path)
            else:
                return original_read_bytes(self)

        with mock.patch("pathlib.Path.read_bytes", mock_read_bytes):
            step = _create_artifact_step()

        assert step != sample_artifact_step

    def test_different_tracked_file(self, sample_artifact_step, tmp_path):
        tacked_file_path = _FIXTURES_PATH / "sample_tracked_file.txt"
        mock_file_path = tmp_path / tacked_file_path.name
        tracked_file_content = tacked_file_path.read_text()

        tracked_file_modified_content = f"beautiful {tracked_file_content}"
        mock_file_path.write_text(tracked_file_modified_content)

        original_read_bytes = pl.Path.read_bytes

        def mock_read_bytes(self):
            if self == pl.Path(tacked_file_path):
                return original_read_bytes(mock_file_path)
            else:
                return original_read_bytes(self)

        with mock.patch("pathlib.Path.read_bytes", mock_read_bytes):
            step = _create_artifact_step()

        assert step != sample_artifact_step


@pytest.mark.parametrize(["step_base_image"], [[None], ["ubuntu_20_04"]], indirect=True)
def test_id_cache_invalidation(sample_artifact_step, tmp_path, step_base_image):
    # test that changing of the step id leads to another cache key.
    sample_artifact_step.run(work_dir=tmp_path)

    caches_dir = tmp_path / "step_cache"
    found = list(caches_dir.iterdir())
    assert len(found) == 1
    assert found[0] == sample_artifact_step.get_cache_directory(work_dir=tmp_path)

    # Create identical step to verify that the cache is reused.
    step1 = _create_artifact_step(base=step_base_image)
    assert step1 == sample_artifact_step
    step1.run(work_dir=tmp_path)
    found = list(caches_dir.iterdir())
    assert len(found) == 1
    assert found[0] == step1.get_cache_directory(work_dir=tmp_path)
    assert step1.get_cache_directory(
        work_dir=tmp_path
    ) == sample_artifact_step.get_cache_directory(work_dir=tmp_path)

    # Create another step with different id, that has to lead to a new cache entry.
    step2 = _create_artifact_step(name="another_name")
    assert step2 != sample_artifact_step

    step2.run(work_dir=tmp_path)
    # Run of this step has to create new directory. in caches folder.
    found = list(caches_dir.iterdir())
    assert len(found) == 2
    assert sample_artifact_step.get_cache_directory(work_dir=tmp_path) in found
    assert step2.get_cache_directory(work_dir=tmp_path) in found


@pytest.mark.parametrize(["step_base_image"], [[None], ["ubuntu_20_04"]], indirect=True)
def test_artifact_step_output(sample_artifact_step, tmp_path):
    sample_artifact_step.run(work_dir=tmp_path)

    step_output = sample_artifact_step.get_output_directory(work_dir=tmp_path)
    result_file_path = step_output / "result.txt"
    assert result_file_path.exists()

    # The result file  has to contain the 'Hello world'.
    assert result_file_path.read_text() == "Hello world.\n"
