#!/usr/bin/python3
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

import os
import subprocess
import pathlib as pl

SOURCE_ROOT = pl.Path(os.environ["SOURCE_ROOT"])
STEP_OUTPUT_PATH = pl.Path(os.environ["STEP_OUTPUT_PATH"])
PORTABLE_RUNNER_NAME = os.environ["PORTABLE_RUNNER_NAME"]

dist_path = STEP_OUTPUT_PATH / "dist"
subprocess.check_call(
    [
        "python3",
        "-m",
        "PyInstaller",
        "--onefile",
        "--distpath",
        str(dist_path),
        "--workpath",
        str(STEP_OUTPUT_PATH / "build"),
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
        str(
            SOURCE_ROOT
            / "tests/end_to_end_tests/run_in_remote_machine/portable_pytest_runner.py"
        ),
    ],
    cwd=SOURCE_ROOT,
)
