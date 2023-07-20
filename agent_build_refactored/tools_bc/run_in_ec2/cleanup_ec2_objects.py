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
This script is used by the GitHub Actions to clean up the ec2 instances and related objects.
"""
import json
import logging
import random
import sys
import pathlib as pl


# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
import time
from typing import Dict, List

import boto3

sys.path.append(str(pl.Path(__file__).parent.parent.parent.parent))

from agent_build_refactored.tools.run_in_ec2.boto3_tools import (
    AWSSettings,
    PREFIX_LIST_ENTRY_REMOVE_THRESHOLD,
    INSTANCE_NAME_STRING,
    DELETE_OLD_NODES_THRESHOLD_DT,
    get_prefix_list_version,
)


logger = logging.getLogger(__name__)


def cleanup_old_prefix_list_entries(
    boto3_session: boto3.Session,
    prefix_list_id: str,
    ec2_objects_name_prefix: str = None,
):
    """
    Cleanup ec2 test related prefix lists entries.
    :param boto3_session: boto3 session oject.
    :param prefix_list_id: Prefix list ID.
    :param ec2_objects_name_prefix: Workflow id to filter workflow related entries.
    :return:
    """

    boto3_client = boto3_session.client("ec2")
    resp = boto3_client.get_managed_prefix_list_entries(PrefixListId=prefix_list_id)
    entries = resp["Entries"]

    entries_to_remove = {}

    current_time = time.time()

    # Remove old prefix list entries.
    for entry in entries:
        timestamp = _parse_entry_timestamp(entry)
        if timestamp <= current_time - PREFIX_LIST_ENTRY_REMOVE_THRESHOLD:
            entries_to_remove[entry["Cidr"]] = entry

    # If workflow provided, then we also remove entries that have matching workflow_id field in
    # their Description field.
    if ec2_objects_name_prefix:
        for entry in entries:
            description = _parse_entry_description(entry)
            if (
                description["workflow_id"]
                and description["workflow_id"] == ec2_objects_name_prefix
            ):
                entries_to_remove[entry["Cidr"]] = entry

    if not entries_to_remove:
        return

    print(f"Removing entries: {entries_to_remove}")
    _remove_entries(
        client=boto3_client,
        entries=list(entries_to_remove.values()),
        prefix_list_id=prefix_list_id,
    )


def cleanup_old_ec2_instances(
    boto3_session: boto3.Session, ec2_objects_name_prefix: str = None
):
    """
    Cleanup old ec2 instances.
    """

    ec2 = boto3_session.resource("ec2")
    instances = list(ec2.instances.all())

    logger.info("Looking for and deleting old running automated ci/cd instances...")

    for instance in instances:
        name = _get_instance_name(instance)
        if name is None:
            continue

        if INSTANCE_NAME_STRING not in name:
            continue

        # Remove instances which are created by the current workflow immediately.
        if ec2_objects_name_prefix and ec2_objects_name_prefix in name:
            logger.info(
                f"Remove ec2 instance {name} with prefix {ec2_objects_name_prefix}"
            )
            instance.terminate()
            continue

        if not instance.launch_time:
            continue

        tzinfo = instance.launch_time.tzinfo
        if instance.launch_time >= DELETE_OLD_NODES_THRESHOLD_DT.replace(tzinfo=tzinfo):
            continue

        logger.info(f"Remove ec2 instance {name}")
        instance.terminate()


def cleanup_volumes(
    boto3_session: boto3.Session,
):
    ec2 = boto3_session.resource("ec2")
    volumes = list(ec2.volumes.all())

    def _get_volume_name(_volume):
        if not _volume.tags:
            return None

        for tag in _volume.tags:
            if tag["Key"] == "Name":
                return tag["Value"]

    for volume in volumes:
        name = _get_volume_name(volume)

        if not name:
            continue

        if INSTANCE_NAME_STRING not in name:
            continue

        if volume.state == "in-use":
            continue

        tzinfo = volume.create_time.tzinfo
        if volume.create_time >= DELETE_OLD_NODES_THRESHOLD_DT.replace(tzinfo=tzinfo):
            continue

        logger.info(f"Deleting volume with name: {name}")
        volume.delete()


def _get_instance_name(instance):

    if instance.tags is None:
        return None

    for tag in instance.tags:
        if tag["Key"] == "Name":
            return tag["Value"]


def _parse_entry_description(entry: Dict):
    """
    Parse json object from the description of the prefix list entry.
    Conventionally, we store useful information in it.
    """
    return json.loads(entry["Description"])


def _parse_entry_timestamp(entry: Dict) -> float:
    """
    Parse creation timestamp of the prefix list entry.
    """
    return float(_parse_entry_description(entry)["time"])


def _remove_entries(client, entries: List, prefix_list_id: str):
    """
    Remove specified entries from prefix list.
    :param client: boto3 client.
    :param entries: List of entries to remove.
    :param prefix_list_id: Prefix list ID.
    :return:
    """
    import botocore.exceptions

    attempts = 20
    # Since there may be multiple running ec2 tests, we have to add the retry
    # logic to overcome the prefix list concurrent access issues.
    while True:
        try:
            version = get_prefix_list_version(
                client=client, prefix_list_id=prefix_list_id
            )
            client.modify_managed_prefix_list(
                PrefixListId=prefix_list_id,
                CurrentVersion=version,
                RemoveEntries=[{"Cidr": e["Cidr"]} for e in entries],
            )
            break
        except botocore.exceptions.ClientError as e:
            keep_trying = False
            if "The prefix list has the incorrect version number" in str(e):
                keep_trying = True

            if "The request cannot be completed while the prefix" in str(e):
                keep_trying = True

            if attempts == 0 or not keep_trying:
                raise

            attempts -= 1
            print(f"Can not modify prefix list, retry. Reason: {str(e)}")
            time.sleep(random.randint(1, 5))


if __name__ == "__main__":

    aws_settings = AWSSettings.create_from_env()
    boto3_session = aws_settings.create_boto3_session()

    cleanup_old_prefix_list_entries(
        boto3_session=boto3_session,
        prefix_list_id=aws_settings.security_groups_prefix_list_id,
        ec2_objects_name_prefix=aws_settings.ec2_objects_name_prefix,
    )

    cleanup_old_ec2_instances(
        boto3_session=boto3_session,
        ec2_objects_name_prefix=aws_settings.ec2_objects_name_prefix,
    )

    cleanup_volumes(
        boto3_session=boto3_session,
    )
