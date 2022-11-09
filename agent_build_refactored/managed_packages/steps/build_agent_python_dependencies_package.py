#!/usr/libexec/scalyr-agent-2-python3
import os
import datetime
import re
import sys
import pathlib as pl


sys.path.append(str(pl.Path(os.environ["SOURCE_ROOT"])))

from agent_build_refactored.tools.steps_libs.subprocess_with_log import check_call_with_log


def main(
        package_name: str,
        package_architecture: str,
        package_type: str,
        python_package_name: str,
        python_version: str,
):

    description = ""

    ts = datetime.datetime.now().timestamp()
    checksum = os.environ["CHECKSUM"]
    package_version = f"{int(ts)}-{checksum}"

    # look for python dependency package
    build_python_package_output = pl.Path(os.environ["BUILD_PYTHON_PACKAGE"])

    found_python_packages = list(build_python_package_output.glob(
        f"{python_package_name}_{python_version}-*-*_{package_architecture}.{package_type}"
    ))

    packages_num = len(found_python_packages)
    assert packages_num == 1, f"Number of python packages has to be 1, but got {packages_num}"

    python_package_path = found_python_packages[0]
    python_package_file_name = python_package_path.name

    m = re.search(
        rf"{python_package_name}_({python_version}-\d+-[A-Za-z\d]+)_{package_architecture}\.{package_type}",
        python_package_file_name
    )

    assert m is not None, f"Can't fetch python package version from its file name - {python_package_file_name}"

    python_package_version = m.group(1)

    package_root_path = os.environ["BUILD_AGENT_PYTHON_DEPENDENCIES"]

    check_call_with_log(
        [
            # fmt: off
            "fpm",
            "-s", "dir",
            "-a", package_architecture,
            "-t", package_type,
            "-n", package_name,
            "-v", package_version,
            "-C", str(package_root_path),
            "--license", '"Apache 2.0"',
            "--vendor", "Scalyr %s",
            "--provides", "scalyr-agent-2-dependencies",
            "--description", description,
            "--depends", "bash >= 3.2",
            "--depends", f"scalyr-agent-python3 = {python_package_version}",
            "--url", "https://www.scalyr.com",
            "--deb-user", "root",
            "--deb-group", "root",
            # "--deb-changelog", "changelog-deb",
            "--rpm-user", "root",
            "--rpm-group", "root",
            # "--rpm-changelog", "changelog-rpm",
            # "  --before-install preinstall.sh "
            # "  --after-install postinstall.sh "
            # "  --before-remove preuninstall.sh "
            # fmt: on
        ],
        cwd=str(os.environ["STEP_OUTPUT_PATH"])
    )


if __name__ == '__main__':
    main(
        package_name=os.environ["PACKAGE_NAME"],
        package_architecture=os.environ["PACKAGE_ARCHITECTURE"],
        package_type=os.environ["PACKAGE_TYPE"],
        python_package_name=os.environ["PYTHON_PACKAGE_NAME"],
        python_version=os.environ["PYTHON_VERSION"]
    )