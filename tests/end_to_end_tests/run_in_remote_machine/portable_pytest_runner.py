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
import subprocess
import sys

from agent_build_refactored.tools.constants import SOURCE_ROOT, Architecture, DockerPlatform
from agent_build_refactored.tools.runner import Runner, EnvironmentRunnerStep, DockerImageSpec, GitHubActionsSettings
from agent_build_refactored.managed_packages.managed_packages_builders import PREPARE_TOOLSET_STEPS

PORTABLE_RUNNER_NAME = "portable_runner"

PREPARE_TOOLSET_GLIBC_ARMV7 = EnvironmentRunnerStep(
    name="prepare_pytest_runner_builder_armhf",
    script_path="tests/end_to_end_tests/run_in_remote_machine/steps/prepare_pytest_runner_builder.sh",
    tracked_files_globs=[
        "agent_build/requirement-files/*.txt",
    ],
    base=DockerImageSpec(
        name="python:3.7",
        platform=DockerPlatform.ARMV7.value
    ),
    github_actions_settings=GitHubActionsSettings(
        cacheable=True
    )
)


class PortablePytestRunnerBuilder(Runner):
    """
    Builder class that builds pytest runner executable by using PyInstaller.
    """

    def build(self):

        self.run_required()

        if self.runs_in_docker:
            self.run_in_docker()
            return

        dist_path = self.output_path / "dist"
        subprocess.check_call(
            [
                "python3",
                "-m",
                "PyInstaller",
                "--onefile",
                "--distpath",
                str(dist_path),
                "--workpath",
                str(self.output_path / "build"),
                "--name",
                PORTABLE_RUNNER_NAME,
                "--add-data",
                f"tests/end_to_end_tests{os.pathsep}tests/end_to_end_tests",
                "--add-data",
                f"agent_build{os.pathsep}agent_build",
                "--add-data",
                f"agent_build_refactored{os.pathsep}agent_build_refactored",
                "--add-data",
                f"VERSION{os.pathsep}.",
                "--add-data",
                f"dev-requirements-new.txt{os.pathsep}.",
                # As an entry point we use this file itself because it also acts like a script which invokes pytest.
                __file__,
            ],
            cwd=SOURCE_ROOT,
        )

    @property
    def result_runner_path(self):
        return self.output_path / "dist" / PORTABLE_RUNNER_NAME

    @classmethod
    def handle_command_line_arguments(
        cls,
        args,
    ):
        super(PortablePytestRunnerBuilder, cls).handle_command_line_arguments(args)
        builder = cls(work_dir=args.work_dir)
        builder.build()


class PortablePytestRunnerBuilderX86_64(PortablePytestRunnerBuilder):
    BASE_ENVIRONMENT = PREPARE_TOOLSET_STEPS[Architecture.X86_64]


class PortablePytestRunnerBuilderARM64(PortablePytestRunnerBuilder):
    BASE_ENVIRONMENT = PREPARE_TOOLSET_STEPS[Architecture.ARM64]


class PortablePytestRunnerBuilderARMV7(PortablePytestRunnerBuilder):
    BASE_ENVIRONMENT = PREPARE_TOOLSET_GLIBC_ARMV7


PORTABLE_PYTEST_RUNNER_BUILDERS = {
    Architecture.X86_64: PortablePytestRunnerBuilderX86_64,
    Architecture.ARM64: PortablePytestRunnerBuilderARM64,
    Architecture.ARMV7: PortablePytestRunnerBuilderARMV7
}


if __name__ == "__main__":
    # We use this file as an entry point for the pytest runner.
    import pytest
    sys.path.append(str(SOURCE_ROOT))

    os.chdir(SOURCE_ROOT)
    sys.exit(pytest.main())
