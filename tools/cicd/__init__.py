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
This script helps GitHub Actions CI/CD to get information about steps that can be run and cached in parallel jobs. That
has to decrease overall build time.

How it works:


"""
import argparse
from typing import Dict, List


# Import modules that define any runner that is used during the builds.
# It is important to import them before the import of the 'ALL_RUNNERS' or otherwise, runners from missing mudules
# won't be presented in the "ALL_RUNNERS" final collection.
import tests.end_to_end_tests  # NOQA
import tests.end_to_end_tests.run_in_remote_machine.portable_pytest_runner # NOQA
import tests.end_to_end_tests.managed_packages_tests.conftest  # NOQA

# Import ALL_RUNNERS global collection only after all modules that define any runner are imported.
from agent_build_refactored.tools.runner import ALL_RUNNERS

from agent_build_refactored.tools.runner import Runner, RunnerStep, group_steps_by_stages, remove_steps_from_stages, sort_and_filter_steps

# Suffix that is appended to all steps cache keys. CI/CD cache can be easily invalidated by changing this value.
CACHE_VERSION_SUFFIX = "v15"


def get_all_used_steps() -> List[RunnerStep]:
    """
    Get list of all steps that are used in the whole project.
    """
    all_steps = []
    for runner_cls in ALL_RUNNERS:
        for step in runner_cls.get_all_steps(recursive=True):
            all_steps.append(step)

    return sort_and_filter_steps(steps=all_steps)


class CacheableStepRunner(Runner):
    """
    A "wrapper" runner class that is needed to locate and run cacheable steps.
    """
    STEP: RunnerStep

    @classmethod
    def get_all_required_steps(cls) -> List[RunnerStep]:
        return [cls.STEP]

    @classmethod
    def add_command_line_arguments(cls, parser: argparse.ArgumentParser):
        super(CacheableStepRunner, cls).add_command_line_arguments(parser=parser)

        subparsers = parser.add_subparsers(dest="command")

        subparsers.add_parser("run-cacheable-step")

    @classmethod
    def handle_command_line_arguments(
        cls,
        args,
    ):
        super(CacheableStepRunner, cls).handle_command_line_arguments(args=args)

        if args.command == "run-cacheable-step":
            cls._run_steps(
                steps=[cls.STEP],
                work_dir=pl.Path(args.work_dir)
            )
            exit(0)
        else:
            print(f"Unknown command: {args.command}", file=sys.stderr)


def get_steps_runners(stages: List):
    result_runners = {}

    for stage in stages:
        for step_id, step in stage.items():
            _RunnerCls = result_runners.get(step.id)
            if _RunnerCls is None:
                class _RunnerCls(CacheableStepRunner):
                    STEP = step
                    CLASS_NAME_ALIAS = f"{step_id}_cached"

                result_runners[step_id] = _RunnerCls

    return result_runners


all_used_steps: Dict[str, RunnerStep] = {step.id: step for step in get_all_used_steps()}

step_stages = group_steps_by_stages(steps=list(all_used_steps.values()))

steps_runners = get_steps_runners(stages=step_stages)

