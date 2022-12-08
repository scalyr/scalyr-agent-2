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
This script determines initial information for the Ci/CD workflow, for example:
- type of the build (aka, dev or production)
- should build artifacts be published, and where.
- what version (dev or prod) to use for build artifacts.
"""

import json
import os
import subprocess
import sys
import pathlib as pl
import time
import re
from distutils.version import StrictVersion

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(pl.Path(__file__).parent.parent.parent.parent))


# We expect some info from the GitHub actions context to determine if the run is 'master-only' or not.
GITHUB_EVENT_NAME = os.environ.get("GITHUB_EVENT_NAME", "")
GITHUB_BASE_REF = os.environ.get("GITHUB_BASE_REF", "")
GITHUB_REF_TYPE = os.environ.get("GITHUB_REF_TYPE", "")
GITHUB_REF_NAME = os.environ.get("GITHUB_REF_NAME", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_SHA = os.environ.get("GITHUB_SHA", "")


def is_branch_has_pull_requests() -> bool:
    """
    Determine if current branch has at least one opened pull request.
    """
    data = subprocess.check_output([
        "curl",
        "-H",
        f"Authorization: Bearer {GITHUB_TOKEN}",
        f"https://api.github.com/repos/ArthurKamalov/scalyr-agent-2/pulls?head=ArthurKamalov:{GITHUB_REF_NAME}&base=master",
    ]).decode().strip()

    pull_requests = json.loads(data)
    return len(pull_requests) > 0


def determine_last_prod_version() -> str:
    """
    Get the latest agent production version by looking for git tags.
    """
    subprocess.check_call([
            "git", "fetch", "--unshallow", "--tags"
    ])
    output = subprocess.check_output([
        "git", "--no-pager", "tag", "-l"
    ]).decode()

    production_tags = []
    for tag in output.splitlines():
        m = re.search(r"^v(\d+\.\d+\.\d+)$", tag)
        if m is None:
            continue

        production_tags.append(m.group(1))

    last_version = sorted(production_tags, key=StrictVersion)[-1]
    return last_version


# Get last production version.
PROD_VERSION = determine_last_prod_version()

# Create version for dev build. It's <last_release_version>.<timestamp><commit_sha>
DEV_VERSION = f"{PROD_VERSION}.{int(time.time())}.{GITHUB_SHA}"

# We do a full, 'master' workflow run on:
# pull request against the 'master' branch.
if GITHUB_EVENT_NAME == "pull_request" and GITHUB_BASE_REF == "master":
    master_run = True
    to_publish = False
    is_production = False
    version = DEV_VERSION
# push to the 'master' branch
elif (
    GITHUB_EVENT_NAME == "push"
    and GITHUB_REF_TYPE == "branch"
    and GITHUB_REF_NAME == "master"
):
    master_run = True
    to_publish = True
    is_production = False
    version = DEV_VERSION

# push to a "production" tag.
elif GITHUB_EVENT_NAME == "push" and GITHUB_REF_TYPE == "tag":
    to_publish = True
    master_run = True
    m = re.match(r"^v(\d+\.\d+\.\d+)$", GITHUB_REF_NAME)
    if m:
        is_production = True
        version = m.group(1)
    else:
        is_production = False
        # Use version similar to the dev version, but instead of commit sha, we use tag name.
        version = f"{PROD_VERSION}.{int(time.time())}.{GITHUB_REF_NAME}"

else:
    master_run = is_branch_has_pull_requests()
    to_publish = False
    is_production = False
    version = DEV_VERSION


def main():
    run_type_name = "master" if master_run else "non-master"
    print(
        f"Doing {run_type_name} workflow run.",
        file=sys.stderr
    )
    print(
        f"event_name: {GITHUB_EVENT_NAME}\n"
        f"base_ref: {GITHUB_BASE_REF}\n"
        f"ref_type: {GITHUB_REF_TYPE}\n"
        f"ref_name: {GITHUB_REF_NAME}",
        file=sys.stderr,
    )

    result = {
        "is_master_run": master_run,
        "to_publish": to_publish,
        "is_production": is_production,
        "version": version
    }

    print(json.dumps(result))


if __name__ == "__main__":
    main()

