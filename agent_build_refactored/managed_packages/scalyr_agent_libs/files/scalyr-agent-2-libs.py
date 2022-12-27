#!/usr/lib/scalyr-agent-2/bin/scalyr-agent-python3
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


def recreate_venv():
    config_path = pl.Path("/etc/scalyr-agent-2/agent-libs/config.ini")

    config = configparser.ConfigParser()
    config.read(config_path)
    print(config.sections())
    requirements = config["requirements"]
    source = requirements["source"]
    include_binary_packages = requirements.getboolean("include_binary_packages")

    wheels_dir = pl.Path("/usr/share/scalyr-agent-2/agent-libs/wheels")
    core_requirements_path = pl.Path("/usr/share/scalyr-agent-2/agent-libs/requirements.txt")
    binary_requirements_path = pl.Path("/usr/share/scalyr-agent-2/agent-libs/binary-requirements.txt")
    additional_requirements_path = pl.Path("/etc/scalyr-agent-2/agent-libs/additional-requirements.txt")
    venv_dir = pl.Path("/var/lib/scalyr-agent-2/agent-libs/venv")
    python_executable = "/usr/lib/scalyr-agent-2/bin/scalyr-agent-python3"
    subprocess.check_call(
        [str(python_executable), "-m", "venv", str(venv_dir)],
    )

    if include_binary_packages and source != "pypi":
        print(
            "WARNING: The 'include_binary_packages' option has to effect without option 'source=pypi'",
            file=sys.stderr
        )
        include_binary_packages = False

    venv_python_executable = venv_dir / "bin/python3"

    pip_install_args = [
        str(venv_python_executable),
        "-m",
        "pip",
        "install",
        "-r", str(core_requirements_path),
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

    if args.command == "venv":
        if args.venv_command == "recreate":
            recreate_venv()

    elif not args.command:
        print("Missing command", file=sys.stderr)
        parser.print_help(file=sys.stderr)
    else:
        print(f"Unknown command: {args.command}")
        parser.print_help(file=sys.stderr)



