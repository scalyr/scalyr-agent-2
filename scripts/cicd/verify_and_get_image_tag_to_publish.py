#!/usr/bin/env python
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

"""
This script is used by the CI/CD to publish agent docker images to appropriate tags.
It takes an repository tag as an input and prints result tag option to the stdout.
The result options can be inserted directly into the image build command.
"""

import argparse
import pathlib as pl
import re
import sys

_SOURCE_PATH = pl.Path(__file__).parent.parent.parent.absolute()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("tag")
    args = parser.parse_args()

    production_tag_pattern = r"^v(\d+\.\d+\.\d+)$"

    m = re.match(
        production_tag_pattern,
        args.tag
    )

    # if given tag does not match production tag (e.g. v2.1.25), then just push
    # the image by the same, unchanged tag.
    if not m:
        print(f"--tag {args.tag}")
        exit(0)

    # The production tag is given, verify it the given version matches the version in the file.
    tag_version = m.group(1)

    version_file_path = _SOURCE_PATH / "VERSION"

    current_version = version_file_path.read_text().strip()

    if tag_version != current_version:
        print(
            f"Error. New version tag {args.tag} does not match "
            f"current version {current_version}.",
            file=sys.stderr
        )
        exit(1)

    # Version is valid print version as a tag and  also add the 'latest' tag.
    print(f"--tag {tag_version} --tag latest")
    exit(0)


