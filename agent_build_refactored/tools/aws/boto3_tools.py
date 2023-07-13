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

import dataclasses
import os
import logging
import datetime
import pathlib as pl
from typing import Dict, Optional

import boto3

logger = logging.getLogger(__name__)


# All the instances created by this script will use this string in the name.

MAX_PREFIX_LIST_UPDATE_ATTEMPTS = 20

# Age of the prefix entry ofter which it can be cleaned up.
PREFIX_LIST_ENTRY_REMOVE_THRESHOLD = 60 * 7  # Minutes

# We delete any old automated test nodes which are older than 4 hours
DELETE_OLD_NODES_TIMEDELTA = datetime.timedelta(hours=4)
DELETE_OLD_NODES_THRESHOLD_DT = datetime.datetime.utcnow() - DELETE_OLD_NODES_TIMEDELTA


@dataclasses.dataclass
class AWSSettings:
    """
    Dataclass that stores all settings that are required to manipulate AWS objects.
    """

    access_key: str
    secret_key: str
    private_key_path: pl.Path
    private_key_name: str
    region: str
    security_group: str
    security_groups_prefix_list_id: str
    ec2_objects_name_prefix: str
    current_session_tag: str

    @staticmethod
    def create_from_env():
        vars_name_prefix = os.environ.get("AWS_ENV_VARS_PREFIX", "")

        def _validate_setting(name):
            final_name = f"{vars_name_prefix}{name}"
            value = os.environ.get(final_name)
            if value is None:
                raise Exception(f"Env. variable '{final_name}' is not found.")

            return value

        return AWSSettings(
            access_key=_validate_setting("AWS_ACCESS_KEY"),
            secret_key=_validate_setting("AWS_SECRET_KEY"),
            private_key_path=pl.Path(_validate_setting("AWS_PRIVATE_KEY_PATH")),
            private_key_name=_validate_setting("AWS_PRIVATE_KEY_NAME"),
            region=_validate_setting("AWS_REGION"),
            security_group=_validate_setting("AWS_SECURITY_GROUP"),
            security_groups_prefix_list_id=_validate_setting(
                "AWS_SECURITY_GROUPS_PREFIX_LIST_ID"
            ),
            ec2_objects_name_prefix=_validate_setting("AWS_OBJECTS_NAME_PREFIX"),
            current_session_tag=_validate_setting("CURRENT_SESSION_TAG")
        )

    def create_boto3_session(self):
        return boto3.session.Session(
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
        )


def get_prefix_list_version(client, prefix_list_id: str):
    """
    Get version of the prefix list.
    :param client: ec2 boto3 client.
    :param prefix_list_id: ID of the prefix list.
    """
    resp = client.describe_managed_prefix_lists(
        Filters=[
            {"Name": "prefix-list-id", "Values": [prefix_list_id]},
        ],
    )
    found = resp["PrefixLists"]
    assert (
        len(found) == 1
    ), f"Number of found prefix lists has to be 1, got {len(found)}"
    prefix_list = found[0]
    return int(prefix_list["Version"])
