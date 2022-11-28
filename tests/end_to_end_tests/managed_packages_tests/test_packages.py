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

import pathlib as pl
import shlex
import subprocess
import logging
from typing import List

from agent_build_refactored.tools.constants import SOURCE_ROOT
from agent_build_refactored.managed_packages.managed_packages_builders import PYTHON_PACKAGE_NAME, \
    AGENT_LIBS_PACKAGE_NAME, AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME

logger = logging.getLogger(__name__)


def _get_package_from_repo_dir(
        package_name: str,
        package_type: str,
        repo_dir: pl.Path
):
    if package_type == "deb":
        package_dir_path = repo_dir / f"pool/main/s/{package_name}"
    elif package_type == "rpm":
        package_dir_path = repo_dir
    else:
        raise Exception(f"Unknown package type: {package_type}")

    found = list(package_dir_path.rglob(f"{package_name}*.{package_type}"))
    assert len(found) == 1
    return found[0]


def _verify_package_subdirectories(
        repo_dir: pl.Path,
        package_type: str,
        package_name: str,
        output_dir: pl.Path,
        expected_folders: List[str]
):
    """
    Verify structure if the agent's dependency packages.
    First,  we have to ensure that all package files are located inside special subdirectory and nothing has leaked
    outside.
    :param package_type: Type of the package, e.g. deb, rpm.
    :param package_name: Name of the package.
    :param output_dir: Directory where to extract a package.
    :param expected_folders: List of paths that are expected to be in this package.
    """

    package_path = _get_package_from_repo_dir(
        package_name=package_name,
        package_type=package_type,
        repo_dir=repo_dir
    )

    package_root = output_dir / package_name
    package_root.mkdir()

    if package_type == "deb":
        subprocess.check_call([
            "dpkg-deb", "-x", str(package_path), str(package_root)
        ])
    elif package_type == "rpm":
        escaped_package_path = shlex.quote(str(package_path))
        command = f"rpm2cpio {escaped_package_path} | cpio -idmv"
        subprocess.check_call(
            command, shell=True, cwd=package_root,
            env={"LD_LIBRARY_PATH": "/lib64"}
        )
    else:
        raise Exception(f"Unknown package type {package_type}.")

    remaining_paths = set(package_root.glob("**/*"))

    for expected in expected_folders:
        expected_path = package_root / expected
        for path in list(remaining_paths):
            if str(path).startswith(str(expected_path)) or str(path) in str(expected_path):
                remaining_paths.remove(path)

    assert len(remaining_paths) == 0, "Something remains outside if the expected package structure."


def test_dependency_packages(
        package_builder,
        tmp_path,
        repo_dir
):
    # Verify structure of the package and make sure there's no any file outside it.

    package_type = package_builder.PACKAGE_TYPE

    _verify_package_subdirectories(
        repo_dir=repo_dir,
        package_type=package_builder.PACKAGE_TYPE,
        package_name=PYTHON_PACKAGE_NAME,
        output_dir=tmp_path,
        expected_folders=[
            f"usr/lib/{AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME}/",
            f"usr/share/{AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME}/",
            # Depending on its type, a package also may install its own "metadata", so we have to take it into
            # account too.
            f"usr/share/doc/{PYTHON_PACKAGE_NAME}/" if package_type == "deb" else "usr/lib/.build-id/"
        ]
    )

    # Verify structure of the package and make sure there's no any file outside it.
    _verify_package_subdirectories(
        repo_dir=repo_dir,
        package_type=package_builder.PACKAGE_TYPE,
        package_name=AGENT_LIBS_PACKAGE_NAME,
        output_dir=tmp_path,
        expected_folders=[
            f"usr/lib/{AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME}/",
            f"usr/share/{AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME}/",
            # Depending on its type, a package also may install its own "metadata", so we have to take it into
            # account too.
            f"usr/share/doc/{AGENT_LIBS_PACKAGE_NAME}/" if package_type == "deb" else "usr/lib/.build-id/"
        ]
    )


def test_packages(
        tmp_path,
        add_repo,
        install_package,
        repo_url
):
    add_repo(repo_url=repo_url)

    logger.info(f"Install package {AGENT_LIBS_PACKAGE_NAME}")
    install_package(package_name=AGENT_LIBS_PACKAGE_NAME)

    logger.info("Execute simple sanity test script for the python interpreter and its libraries.")
    subprocess.check_call(
        [
            f"/usr/lib/{AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME}/bin/python3",
            "tests/end_to_end_tests/managed_packages_tests/verify_python_interpreter.py"
        ],
        env={
            # It's important to override the 'LD_LIBRARY_PATH' to be sure that libraries paths from the test runner
            # frozen binary are not leaked to a script's process.
            "LD_LIBRARY_PATH": "",
            "PYTHONPATH": str(SOURCE_ROOT),
        },
    )
