#!/usr/bin/python3
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

# This script is meant to be executed by the instance of the 'agent_build_refactored.tools.runner.RunnerStep' class.
# Every RunnerStep provides common environment variables to its script:
#   SOURCE_ROOT: Path to the projects root.
#   STEP_OUTPUT_PATH: Path to the step's output directory.
#
# This script downloads package from the Packagecloud.
#
# It expects next environment variables:
#   PACKAGE_FILENAME: File name of the package.
import logging
import os
import subprocess
import requests
import pathlib as pl
import shutil
from requests.auth import HTTPBasicAuth

from agent_build_refactored.tools.steps_libs.step_tools import skip_caching_and_exit
from agent_build_refactored.tools.steps_libs.build_logging import init_logging

logger = logging.getLogger(__name__)

def main():
    init_logging()

    package_file_name = os.environ["PACKAGE_FILENAME"]
    user_name = os.environ["USER_NAME"]
    repo_name = os.environ["REPO_NAME"]
    token = "50552e5ef4df6c425e24d1213564910f1990c5fd25f2c4f4"
    auth = HTTPBasicAuth(token, "")

    with requests.Session() as s:
        headers = {'Authorization': token}

        resp = s.get(
            url=f"https://packagecloud.io/api/v1/repos/{user_name}/{repo_name}/search.json",
            params={
                "q": package_file_name
            },
            auth=auth
        )

    resp.raise_for_status()
    packages = resp.json()

    if len(packages) == 0:
        logger.info(f"Package {package_file_name} is not in the Packagecloud repository.")
        skip_caching_and_exit()

    download_url = packages[0]["download_url"]

    package_path = pl.Path(os.environ["STEP_OUTPUT_PATH"]) / package_file_name

    with requests.Session() as s:
        resp = s.get(
            url=download_url,
            auth=auth,
            stream=True
        )
        resp.raise_for_status()
        with package_path.open("wb") as f:
            shutil.copyfileobj(resp.raw, f)


if __name__ == '__main__':
    main()