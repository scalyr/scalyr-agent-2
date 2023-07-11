import collections
import pathlib as pl
import shutil
import subprocess
import os
import tarfile
from typing import Dict, Type

from agent_build_refactored.tools.constants import SOURCE_ROOT, CpuArch, LibC
from agent_build_refactored.tools.builder import BuilderStep, Builder
from agent_build_refactored.build_dependencies.python import (
    PREPARE_BUILD_BASE_WITH_PYTHON_STEPS
)
from agent_build_refactored.build_dependencies.python.prepare_build_base_with_python import PrepareBuildBaseWithPythonStep

_PARENT_DIR = pl.Path(__file__).parent

PORTABLE_RUNNER_NAME = "portable_runner"


class PortablePytestRunnerBuilderStep(BuilderStep):
    def __init__(
            self,
            prepare_python_environment_step: PrepareBuildBaseWithPythonStep,
    ):
        self.prepare_python_environment_step = prepare_python_environment_step

        build_python_step = self.prepare_python_environment_step.build_python_step
        super(PortablePytestRunnerBuilderStep, self).__init__(
            name="build_portable_pytest_runner",
            context=SOURCE_ROOT,
            dockerfile=_PARENT_DIR / "Dockerfile",
            platform=self.prepare_python_environment_step.platform,
            build_contexts=[
                self.prepare_python_environment_step,
            ],
            build_args={
                "PATH_SEP": os.pathsep,
                "PYTHON_INSTALL_PREFIX": str(build_python_step.install_prefix),
                "PORTABLE_RUNNER_NAME": PORTABLE_RUNNER_NAME,
            },
            run_in_remote_builder_if_possible=True,
            cache=True,
        )

    @property
    def portable_runner_path(self) -> pl.Path:
        return self.output_dir / PORTABLE_RUNNER_NAME


class PortablePyTestRunnerBuilder(Builder):
    ARCHITECTURE: CpuArch
    LIBC: LibC

    def __init__(self):

        self.prepare_python_environment_step = PREPARE_BUILD_BASE_WITH_PYTHON_STEPS[self.LIBC][self.ARCHITECTURE]
        self.build_portable_pytest_runner_step = PortablePytestRunnerBuilderStep(
            prepare_python_environment_step=self.prepare_python_environment_step,
        )

        super(PortablePyTestRunnerBuilder, self).__init__(
            base=self.prepare_python_environment_step,
            dependencies=[
                self.build_portable_pytest_runner_step,
            ],
        )

    def build(self):
        shutil.copytree(
            self.build_portable_pytest_runner_step.output_dir,
            self.output_dir,
            dirs_exist_ok=True
        )

        source_tarball = self.output_dir / "source.tar.gz"
        with tarfile.open(source_tarball, "w:gz") as tar:
            tar.add(SOURCE_ROOT, arcname="/")

    def run_portable_pytest_runner_builder(
        self,
        output_dir: pl.Path = None,
        verbose: bool = True,
    ):
        self.run_builder(
            output_dir=output_dir,
            **{
                self.VERBOSE_ARG.name: verbose,
            }
        )


PORTABLE_PYTEST_RUNNER_BUILDERS: Dict[LibC, Dict[CpuArch, Type[PortablePyTestRunnerBuilder]]] = collections.defaultdict(dict)


for runner_libc, architectures in PREPARE_BUILD_BASE_WITH_PYTHON_STEPS.items():
    for runner_architecture, prepare_python_env_step in architectures.items():

        class _PortablePyTestRunnerBuilder(PortablePyTestRunnerBuilder):
            NAME = f"portable_pytest_runner_builder_{runner_libc.value}_{runner_architecture.value}"
            ARCHITECTURE = runner_architecture
            LIBC = runner_libc
        # step = PortablePytestRunnerBuilderStep(
        #     prepare_python_environment_step=prepare_python_env_step,
        # )

        PORTABLE_PYTEST_RUNNER_BUILDERS[runner_libc][runner_architecture] = _PortablePyTestRunnerBuilder




