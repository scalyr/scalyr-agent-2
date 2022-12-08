import argparse
import collections
import json
import os
import pathlib as pl
import sys

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
import time

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

MATRICES_PATH = pl.Path(os.environ["MATRICES_PATH"])

used_builders = []

existing_runners = collections.defaultdict(dict)
for name, runner_cls in ALL_USED_BUILDERS.items():
    for step in runner_cls.get_all_cacheable_steps():
        if not step.github_actions_settings.pre_build_in_separate_job:
            continue

        if step.id in existing_runners[name]:
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

        existing_runners[name][step.id] = StepWrapperRunner


if __name__ == '__main__':

    result_matrix = {"include": []}

    for matrix_file in MATRICES_PATH.glob("*.json"):
        matrix = json.loads(matrix_file.read_text())
        for job in matrix["include"]:
            builder_name = job["name"]

            if builder_name not in existing_runners:
                continue

            for runner in existing_runners[builder_name]:
                result_matrix["include"].append(
                    {
                        "name": f"Pre-build: {runner.REQUIRED_STEPS[0].name}",
                        "step-runner-fqdn": runner.get_fully_qualified_name(),
                        "os": "ubuntu-20.04",
                        "python-version": "3.8.13",
                    }
                )

    print(json.dumps(result_matrix))
