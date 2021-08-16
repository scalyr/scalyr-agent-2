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
#
# This script is just a "wrapper" for all other test scripts in the folder.
# The script accepts a package type, so it can pick an appropriate test script for this type for this package and run it.
#
import pathlib as pl
import argparse
import subprocess

_PARENT_DIR = pl.Path(__file__).parent


parser = argparse.ArgumentParser()

parser.add_argument("--package-path", required=True)
parser.add_argument("--package-type", required=True)
parser.add_argument("--package-test-path")
parser.add_argument("--docker-image")
parser.add_argument("--scalyr-api-key", required=True)


args = parser.parse_args()

package_path = pl.Path(args.package_path)
package_type = args.package_type

if args.package_test_path:
    package_test_path = pl.Path(args.package_test_path)
else:
    if package_type in ["deb", "rpm", "msi", "tar"]:
        package_test_path = _PARENT_DIR / "package_test.py"
    elif package_type == "k8s":
        package_test_path = _PARENT_DIR / "k8s_test.py"
    elif package_type in ["docker-json"]:
        package_test_path = _PARENT_DIR / "docker_test.py"
    else:
        raise ValueError(f"Wrong package type - {package_type}")

if args.docker_image:
    # Run the test inside the docker.
    # fmt: off
    subprocess.check_call(
        [
            "docker", "run", "-i", "--rm",
            # map the test executable.
            "-v", f"{package_test_path}:/package_test",
            # map the package file.
            "-v", f"{package_path}:/{package_path.name}", "--init",
            # specify the image.
            "args.docker_image",
            # Command to run the test executable inside the container.
            "/package_test", "--package-path", f"/{package_path.name}", "--scalyr-api-key", args.scalyr_api_key
        ]
    )
    # fmt: on
else:
    # Rus the test script.
    subprocess.check_call(
        [
            str(package_test_path), "--package-path", str(package_path),
            "--scalyr-api-key", args.scalyr_api_key
        ]
    )
