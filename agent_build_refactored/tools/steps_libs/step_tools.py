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

#
# This module provides some helper functions that can be used inside RunnerStep scripts.
#
import os
import pathlib as pl


def skip_caching_and_exit():
    """
    This function immediately finishes RunnerStep's script and also writes special 'skip_caching' file,
    which signals that step result must not be cached.
    """
    skip_caching_file_path = pl.Path(os.environ["STEP_OUTPUT_PATH"]) / "skip_caching"
    skip_caching_file_path.touch()
    exit(0)