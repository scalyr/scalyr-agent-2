#!/usr/bin/env python
#
# Copyright 2019 Scalyr Inc.
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
# ------------------------------------------------------------------------
#
# Script used to check the code for python 2/3 compatibility using "python-modernize" tool
# usage python modernize.py

from __future__ import print_function
from __future__ import absolute_import

import re
import os
import glob2
import subprocess
from collections import defaultdict

from scalyr_agent.__scalyr__ import get_package_root


def modernize(files, params_str=""):
    """
    :param files: list of files paths.
    :param params_str:  additional parameters to python-modernize
    :return:
    """
    process = subprocess.Popen(
        "python-modernize {} -w -n {}".format(params_str, " ".join(list(files))),
        shell=True,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE
    )

    stdout = process.stdout

    diffs = defaultdict(list)

    while True:
        line = stdout.readline()
        if not line:
            break
        m = re.match(r"--- (.+)\s+\(original\)\n", line)
        if m:
            filename = m.group(1)
            diffs[filename].append(line)
            current_file = list()
            current_filename = filename
        else:
            diffs[current_filename].append(line)

    return diffs


source_root = get_package_root()
root = os.path.dirname(source_root)


# do not modernize third_party libraries.
third_party_files = set(glob2.glob("{0}/third_party*/**/*.py".format(source_root)))

# files to modernize later, without using six.
files_without_six = (
    # __scalyr__.py can not have "six" as dependency, because third_party libraries are not imported yet.
    os.path.join(root, os.path.join("scalyr_agent", "__scalyr__.py")),
)

regular_files = set(glob2.glob("{}/**/*.py".format(root), recursive=True)) - third_party_files - set(files_without_six)

# modernize the main codebase.
regular_files_diffs = modernize(regular_files)

# modernize files(first of all __scalyr__.py) without "six" library.
files_without_six_diffs = modernize(files_without_six, params_str="--no-six")


# combine all results in one.
all_diffs = dict()
all_diffs.update(regular_files_diffs)
all_diffs.update(files_without_six_diffs)

if not all_diffs:
    print("All files are up to date.")
    # Nothing to update. Exit without error.
    exit(0)

for filename, lines in list(all_diffs.items()):
    all_diffs[filename] = "".join(lines)


print("Python-modernize found code to update in files:")


for filename, diff in list(all_diffs.items()):
    print(filename)
    print(diff)

exit(1)
