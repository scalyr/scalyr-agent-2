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
import tempfile
import subprocess
import glob

parser = argparse.ArgumentParser()
parser.add_argument(
    "--show",
    action="store_true",
    default=False,
    help="Open index page of html coverage report.",
)

args = parser.parse_args()

# create temporary directory

for path in glob.glob(os.path.join(tempfile.gettempdir(), "scalyr_agent_coverage*")):
    shutil.rmtree(path)

tmp_path = tempfile.mkdtemp(prefix="scalyr_agent_coverage_")


copied_coverage_file_path = os.path.join(tmp_path, ".coverage.1")

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
coverage_file_path = os.path.join(root, ".coverage")
coverage_txt_path = os.path.join(root, "coverage.txt")
renamed_coverage_file = os.path.join(root, "coverage.1")

print(root)

# "rename .coverage file for  "combine" command"
if os.path.exists(coverage_txt_path):
    # can be useful after downloading from circleci.
    #os.rename(coverage_txt_path, renamed_coverage_file)
    shutil.copy(coverage_txt_path, copied_coverage_file_path)
elif os.path.exists(coverage_file_path):
    #os.rename(coverage_file_path, renamed_coverage_file)
    shutil.copy(coverage_file_path, copied_coverage_file_path)
else:
    raise OSError("Coverage file not found.")

coverage_rc_path = os.path.join(tmp_path, ".coveragerc")

shutil.copy(os.path.join(root, ".coveragerc"), coverage_rc_path)

# Add current local project path in .coveragrc config file.
# This is important because html report needs source code to generate results
# Paths in .coverage and in local project can be different,
# so we need to specify local project path, so coverage tool can access to source code to generate html.
parser = six.moves.configparser.ConfigParser()  # type: ignore
with open(coverage_rc_path, "r") as f:
    parser.readfp(f)  # type: ignore

# add current path to 'paths' section.
cwd = os.getcwd()
paths = ["\n%s" % root, "/agent_source/"]
parser.add_section("paths")
parser.set("paths", "source", "\n".join(paths))  # type: ignore

with open(coverage_rc_path, "w") as f:
    parser.write(f)  # type: ignore

subprocess.check_call(
    "coverage combine",
    shell=True,
    cwd=tmp_path
)


subprocess.check_call(
    "coverage html",
    shell=True,
    cwd=tmp_path
)

html_report_path = os.path.join(root, "htmlcov")
shutil.rmtree(html_report_path, ignore_errors=True)
shutil.copytree(os.path.join(tmp_path, "htmlcov"), html_report_path)

if args.show:
    import webbrowser

    webbrowser.open(os.path.join(html_report_path, "index.html"))
