import argparse
import shutil
import pathlib as pl
import subprocess
from typing import List

from agent_build_refactored.tools.constants import Architecture, SOURCE_ROOT
from agent_build_refactored.tools.runner import Runner, RunnerStep


from agent_build_refactored.managed_packages.managed_packages_builders import (
    BUILD_OPENSSL_3_STEPS,
    BUILD_PYTHON_WITH_OPENSSL_3_STEPS,
    BUILD_AGENT_LIBS_VENV_STEPS,
    AGENT_SUBDIR_NAME,
)
from agent_build_refactored.build_python.build_python_steps import create_python_files, create_agent_libs_venv_files
from agent_build_refactored.prepare_agent_filesystem import build_linux_fhs_agent_files, add_config, render_agent_executable_script

SUPPORTED_IMAGE_ARCHITECTURES = [
    Architecture.X86_64,
]


class AgentImageBuilder(Runner):
    @classmethod
    def get_all_required_steps(cls) -> List[RunnerStep]:
        result = []
        for steps in [BUILD_OPENSSL_3_STEPS, BUILD_PYTHON_WITH_OPENSSL_3_STEPS, BUILD_AGENT_LIBS_VENV_STEPS]:

            for arch in SUPPORTED_IMAGE_ARCHITECTURES:
                result.append(steps[arch])
        return result

    def build(self):
        self.prepare_runer()

        build_context_path = self.output_path / "build_context"
        build_context_path.mkdir()

        agent_filesystem_root = build_context_path / "agent_filesystem_root"

        # Build 'FHS-structured' filesystem.
        build_linux_fhs_agent_files(
            output_path=agent_filesystem_root,
        )

        add_config(
            base_config_source_path=SOURCE_ROOT / "docker" / "docker-json-config",
            output_path=agent_filesystem_root / "etc/scalyr-agent-2",
            #additional_config_paths=type(self).IMAGE_TYPE_SPEC.additional_config_paths,
        )

        install_root_executable_path = (
            agent_filesystem_root / f"usr/share/{AGENT_SUBDIR_NAME}/bin/scalyr-agent-2"
        )

        render_agent_executable_script(
            python_executable="/var/opt/scalyr-agent-2/venv/bin/python3",
            agent_main_script_path=pl.Path("/usr/share/scalyr-agent-2/py/scalyr_agent/agent_main.py"),
            output_file=install_root_executable_path
        )

        # Also link agent executable to usr/sbin
        usr_sbin_executable = agent_filesystem_root / "usr/sbin/scalyr-agent-2"
        usr_sbin_executable.unlink()
        usr_sbin_executable.symlink_to("../share/scalyr-agent-2/bin/scalyr-agent-2")

        # Need to create some docker specific directories.
        pl.Path(agent_filesystem_root / "var/log/scalyr-agent-2/containers").mkdir()

        # Create architecture-dependent files, such as Python interpreter, etc.
        for architecture in SUPPORTED_IMAGE_ARCHITECTURES:

            docker_platform = architecture.as_docker_platform.value

            platform_variant = docker_platform.variant or ""
            arch_dir_name = f"{docker_platform.os}_{docker_platform.architecture}_{platform_variant}"
            arch_dir = build_context_path / "architectures" / arch_dir_name
            arch_dir.mkdir(parents=True)

            python_dir = arch_dir / "python"

            build_python_step = BUILD_PYTHON_WITH_OPENSSL_3_STEPS[architecture]
            build_python_output = build_python_step.get_output_directory(work_dir=self.work_dir)
            create_python_files(
                build_python_step_output=build_python_output,
                output=python_dir,
            )

            build_agent_libs_step = BUILD_AGENT_LIBS_VENV_STEPS[architecture]
            build_agent_libs_step_output = build_agent_libs_step.get_output_directory(
                work_dir=self.work_dir
            )

            venv_dir = arch_dir / f"venv/var/opt" / AGENT_SUBDIR_NAME / "venv"
            create_agent_libs_venv_files(
                build_libs_venv_step_output=build_agent_libs_step_output,
                output=venv_dir
            )

        dockerfile_path = SOURCE_ROOT / "agent_build_refactored/containerized/Dockerfile"

        image_name = "teeeest"

        platform_args = []
        for architecture in SUPPORTED_IMAGE_ARCHITECTURES:
            platform_args.extend([
                "--platform",
                str(architecture.as_docker_platform.value)
            ])

        subprocess.run(
            [
                "docker",
                "buildx",
                "build",
                "-f", str(dockerfile_path),
                "-t", image_name,
                "--load",
                *platform_args,
                str(build_context_path),
            ]
        )



    @classmethod
    def handle_command_line_arguments(
        cls,
        args,
    ):
        super(AgentImageBuilder, cls).handle_command_line_arguments(args=args)

        builder = cls(work_dir=args.work_dir)

        builder.build()








