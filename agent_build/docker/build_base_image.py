#!/usr/env python3
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

import os
import subprocess
import pathlib as pl

SOURCE_ROOT = pl.Path(__file__).parent.parent.parent

PYTHON_BASE_IMAGE = os.environ["PYTHON_BASE_IMAGE"]
DISTRO_NAME = os.environ["DISTRO_NAME"]
RESULT_IMAGE_NAME = os.environ["RESULT_IMAGE_NAME"]
PLATFORM = os.environ["PLATFORM"]

IMAGE_TARBALL_OUTPUT_PATH = pl.Path("STEP_OUTPUT_PATH") / RESULT_IMAGE_NAME

subprocess.check_call([
    "docker",
    "buildx",
    "build",
    "-t", RESULT_IMAGE_NAME,
    "-f",
    str(SOURCE_ROOT / "agent_build/docker/base.Dockerfile"),
    "--platform", PLATFORM,
    "--build-arg",
    f"PYTHON_BASE_IMAGE={PYTHON_BASE_IMAGE}",
    "--build-arg",
    f"DISTRO_NAME={DISTRO_NAME}",
    "-o",
    f"type=oci,dest=out/out.tar {IMAGE_TARBALL_OUTPUT_PATH}",
    str(SOURCE_ROOT)
])