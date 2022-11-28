import os
import subprocess
import sys

from agent_build_refactored.tools.constants import SOURCE_ROOT
from agent_build_refactored.tools.runner import Runner
from agent_build_refactored.managed_packages.managed_packages_builders import PREPARE_TOOLSET_GLIBC_X86_64

PORTABLE_RUNNER_NAME = "portable_runner_name"


class PortablePytestRunnerBuilder(Runner):
    BASE_ENVIRONMENT = PREPARE_TOOLSET_GLIBC_X86_64

    def build(self):

        self.run_required()

        if self.runs_in_docker:
            self.run_in_docker()
            return

        dist_path = self.output_path / "dist"
        subprocess.check_call(
            [
                "python3",
                "-m",
                "PyInstaller",
                "--onefile",
                "--distpath",
                str(dist_path),
                "--workpath",
                str(self.output_path / "build"),
                "--name",
                PORTABLE_RUNNER_NAME,
                "--add-data",
                f"tests/end_to_end_tests{os.pathsep}tests/end_to_end_tests",
                "--add-data",
                f"agent_build{os.pathsep}agent_build",
                "--add-data",
                f"agent_build_refactored{os.pathsep}agent_build_refactored",
                "--hidden-import",
                "paramiko",
                __file__
            ],
            cwd=SOURCE_ROOT
        )

    @property
    def result_runner_path(self):
        return self.output_path / "dist" / PORTABLE_RUNNER_NAME



    @classmethod
    def handle_command_line_arguments(
        cls,
        args,
    ):
        super(PortablePytestRunnerBuilder, cls).handle_command_line_arguments(args)
        builder = cls(work_dir=args.work_dir)
        builder.build()


if __name__ == '__main__':
    import pytest

    sys.path.append(str(SOURCE_ROOT))

    os.chdir(SOURCE_ROOT)
    sys.exit(pytest.main())