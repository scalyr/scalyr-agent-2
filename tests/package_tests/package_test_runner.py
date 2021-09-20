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
# This script is just a "wrapper" for all other tests in the folder.
# The script accepts a package type, so it can run an appropriate test for the package.
#

import pathlib as pl
import argparse
import subprocess
import sys
import logging

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] [%(filename)s] %(message)s")


_PARENT_DIR = pl.Path(__file__).parent.absolute().resolve()
__SOURCE_ROOT__ = _PARENT_DIR.parent.parent

# Add the source root to the PYTHONPATH. Since this is a script,this is required in order to be able to
# import inner modules.
sys.path.append(str(__SOURCE_ROOT__))

# Import internal modules only after the PYTHONPATH is tweaked.
from tests.package_tests import k8s_test, docker_test, package_test


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


if args.docker_image:

    if args.package_test_path:
        executable_mapping_args = ["-v", f"{args.package_test_path}:/tmp/test_executable"]
        test_executable_path = "/tmp/test_executable"
    else:
        executable_mapping_args = []
        test_executable_path = "/scalyr-agent-2/tests/package_tests/package_test_runner.py"

    # Run the test inside the docker.
    # fmt: off
    subprocess.check_call(
        [
            "docker", "run", "-i", "--rm", "--init",
            "-v", f"{__SOURCE_ROOT__}:/scalyr-agent-2",
            "-v", f"{package_path}:/tmp/package",
            *executable_mapping_args,
            # specify the image.
            args.docker_image,
            # Command to run the test executable inside the container.
            test_executable_path,
            "--package-type", package_type,
            "--package-path", f"/tmp/package", "--scalyr-api-key", args.scalyr_api_key
        ]
    )
    # fmt: on
else:

    if package_type in ["deb", "rpm", "msi", "tar"]:
        package_test.run(
            package_path=package_path,
            package_type=package_type,
            scalyr_api_key=args.scalyr_api_key
        )
    elif package_type == "k8s":
        k8s_test.run(
            builder_path=package_path,
            scalyr_api_key=args.scalyr_api_key
        )
    elif package_type in ["docker-json"]:
        docker_test.run(
            builder_path=package_path,
            scalyr_api_key=args.scalyr_api_key
        )
    else:
        raise ValueError(f"Wrong package type - {package_type}")