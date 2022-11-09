#!/usr/libexec/scalyr-agent-2-python3
import os
import datetime
import sys
import pathlib as pl


sys.path.append(str(pl.Path(os.environ["SOURCE_ROOT"])))

from agent_build_refactored.tools.steps_libs.subprocess_with_log import check_call_with_log


def main(
        package_name: str,
        package_architecture: str,
        package_type: str,
        python_package_root_path: str,
        python_version: str,
):

    description = ""

    ts = datetime.datetime.now().timestamp()
    checksum = os.environ["CHECKSUM"]
    package_version = f"{python_version}-{int(ts)}-{checksum}"

    check_call_with_log(
        [
            # fmt: off
            "fpm",
            "-s", "dir",
            "-a", package_architecture,
            "-t", package_type,
            "-n", package_name,
            "-v", package_version,
            "-C", str(python_package_root_path),
            "--license", '"Apache 2.0"',
            "--vendor", "Scalyr %s",
            "--provides", "scalyr-agent-dependencies",
            "--description", description,
            "--depends", "bash >= 3.2",
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
        python_package_root_path=os.environ["BUILD_PYTHON"],
        python_version=os.environ["PYTHON_VERSION"]
    )