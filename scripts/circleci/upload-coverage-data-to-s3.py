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
Script which uploads coverage data files to a S3 bucket.
"""

from __future__ import absolute_import
from __future__ import print_function

import os
import sys
import time

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


def upload_file(file_path):
    """
    :param file_path: Path to the coverage file to upload.
    """
    if not os.path.isfile(file_path):
        raise ValueError("File %s doesn't exist" % (file_path))

    print("Uploading coverage file to S3")

    cls = get_driver(Provider.S3)
    driver = cls(ACCESS_KEY_ID, ACCESS_KEY_SECRET, region="us-east-1")

    file_name = os.path.basename(file_path)

    # We also attach timestamp to file name to avoid conflicts
    now = str(int(time.time()))

    object_name = "%s/%s/%s.%s" % (CIRCLE_CI_BRANCH, CIRCLE_CI_COMMIT, file_name, now)

    container = driver.get_container(container_name=BUCKET_NAME)
    obj = container.upload_object(file_path=file_path, object_name=object_name)

    print(("Object uploaded to: %s/%s" % (BUCKET_NAME, object_name)))
    print(obj)


if __name__ == "__main__":
    file_path = os.path.abspath(sys.argv[1])
    upload_file(file_path)
