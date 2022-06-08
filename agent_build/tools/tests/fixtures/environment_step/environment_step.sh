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

# This is a template of the script that can be used in a BuildStep (see agent_build/tools/builder.py).
# PLEASE NOTE. To achieve valid caching of the build step, keep that script as standalone as possible.
#   If there are any dependencies, imports or files which are used by this script, then also add them
#   to the `TRACKED_FILE_GLOBS` attribute of the step class.

# Here are some environment variables, which are pre-defined for all steps:
#   SOURCE_ROOT - path to the source root of the project.
#   STEP_OUTPUT_PATH - path where the step has to save its results.

cached_result_output_path="$STEP_OUTPUT_PATH/result.txt"

if [ ! -d "$cached_result_output_path" ]; then
  echo "${INPUT}" > "$cached_result_output_path"
  echo "shell" >> "$cached_result_output_path"
  if [ -n "$AGENT_BUILD_IN_DOCKER" ]; then
    echo "docker" >> "$cached_result_output_path"
  fi
fi

cp "$cached_result_output_path" "$RESULT_FILE_PATH"
