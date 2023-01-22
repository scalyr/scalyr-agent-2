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
This module defines builder for agent's "convenient" install script.
"""

import argparse

from agent_build_refactored.tools.constants import SOURCE_ROOT
from agent_build_refactored.tools.runner import Runner


class ConvenienceScriptBuilder(Runner):
    def build(self, repo_url: str, public_key_url: str):
        self.run_required()

        template_path = (
            SOURCE_ROOT
            / "agent_build_refactored/managed_packages/convenience_install_script/install_agent_template.sh"
        )
        content = template_path.read_text()
        content = content.replace("{ % REPLACE_REPOSITORY_URL % }", repo_url)
        content = content.replace("{ % REPLACE_PUBLIC_KEY_URL % }", public_key_url)
        result_file = self.output_path / "install-agent.sh"
        result_file.write_text(content)

    @classmethod
    def add_command_line_arguments(cls, parser: argparse.ArgumentParser):
        super(ConvenienceScriptBuilder, cls).add_command_line_arguments(parser)

        parser.add_argument("--repo_url", required=True)

        parser.add_argument("public_key", required=True)

    @classmethod
    def handle_command_line_arguments(
        cls,
        args,
    ):
        super(ConvenienceScriptBuilder, cls).handle_command_line_arguments(args)
        builder = cls()
        builder.build(repo_url=args.repo_url, public_key=args.public_key)
