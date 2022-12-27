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
import hashlib
from typing import List

from agent_build_refactored.tools.steps_libs.constants import SOURCE_ROOT


def calculate_files_checksum(
        files_paths: List[pl.Path],
        sha256=None
):
    """Calculate checksum of a file."""
    if sha256 is None:
        sha256 = hashlib.sha256()

    for file_path in files_paths:
        if not str(file_path).startswith(str(SOURCE_ROOT)):
            raise Exception(f"Path {file_path}has to be relative to project root: {SOURCE_ROOT}")
        # Include file's path...
        rel_path = file_path.relative_to(SOURCE_ROOT)
        sha256.update(str(rel_path).encode())
        # ... content ...
        sha256.update(file_path.read_bytes())
        # ... and permissions.
        sha256.update(str(file_path.stat().st_mode).encode())

    return sha256
