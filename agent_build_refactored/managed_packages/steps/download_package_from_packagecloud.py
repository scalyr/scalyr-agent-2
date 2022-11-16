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

# This script is meant to be executed by the instance of the 'agent_build_refactored.tools.runner.RunnerStep' class.
# Every RunnerStep provides common environment variables to its script:
#   SOURCE_ROOT: Path to the projects root.
#   STEP_OUTPUT_PATH: Path to the step's output directory.
#
# This script downloads package from the Packagecloud.
#
# It expects next environment variables:
#   PACKAGE_FILENAME: File name of the package.

import os

from agent_build_refactored.tools.steps_libs.step_tools import skip_caching_and_exit


def main():
    package_file_name = os.environ["PACKAGE_FILENAME"]

    skip_caching_and_exit()


if __name__ == '__main__':
    main()