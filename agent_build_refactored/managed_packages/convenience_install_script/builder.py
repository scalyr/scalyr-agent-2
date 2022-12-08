import argparse

from agent_build_refactored.tools.constants import SOURCE_ROOT
from agent_build_refactored.tools.runner import Runner


class ConvenienceScriptBuilder(Runner):
    def build(
        self,
        repo_url: str,
        public_key_url: str
    ):
        self.run_required()

        template_path = SOURCE_ROOT / "agent_build_refactored/managed_packages/convenience_install_script/install_agent_template.sh"
        content = template_path.read_text()
        content = content.replace("{ % REPLACE_REPOSITORY_URL % }", repo_url)
        content = content.replace("{ % REPLACE_PUBLIC_KEY_URL % }", public_key_url)
        result_file = self.output_path / "install-agent.sh"
        result_file.write_text(content)

    @classmethod
    def add_command_line_arguments(cls, parser: argparse.ArgumentParser):
        super(ConvenienceScriptBuilder, cls).add_command_line_arguments(parser)

        parser.add_argument(
            "--repo_url",
            required=True
        )

        parser.add_argument(
            "public_key",
            required=True
        )

    @classmethod
    def handle_command_line_arguments(
        cls,
        args,
    ):
        super(ConvenienceScriptBuilder, cls).handle_command_line_arguments(args)
        builder = cls()
        builder.build(
            repo_url=args.repo_url,
            public_key=args.public_key
        )
