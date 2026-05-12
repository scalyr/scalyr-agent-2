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

import argparse
import sys
import os
import tarfile
import tempfile

import pytest

# We have to explicitly import all needed libraries here in order to help PyInstaller to bundle them,
# because we do not bundle agent's source code and PyInstaller does not have ability to determine
# all requirements.
import logging # NOQA
import logging.handlers # NOQA
import requests  # NOQA
import six # NOQA
import boto3 # NOQA

if __name__ == "__main__":
    # We use this file as an entry point for the pytest runner.
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "source_tarball_path",
        help="Path to a tarball with agent's source code."
    )

    parser.add_argument(
        "--set-env",
        dest="set_env",
        required=False,
        action="append",
        help="Set additional environment variable. Since this executable is produced by the Pyinstaller,"
             "it prevents from setting environment variables directly, so we have to have such option."
    )

    args, other_argv = parser.parse_known_args()

    source_tarball_path = args.source_tarball_path
    temp_dir = tempfile.TemporaryDirectory("agent_e2e_test_source")

    if args.set_env:
        for env_str in args.set_env:
            name, value = env_str.split("=")
            os.environ[name] = value

    source_root = temp_dir.name
    with tarfile.open(source_tarball_path, ":gz") as tar:
        tar.extractall(path=source_root)

    sys.path.append(str(source_root))

    os.chdir(source_root)

    exit_code = pytest.main(args=other_argv)
    temp_dir.cleanup()
    sys.exit(exit_code)
