# Copyright 2014-2023 Scalyr Inc.
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
This module defines all name of docker images that are used by this project.
Image names are parsed from the "dummy" Dockerfiles in the same directory. It is important to
have those dockerfiles because dependabot can detect and update their versions.
"""

import re
import pathlib as pl

PARENT_DIR = pl.Path(__file__).parent.absolute()


def parse_dockerfile(path: pl.Path):
    content = path.read_text()

    for line in content.splitlines():
        trimmed_line = line.strip()
        if not trimmed_line.startswith("FROM"):
            continue

        m = re.search(r"^FROM\s+(\S+)$", trimmed_line)

        image_name = m.group(1)
        return image_name

    raise Exception(f"Can't find image name in the dockerfile {path}")



UBUNTU_22_04 = parse_dockerfile(path=PARENT_DIR / "ubuntu-22.04.Dockerfile")

a=10
