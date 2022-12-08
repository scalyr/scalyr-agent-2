import argparse
import json
import pathlib as pl
import sys

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(pl.Path(__file__).parent.parent.parent))

from agent_build_refactored.tools.constants import SOURCE_ROOT
from agent_build_refactored.tools.runner import Runner, RunnerStep
from agent_build_refactored.docker_image_builders import IMAGES_PYTHON_VERSION

from agent_build_refactored.docker_image_builders import (
    ALL_IMAGE_BUILDERS,
)

from agent_build_refactored.managed_packages.managed_packages_builders import ALL_MANAGED_PACKAGE_BUILDERS


ALL_USED_BUILDERS = {
    **ALL_IMAGE_BUILDERS,
    **ALL_MANAGED_PACKAGE_BUILDERS
}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--matrices-path",
        required=True
    )
    args = parser.parse_args()

    matrices_path = pl.Path(args.matrices_path)

    used_builders = []

    for matrix_file in matrices_path.glob("*.json"):
        print("!!!!")
        print(matrix_file.read_text())
        matrix = json.loads(matrix_file.read_text())
        for job in matrix["include"]:
            builder_name = job["name"]
            builder_cls = ALL_USED_BUILDERS[builder_name]
            used_builders.append(builder_cls)

    result_matrix = {"include": []}
    for runner_cls in used_builders:
        for step in runner_cls.get_all_cacheable_steps():
            if not step.github_actions_settings.pre_build_in_separate_job:
                continue

            # Create "dummy" Runner for each runner step that has to be pre-built, this dummy runner will be executed
            # by its fqdn to run the step.
            class StepWrapperRunner(Runner):
                REQUIRED_STEPS = [step]

            # Since this runner class is created dynamically we have to generate a constant fqdn for it.
            StepWrapperRunner.assign_fully_qualified_name(
                class_name="pre-built-",
                module_name=__name__,
                class_name_suffix=step.id,
            )

            result_matrix["include"].append(
                {
                    "name": f"Pre-build: {StepWrapperRunner.REQUIRED_STEPS[0].name}",
                    "step-runner-fqdn": StepWrapperRunner.get_fully_qualified_name(),
                    "os": "ubuntu-20.04",
                    "python-version": "3.8.13",
                }
            )

    print(json.dumps(result_matrix))
