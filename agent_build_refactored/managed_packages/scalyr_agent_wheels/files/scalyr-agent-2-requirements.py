#!/usr/lib/scalyr-agent-2/requirements/python3/bin/python3
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
import argparse
import configparser
import pathlib as pl
import subprocess
import sys

AGENT_REQUIREMENTS_PACKAGE_LIB_DIR = pl.Path("/usr/lib/scalyr-agent-2/requirements")
AGENT_REQUIREMENTS_PACKAGE_ETC_DIR = pl.Path("/etc/scalyr-agent-2/requirements")
AGENT_REQUIREMENTS_PACKAGE_VAR_DIR = pl.Path("/var/lib/scalyr-agent-2/requirements")

def recreate_venv():
    config_path = AGENT_REQUIREMENTS_PACKAGE_ETC_DIR / "config.ini"

    config = configparser.ConfigParser()
    config.read(config_path)
    requirements = config["requirements"]
    source = requirements["source"]
    include_binary_packages = requirements.getboolean("include_binary_packages")

    wheels_dir = AGENT_REQUIREMENTS_PACKAGE_LIB_DIR / "wheels"
    core_requirements_path = wheels_dir / "requirements.txt"
    binary_requirements_path = wheels_dir / "binary-requirements.txt"
    additional_requirements_path = AGENT_REQUIREMENTS_PACKAGE_ETC_DIR / "additional-requirements.txt"

    venv_dir = AGENT_REQUIREMENTS_PACKAGE_VAR_DIR / "venv"
    subprocess.check_call(
        [
            str(AGENT_REQUIREMENTS_PACKAGE_LIB_DIR / "python3/bin/python3"),
            "-m",
            "venv",
            str(venv_dir)
        ],
    )

    if include_binary_packages and source != "pypi":
        print(
            "WARNING: The 'include_binary_packages' option has to effect without option 'source=pypi'",
            file=sys.stderr
        )
        include_binary_packages = False

    python_executable = AGENT_REQUIREMENTS_PACKAGE_LIB_DIR / "bin/scalyr-agent-python3"

    pip_install_args = [
        str(python_executable),
        "-m",
        "pip",
        "install",
        "-r", str(core_requirements_path),
        "-v",
    ]

    # Install core requirements from local wheels.
    if source == "local":
        pip_install_args.extend([
            "--no-index",
            "--find-links", str(wheels_dir),
        ])
    else:
        # Install requirements from PyPi.
        pip_install_args.extend(["-r", str(additional_requirements_path)])
        # Also install binary requirements, if needed.
        if include_binary_packages:
            pip_install_args.extend(["-r", str(binary_requirements_path)])

    subprocess.check_call(
        pip_install_args,
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest="command")

    venv_parser = subparsers.add_parser("requirements")

    venv_parser.add_argument(
        "requirements_command",
    )

    args = parser.parse_args()

    if args.command == "requirements":
        if args.requirements_command == "recreate":
            recreate_venv()

    elif not args.command:
        print("Missing command", file=sys.stderr)
        parser.print_help(file=sys.stderr)
    else:
        print(f"Unknown command: {args.command}")
        parser.print_help(file=sys.stderr)



