#!/usr/bin/env python
# Copyright 2014-2020 Scalyr Inc.
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
#
# Script which triggers circleci pipeline for particular git branch and uploads its job artifacts after.
#
# It depends on the following environment variables being set:
# - CIRCLE_API_TOKEN - CircleCI API access token.
#
# Usage:
#
# The script expects '--workflow', '--job', and '--artifact-path' for each desired artifact file in order to find it.
#
# python upload_circleci_artifacts.py --branch mastert # --output-path <path>\
# --workflow=package-tests --job=build-windows-package --artifact-path=".*\.msi" \
# --workflow=package-tests --job=build-linux-packages --artifact-path=".*\.rpm" \
# --workflow=package-tests --job=build-linux-packages --artifact-path=".*\.deb" \


from __future__ import print_function
from __future__ import unicode_literals
from __future__ import absolute_import
from scalyr_agent import compat
from io import open
from six.moves import zip

if False:
    from typing import Dict
    from typing import List
    from typing import Any
    from typing import Generator
    from typing import Tuple

import argparse
import os
import itertools
import operator
import datetime
import time
import re

import requests

CIRCLE_API_URL = "https://circleci.com/api/v2"

CIRCLE_API_PROJECT_URL = CIRCLE_API_URL + "/project/gh/scalyr/scalyr-agent-2"

# 15 min
CIRCLE_WAIT_TIMEOUT = 60 * 15

try:
    CIRCLE_API_TOKEN = compat.os_environ_unicode["CIRCLE_API_TOKEN"]
except KeyError:
    print("Environment variable 'CIRCLE_API_TOKEN' is not specified.")
    raise


def _do_request(method, url, **kwargs):
    # type: (str, str, **Any) -> requests.Response

    headers = kwargs.get("headers", dict())

    headers["Circle-Token"] = CIRCLE_API_TOKEN
    headers["Accept"] = "application/json"

    kwargs["headers"] = headers

    with requests.Session() as session:
        resp = session.request(method=method, url=url, **kwargs)
    resp.raise_for_status()
    return resp


def get_request(url, **kwargs):
    # type: (str, Dict) -> Dict
    resp = _do_request("GET", url, **kwargs)
    return resp.json()


def post_request(url, **kwargs):
    # type: (str, Dict) -> requests.Response
    return _do_request("POST", url, **kwargs)


def get_paginated_collection(url):
    # type: (str) -> Generator
    """
    Generator witch fetches elements from circleci collection with pagination.
    :param url: Url to the collection.
    :return: Yields next element in the collection.
    """
    next_page_token = None
    while True:

        resp = get_request(url=url, params={"page-token": next_page_token})

        for item in resp["items"]:
            yield item

        next_page_token = resp["next_page_token"]
        if next_page_token is None:
            raise StopIteration()


def get_paginated_list(url):
    # type: (str) -> List
    """
    Fetch the circleci paginated collection as list.
    """

    return list(get_paginated_collection(url))


def get_paginated_dict(url, key):
    # type: (str, str) -> Dict
    """
    Fetch the circleci paginated collection as dict.
    :param key: Name of the field of the element which will be used as key for the dictionary.
    """
    return {item[key]: item for item in get_paginated_collection(url)}


def download_artifact_file(artifact_info, output_path):
    # type: (Dict, str) -> None
    """
    Download circleci job artifact.
    :param artifact_info: Contains information about artifact.
    :param output_path: Base output path.
    :return:
    """
    artifact_output_path = os.path.join(
        output_path, os.path.basename(artifact_info["path"]),
    )

    with requests.Session() as session:
        resp = session.get(url=artifact_info["url"], allow_redirects=True, stream=True)

    with open(artifact_output_path, "wb") as file:
        for chunk in resp.iter_content(chunk_size=8192):
            file.write(chunk)


def trigger_pipeline(branch_name,):
    # type: (str) -> Dict
    """
    Trigger new CircleCI pipeline for the specified branch.
    :return: General information about started pipeline from CircleCI.
    """
    resp = post_request(
        url=CIRCLE_API_PROJECT_URL + "/pipeline", json={"branch": branch_name}
    )

    resp.raise_for_status()
    pipeline_info = resp.json()

    return pipeline_info


def wait_for_workflow(workflow_id, timeout_time):
    # type: (str, datetime.datetime) -> Dict
    """
    Wait for specified workflow is finished. If workflow finished without success, raise an error.
    :param timeout_time:
    :return: General information about workflow from CircleCI.
    """
    while True:
        workflow_info = get_request(
            url=CIRCLE_API_URL + "/workflow/" + str(workflow_id),
        )
        workflow_status = workflow_info["status"]
        workflow_name = workflow_info["name"]

        print("Status: ", workflow_status)

        if workflow_status == "success":
            print("Workflow '{0}' finished successfully.".format(workflow_name))
            return workflow_info

        if workflow_status != "running":
            raise RuntimeError(
                "Workflow '{0}' failed with status '{1}'.".format(
                    workflow_name, workflow_status
                )
            )

        if datetime.datetime.now() >= timeout_time:
            raise TimeoutError(
                "Can not wait more for workflow '{0}'.".format(workflow_name)
            )

        print("Wait for workflow '{0}'.".format(workflow_name))
        time.sleep(10)


