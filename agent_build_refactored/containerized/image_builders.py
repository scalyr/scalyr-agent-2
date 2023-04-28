import argparse
import shutil
import subprocess
from typing import List

from agent_build_refactored.tools.constants import Architecture, SOURCE_ROOT
from agent_build_refactored.tools.runner import Runner, RunnerStep


from agent_build_refactored.managed_packages.managed_packages_builders import BUILD_OPENSSL_3_STEPS, BUILD_PYTHON_WITH_OPENSSL_3_STEPS, BUILD_AGENT_LIBS_VENV_STEPS


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

        for architecture in SUPPORTED_IMAGE_ARCHITECTURES:

            build_python_step = BUILD_PYTHON_WITH_OPENSSL_3_STEPS[architecture]

            build_python_output = build_python_step.get_output_directory(work_dir=self.work_dir)

            build_context_path = self.output_path / "build_context"
            build_context_path.mkdir()

            arch_dir_name = architecture.as_docker_platform.value.to_dashed_str
            arch_dir = build_context_path / arch_dir_name
            arch_dir.mkdir()

            python_dir = arch_dir / "python"
            python_dir.mkdir()

            shutil.copytree(
                build_python_output,
                python_dir,
                dirs_exist_ok=True
            )

            dockerfile_path = SOURCE_ROOT / "agent_build_refactored/containerized/Dockerfile"

            image_name = "teeeest"
            arch_image_tag = architecture.as_docker_platform.value.to_dashed_str
            subprocess.run(
                [
                    "docker",
                    "buildx",
                    "build",
                    "-f", str(dockerfile_path),
                    "-t", image_name,
                    "--platform", str(architecture.as_docker_platform.value),
                    "--build-arg", f"ARCH_DIR_NAME={arch_dir_name}",
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








