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
# Script used to generate python coverage html report.
#
# To execute this script, you must have installed "coverage" package.(pip install coverage).
# Before execution put files '.coverage' and '.coveragerc' in the root directory of the project.
# Current working directory must be in the root directory too.
# After execution paths from coverage file will be changed to local paths.
#
# Usage: python coverage_report.py


from __future__ import absolute_import
import os
import shutil
import six.moves.configparser
import argparse
from io import open


parser = argparse.ArgumentParser()
parser.add_argument(
    "--show",
    action="store_true",
    default=False,
    help="Open index page of html coverage report.",
)

args = parser.parse_args()


# "rename .coverage file for  "combine" command"
if os.path.exists("coverage.txt"):
    # can be useful after downloading from circleci.
    os.rename("coverage.txt", ".coverage.1")
elif os.path.exists(".coverage"):
    os.rename(".coverage", ".coverage.1")
elif os.path.exists(".coverage.1"):
    pass
else:
    raise OSError("Coverage file not found.")

# Add current local project path in .coveragrc config file.
# This is important because html report needs source code to generate results
# Paths in .coverage and in local project can be different,
# so we need to specify local project path, so coverage tool can access to source code to generate html.
parser = six.moves.configparser.ConfigParser()  # type: ignore
with open(".coveragerc", "r") as f:
    parser.readfp(f)  # type: ignore

# add current path to 'paths' section.
paths = parser.get("paths", "source").split("\n")  # type: ignore
cwd = os.getcwd()
if cwd not in paths:
    paths = ["\n%s" % os.getcwd()] + paths
parser.set("paths", "source", "\n".join(paths))  # type: ignore

with open(".coveragerc", "w") as f:
    parser.write(f)  # type: ignore

os.system("coverage combine")

shutil.rmtree("htmlcov", ignore_errors=True)

os.system("coverage html")

if args.show:
    import webbrowser

    webbrowser.open("htmlcov/index.html")