def discard_outdated_workflows(workflow_infos):
    # type: (List) -> Dict
    """
    Find workflows with the same names and keep only latest one.
    The pipeline can contain multiple workflows with the same name
    (this can happen, for example, if workflow was restarted manually).
    so we need to get the latest workflow.
    """
    result = dict()

    for name, group in itertools.groupby(
        workflow_infos, key=operator.itemgetter("name")
    ):
        # get workflow with the 'biggest' time.
        latest_workflow = max(group, key=operator.itemgetter("created_at"))
        result[name] = latest_workflow

    return result


def wait_for_pipeline(pipeline_number,):
    # type: (int) -> Dict
    """
    Wait for all workflows are finishedin the pipeline specified by 'pipeline number'.
    :return: General information about all workflows from CircleCI.
    """
    # get information about the pipeline.
    pipeline_info = get_request(
        url=CIRCLE_API_PROJECT_URL + "/pipeline/" + str(pipeline_number)
    )

    pipeline_id = pipeline_info["id"]

    # get pipeline workflows
    pipeline_workflows = get_paginated_list(
        url=CIRCLE_API_URL + "/pipeline/" + str(pipeline_id) + "/workflow",
    )
    raise Exception(pipeline_workflows)
    # remove duplicated workflows and keep latest ones.
    latest_workflows = discard_outdated_workflows(pipeline_workflows)

    finished_workflows = dict()
    # wait for each workflow is successfully finished.
    for name, workflow in latest_workflows.items():
        # If any of the workflows is not successful 'wait_for_workflow' will raise error.

        timeout_time = datetime.datetime.now() + datetime.timedelta(
            seconds=CIRCLE_WAIT_TIMEOUT
        )
        finished_workflows[name] = wait_for_workflow(
            workflow_id=workflow["id"], timeout_time=timeout_time
        )

    return finished_workflows


def download_artifacts(artifacts_to_fetch, workflow_infos, output_path):
    # type: (Dict, Dict, str) -> None

    cached_job_infos = dict()  # type: Dict[str, Any]
    cached_artifact_infos = dict()  # type: Dict[Tuple, Any]
    for workflow_name, job_name, artifact_pattern in artifacts_to_fetch:
        workflow_info = workflow_infos.get(workflow_name)
        if workflow_info is None:
            raise RuntimeError(
                "Can not find workflow with name '{0}'".format(workflow_name)
            )

        # if we already get job infos for this workflow, we just can reuse it from cache.
        job_infos = cached_job_infos.get(workflow_name)
        if job_infos is None:
            # job infos for this workflow are not used yet. Fetch them from CircleCI and cache for future use.
            job_infos = get_paginated_dict(
                url=CIRCLE_API_URL + "/workflow/" + workflow_info["id"] + "/job",
                key="name",
            )
            cached_job_infos[workflow_name] = job_infos

        job_info = job_infos.get(job_name)
        if job_info is None:
            raise RuntimeError("Can not find job with name '{0}'".format(job_name))

        artifact_infos = cached_artifact_infos.get((workflow_name, job_name))
        if artifact_infos is None:
            artifact_infos = get_paginated_dict(
                url=CIRCLE_API_PROJECT_URL
                + "/"
                + str(job_info["job_number"])
                + "/artifacts",
                key="path",
            )
            cached_artifact_infos[(workflow_name, job_name)] = artifact_infos

        for artifact_info in artifact_infos.values():
            artifact_path = artifact_info["path"]
            if re.match(artifact_pattern, artifact_path):
                download_artifact_file(artifact_info, output_path)
                print("Artifact '{0}'is downloaded.".format(artifact_path))
                break
        else:
            raise RuntimeError(
                "Can not find artifact with path '{0}'".format(artifact_pattern)
            )


def main(
    branch_name, artifacts_to_fetch, output_path,
):
    pipeline_trigger_info = trigger_pipeline(branch_name=branch_name)

    pipeline_number = pipeline_trigger_info["number"]

    # wait for whole pipeline is finished and get all workflows.
    workflow_infos = wait_for_pipeline(pipeline_number=pipeline_number)

    time.sleep(20)
    # download artifacts.
    download_artifacts(artifacts_to_fetch, workflow_infos, output_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch", required=True, type=str, help="Branch name."),
    parser.add_argument(
        "--workflow",
        required=True,
        type=str,
        help="Name of the CircleCI workflow.",
        action="append",
    ),
    parser.add_argument(
        "--job",
        required=True,
        type=str,
        help="Name of the CircleCI job.",
        action="append",
    )

    parser.add_argument(
        "--artifact-path",
        required=True,
        type=str,
        help="The Regular expression for the path of the job artifact.",
        action="append",
    )

    parser.add_argument(
        "--output-path",
        required=True,
        type=str,
        help="Output path for all uploaded artifacts.",
    )

    args = parser.parse_args()

    if [len(args.workflow), len(args.job), len(args.artifact_path)].count(
        len(args.workflow)
    ) != 3:
        raise ValueError(
            "Options '--workflow', '--job' and --'artifact-path' must be specified for each artifact."
        )

    main(
        branch_name=args.branch,
        artifacts_to_fetch=list(zip(args.workflow, args.job, args.artifact_path)),
        output_path=args.output_path,
    )
