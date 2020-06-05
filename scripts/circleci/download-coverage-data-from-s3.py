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

"""
Script which downloads all the previously uploaded coverage data files for a particular
branch and commit id.
"""

from __future__ import absolute_import
from __future__ import print_function

import os
import sys

from libcloud.storage.types import Provider
from libcloud.storage.providers import get_driver
from scalyr_agent import compat

BUCKET_NAME = compat.os_getenv_unicode(
    "COVERAGE_BUCKET_NAME", "scalyr-agent-2-coverage-data"
)

ACCESS_KEY_ID = compat.os_getenv_unicode("COVERAGE_AWS_ACCESS_KEY_ID", None)
ACCESS_KEY_SECRET = compat.os_getenv_unicode("COVERAGE_AWS_ACCESS_KEY_SECRET", None)
AWS_REGION = compat.os_getenv_unicode("COVERAGE_AWS_REGION", "us-east-1")

CIRCLE_CI_BRANCH = compat.os_getenv_unicode("CIRCLE_BRANCH", None)
CIRCLE_CI_COMMIT = compat.os_getenv_unicode("CIRCLE_SHA1", None)

if not ACCESS_KEY_ID:
    raise ValueError("COVERAGE_AWS_ACCESS_KEY_ID env variable not set")

if not ACCESS_KEY_SECRET:
    raise ValueError("COVERAGE_AWS_ACCESS_KEY_SECRET env variable not set")

if not CIRCLE_CI_BRANCH:
    raise ValueError("CIRCLE_BRANCH env variable not set")

if not CIRCLE_CI_COMMIT:
    raise ValueError("CIRCLE_SHA1 env variable not set")


def download_coverage_files(destination_path):
    if not os.path.isdir(destination_path):
        raise ValueError(
            "%s path doesn't exist or it's not a directory" % (destination_path)
        )

    cls = get_driver(Provider.S3)
    driver = cls(ACCESS_KEY_ID, ACCESS_KEY_SECRET, region="us-east-1")
    container = driver.get_container(container_name=BUCKET_NAME)

    prefix = "%s/%s" % (CIRCLE_CI_BRANCH, CIRCLE_CI_COMMIT)
    for index, obj in enumerate(container.list_objects(prefix=prefix)):
        print(("Downloading object %s" % (obj.name)))

        obj_time = obj.name.split("/")[-1].rsplit(".")[-1]
        obj_destination_path = os.path.join(
            destination_path, ".coverage.%s.%s" % (index, obj_time)
        )
        obj.download(destination_path=obj_destination_path, overwrite_existing=True)

        print(("Obj %s downloaded to %s" % (obj.name, destination_path)))


if __name__ == "__main__":
    destination_path = os.path.abspath(sys.argv[1])
    download_coverage_files(destination_path)
