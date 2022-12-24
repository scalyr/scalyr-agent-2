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


def calculate_file_checksum(
        file_path: pl.Path,
        relative_to: pl.Path = None,
        sha256=None
):
    """Calculate checksum of a file."""
    if sha256 is None:
        sha256 = hashlib.sha256()
    # Include file's path...
    if relative_to:
        path = file_path.relative_to(relative_to)
    else:
        path = file_path

    sha256.update(str(path).encode())
    # ... content ...
    sha256.update(file_path.read_bytes())
    # ... and permissions.
    sha256.update(str(file_path.stat().st_mode).encode())

    return sha256
