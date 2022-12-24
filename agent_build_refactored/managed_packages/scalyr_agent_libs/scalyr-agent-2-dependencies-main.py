#!/usr/lib/scalyr-agent-2-dependencies/python3/bin/python3
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
    config_path = pl.Path("/etc/scalyr-agent-2/requirements/config.ini")
    config_path = pl.Path("/Users/arthur/PycharmProjects/scalyr-agent-2-final/agent_build_refactored/managed_packages/scalyr_agent_libs/files/config/config.ini")

    config = configparser.ConfigParser()
    config.read(config_path)

    requirements = config["requirements"]
    source = requirements["source"]

    if source == "local":
        wheels_dir = pl.Path("/usr/share/scalyr-agent-2/scalyr-agent-libs/wheels")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest="command")

    venv_parser = subparsers.add_parser("venv")

    venv_parser.add_argument(
        "venv_command",
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



