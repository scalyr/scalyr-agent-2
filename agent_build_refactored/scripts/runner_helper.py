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

"""
This helper script acts as an entry point for Runners allowing to execute them without direct access.
Script caller specifies FQDN of the builder class, and script imports it and executes.
Needed for GitHub Action CI/CD.
"""

import argparse
import sys
import pathlib as pl
import importlib


SOURCE_ROOT = pl.Path(__file__).parent.parent.parent
# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(SOURCE_ROOT))

from agent_build_refactored.tools.runner import Runner, cleanup


if __name__ == "__main__":
    from agent_build_refactored.tools import init_logging

    init_logging()
    cleanup()

    base_parser = argparse.ArgumentParser()
    base_parser.add_argument("builder_class_fqdn")
    base_args, other_args = base_parser.parse_known_args()
    module_name, class_name = base_args.builder_class_fqdn.rsplit(".", 1)

    module = importlib.import_module(module_name)
    builder_cls: Runner = getattr(module, class_name)

    parser = argparse.ArgumentParser()

    builder_cls.add_command_line_arguments(parser=parser)

    args = parser.parse_args(args=other_args)

    builder_cls.handle_command_line_arguments(args=args)
