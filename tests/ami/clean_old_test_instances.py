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
Utility script which cleans up any old / stray running package test instances.

We could be left with running instances if ami-tests Circle CI job is canceled before it has the
chance to clean up (e.g. either manually or by a new build triggered by a push to a branch).
"""

from __future__ import absolute_import
from __future__ import print_function

import datetime

from libcloud.utils.iso8601 import parse_date

from packages_sanity_tests import INSTANCE_NAME_STRING
from packages_sanity_tests import get_libcloud_driver
from packages_sanity_tests import destroy_node_and_cleanup

# We delete any old automated test nodes which are older than 4 hours
DELETE_OLD_NODES_TIMEDELTA = datetime.timedelta(hours=4)
DELETE_OLD_NODES_THRESHOLD_DT = datetime.datetime.utcnow() - DELETE_OLD_NODES_TIMEDELTA


def main():
    driver = get_libcloud_driver()
    nodes = driver.list_nodes()

    print("Looking for and deleting old running automated test nodes...")

    nodes_to_delete = []

    for node in nodes:
        if INSTANCE_NAME_STRING not in node.name:
            continue

        launch_time = node.extra.get("launch_time", None)

        if not launch_time:
            continue

        launch_time_dt = parse_date(launch_time).replace(tzinfo=None)
        if launch_time_dt >= DELETE_OLD_NODES_THRESHOLD_DT:
            continue

        print(('Found node "%s" for deletion.' % (node.name)))

        nodes_to_delete.append(node)

    nodes = []

    for node in nodes_to_delete:
        destroy_node_and_cleanup(driver=driver, node=node)

    print("Destroyed %s old nodes" % (len(nodes_to_delete)))


if __name__ == "__main__":
    main()
