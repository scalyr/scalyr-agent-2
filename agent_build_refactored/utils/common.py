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

import logging
import pathlib as pl
import subprocess


def init_logging():
    logging.basicConfig(
        level=logging.INFO,
        format=f"[%(levelname)s][%(module)s:%(lineno)s] %(message)s",
    )

def latest_commit(source_root: pl.Path) -> str:
    # 'git rev-parse --short HEAD' is the standard command for this
    short_hash = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(source_root),
        stderr=subprocess.STDOUT,
        unicode=True
    ).strip()
    return str(short_hash)