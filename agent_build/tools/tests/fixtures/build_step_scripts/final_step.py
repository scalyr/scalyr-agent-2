#!/bin/sh
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
import pathlib as pl
import sys

output_dir = pl.Path(os.environ["STEP_OUTPUT_PATH"])
result_file_path = output_dir / "result.txt"

base_step_file = pl.Path(os.environ["BASE_RESULT_FILE_PATH"])
base_step_result = base_step_file.read_text()

dependency_step_output = pl.Path(sys.argv[1])
dependency_result_file = dependency_step_output / "result.txt"
dependency_result = dependency_result_file.read_text()

step_input = os.environ["INPUT"]
result_file_path.write_text(
    f"{base_step_result}\n{dependency_result}\n{step_input}_python"
)