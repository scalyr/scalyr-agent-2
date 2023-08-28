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

import subprocess

import pytest


def test_fips(test_image_name, image_builder_name):

    if "fips" not in image_builder_name:
        pytest.skip("Only for fips images.")

    result = subprocess.run(
        [
            "docker",
            "run",
            "-i",
            "--rm",
            test_image_name,
            "/bin/bash",
            "-c",
            'openssl md5 <<< "123456789"',
        ],
        capture_output=True,
    )

    stderr = result.stderr.decode()

    assert result.returncode != 0
    assert "routines:inner_evp_generic_fetch:unsupported" in stderr
    assert "evp_md_init_internal:initialization error" in stderr

    result = subprocess.run(
        [
            "docker",
            "run",
            "-i",
            "--rm",
            test_image_name,
            "/bin/bash",
            "-c",
            'openssl sha256 <<< "123456789"',
        ],
        check=True,
        capture_output=True,
    )

    stdout = result.stdout.decode()

    assert (
        "SHA256(stdin)= 6d78392a5886177fe5b86e585a0b695a2bcd01a05504b3c4e38bc8eeb21e8326"
        in stdout
    )
