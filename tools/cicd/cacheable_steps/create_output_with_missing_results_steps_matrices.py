# Copyright 2014-2023 Scalyr Inc.
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
This script create GitHub Actions job matrices for steps with missing caches.
The output of this script has to be written directly to the "GITHUB_OUTPUT" environment variable of the job step.
The output defines job matrix for each stage job and whether this job has to be skipped.
"""

import io
import json
import pathlib as pl
import sys


# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.

SCRIPT_PATH = pl.Path(__file__).absolute()
SOURCE_ROOT = SCRIPT_PATH.parent.parent.parent.parent
sys.path.append(str(SOURCE_ROOT))

from agent_build_refactored.tools.runner import remove_steps_from_stages
from tools.cicd.cacheable_steps import step_stages, steps_runners, CACHE_VERSION_SUFFIX, SKIPPED_STAGE_JOB_NAME


if __name__ == "__main__":
    existing_result_steps_ids_json = sys.stdin.read()
    existing_result_steps_ids = json.loads(existing_result_steps_ids_json)

    filtered_stages = remove_steps_from_stages(
        stages=step_stages, steps_to_remove=existing_result_steps_ids
    )

    stages = []
    last_non_empty_matrix_index = -1

    for i, stage in enumerate(filtered_stages):
        stage_jobs = []

        for step_id, step in stage.items():

            required_steps_ids = []
            for req_step in step.get_all_dependency_steps():
                required_steps_ids.append(req_step.id)

            runner_cls = steps_runners[step_id]

            stage_jobs.append(
                {
                    "step_runner_fqdn": runner_cls.FULLY_QUALIFIED_NAME,
                    "step_id": step.id,
                    "name": step.name,
                    "required_steps": sorted(required_steps_ids),
                    "cache_version_suffix": CACHE_VERSION_SUFFIX,
                }
            )

        if len(stage_jobs) > 0:
            last_non_empty_matrix_index = i

        stages.append(stage_jobs)

    buffer = io.StringIO()
    for i, stage_jobs in enumerate(stages):

        add_skip_job = False
        if len(stage_jobs) == 0:
            if i <= last_non_empty_matrix_index:
                add_skip_job = True

        if add_skip_job:
            stage_jobs.append({
                "name": SKIPPED_STAGE_JOB_NAME
            })

        matrix = {"include": stage_jobs}

        buffer.write(f"stage_matrix{i}={json.dumps(matrix)}\n")
        if len(stage_jobs) == 0:
            stage_skip = "true"
        else:
            stage_skip = "false"

        buffer.write(f"stage_skip{i}={stage_skip}\n")

    print(buffer.getvalue())


