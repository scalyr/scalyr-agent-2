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

"""
This module defines logic that allows to build single-file, standalone executable binary with pytest runner.
This executable is used in ec2 and docker end-to-end tests to run those tests in completely clean environment
without Python and other dependencies.
"""

import os
import shutil
import pathlib as pl
import sys
from typing import Dict, List

from agent_build_refactored.tools.constants import SOURCE_ROOT, Architecture
from agent_build_refactored.tools.runner import (
    Runner,
    ArtifactRunnerStep,
    RunnerStep,
    GitHubActionsSettings,
)
from agent_build_refactored.managed_packages.managed_packages_builders import (
    PREPARE_PYTHON_ENVIRONMENT_STEPS,
    SUPPORTED_ARCHITECTURES,
)

PORTABLE_RUNNER_NAME = "portable_runner"


def create_build_portable_pytest_runner_step() -> Dict[
    Architecture, ArtifactRunnerStep
]:

    steps = {}
    for architecture in SUPPORTED_ARCHITECTURES:
        run_in_remote_docker = architecture != Architecture.X86_64

        step = ArtifactRunnerStep(
            name=f"build_portable_pytest_runner_{architecture.value}",
            script_path="tests/end_to_end_tests/run_in_remote_machine/steps/build_pytest_runner.py",
            tracked_files_globs=[
                pl.Path(__file__).relative_to(SOURCE_ROOT),
                "tests/end_to_end_tests/**/*",
                "agent_build/**/*",
                "agent_build_refactored/**/*",
                "VERSION",
                "dev-requirements-new.txt",
            ],
            base=PREPARE_PYTHON_ENVIRONMENT_STEPS[architecture],
            environment_variables={
                "PORTABLE_RUNNER_NAME": PORTABLE_RUNNER_NAME,
            },
            github_actions_settings=GitHubActionsSettings(
                cacheable=True, run_in_remote_docker=run_in_remote_docker
            ),
        )

        steps[architecture] = step

    return steps


BUILD_PORTABLE_PYTEST_RUNNER_STEPS = create_build_portable_pytest_runner_step()


class PortablePytestRunnerBuilder(Runner):
    ARCHITECTURE: Architecture
    """
    Builder class that builds pytest runner executable by using PyInstaller.
    """

    @classmethod
    def get_all_required_steps(cls) -> List[RunnerStep]:
        return [BUILD_PORTABLE_PYTEST_RUNNER_STEPS[cls.ARCHITECTURE]]

    def build(self):

        self.run_required()

        build_step = BUILD_PORTABLE_PYTEST_RUNNER_STEPS[self.ARCHITECTURE]
        build_step_output = build_step.get_output_directory(work_dir=self.work_dir)

        shutil.copy(build_step_output / "dist" / PORTABLE_RUNNER_NAME, self.output_path)

    @property
    def result_runner_path(self):
        return self.output_path / PORTABLE_RUNNER_NAME

    @classmethod
    def handle_command_line_arguments(
        cls,
        args,
    ):
        super(PortablePytestRunnerBuilder, cls).handle_command_line_arguments(args)
        builder = cls(work_dir=args.work_dir)
        builder.build()


PORTABLE_PYTEST_RUNNER_BUILDERS = {}
# Iterate through all supported architectures and create package builders classes for each.
for arch in SUPPORTED_ARCHITECTURES:

    class BuilderCls(PortablePytestRunnerBuilder):
        ARCHITECTURE = arch
        CLASS_NAME_ALIAS = f"PortablePytestRunnerBuilder{arch.value}"
        ADD_TO_GLOBAL_RUNNER_COLLECTION = True

    PORTABLE_PYTEST_RUNNER_BUILDERS[arch] = BuilderCls


if __name__ == "__main__":
    # We use this file as an entry point for the pytest runner.
    import pytest

    sys.path.append(str(SOURCE_ROOT))

    os.chdir(SOURCE_ROOT)
    sys.exit(pytest.main())
