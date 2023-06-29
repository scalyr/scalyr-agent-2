import argparse
import pathlib as pl
import shutil

from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.tools.builder import BuilderStep, Builder
from agent_build_refactored.build_dependencies.python.build_python_for_packages import BuildPythonForPackagesStep
from agent_build_refactored.build_dependencies.ubuntu_toolset import LatestUbuntuToolsetStep
from agent_build_refactored.build_dependencies.python.prepare_build_base_with_python import PrepareBuildBaseWithPythonStep


class LinuxPackageBuilder(Builder):
    ENTRYPOINT_SCRIPT = pl.Path(__file__)

    def __init__(
        self
    ):

        python_install_prefix = pl.Path("/opt/scalyr-agent-2/python3")
        python_dependencies_install_prefix = pl.Path("/usr/local")

        self.prepare_build_base_with_python = PrepareBuildBaseWithPythonStep(
            python_version="3.11.2",
            openssl_version="3.0.7",
            install_prefix=python_install_prefix,
            dependencies_install_prefix=python_dependencies_install_prefix,
            architecture=CpuArch.x86_64,
            libc="musl",
        )

        self.build_python_step = self.prepare_build_base_with_python.build_python_step

        super(LinuxPackageBuilder, self).__init__(
            name="build_linux_package",
            base=self.prepare_build_base_with_python,
            dependencies=[
                self.build_python_step,
            ],
        )

    def build(self):
        python_dir = self.build_python_step.output_dir

        shutil.copytree(
            python_dir,
            self.output_dir / "python"
        )


def main(args=None):
    builder = LinuxPackageBuilder()

    parser = LinuxPackageBuilder.create_parser()
    args = parser.parse_args(args=args)

    run_builder = builder.run_builder_from_command_line(args=args)
    run_builder()


if __name__ == '__main__':
    main()


