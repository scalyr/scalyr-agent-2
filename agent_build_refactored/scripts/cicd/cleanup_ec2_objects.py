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
import concurrent.futures
import datetime
import json
import logging
import random
import sys
from datetime import datetime, timedelta
import pathlib as pl
import time
from typing import Dict, List

import boto3

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(pl.Path(__file__).parent.parent.parent.parent))

from agent_build_refactored.tools.common import init_logging
from agent_build_refactored.tools.aws.ec2 import INSTANCE_NAME_STRING, terminate_ec2_instances_and_security_groups
from agent_build_refactored.tools.aws.common import COMMON_TAG_NAME, AWSSettings
from agent_build_refactored.tools.docker.buildx.remote_builder.remote_builder_ami_image import (
    REMOTE_DOCKER_ENGINE_IMAGES
)


init_logging()
logger = logging.getLogger(__name__)


# Age of the prefix entry ofter which it can be cleaned up.
PREFIX_LIST_ENTRY_REMOVE_THRESHOLD = 60 * 7  # Minutes

# We delete any old automated test nodes which are older than 4 hours
DELETE_OLD_NODES_TIMEDELTA = timedelta(hours=4)
DELETE_OLD_NODES_THRESHOLD_DT = datetime.utcnow() - DELETE_OLD_NODES_TIMEDELTA

DELETE_OLD_AMI_IMAGES_TIMEDELTA = timedelta(days=2)
DELETE_OLD_AMI_IMAGES_THRESHOLD_DT = datetime.utcnow() - DELETE_OLD_AMI_IMAGES_TIMEDELTA

#
# def cleanup_old_prefix_list_entries(
#     boto3_session: boto3.Session,
#     prefix_list_id: str,
#     ec2_objects_name_prefix: str = None,
# ):
#     """
#     Cleanup ec2 test related prefix lists entries.
#     :param boto3_session: boto3 session oject.
#     :param prefix_list_id: Prefix list ID.
#     :param ec2_objects_name_prefix: Workflow id to filter workflow related entries.
#     :return:
#     """
#
#     boto3_client = boto3_session.client("ec2")
#     resp = boto3_client.get_managed_prefix_list_entries(PrefixListId=prefix_list_id)
#     entries = resp["Entries"]
#
#     entries_to_remove = {}
#
#     current_time = time.time()
#
#     # Remove old prefix list entries.
#     for entry in entries:
#         timestamp = _parse_entry_timestamp(entry)
#         if timestamp <= current_time - PREFIX_LIST_ENTRY_REMOVE_THRESHOLD:
#             entries_to_remove[entry["Cidr"]] = entry
#
#     # If workflow provided, then we also remove entries that have matching workflow_id field in
#     # their Description field.
#     if ec2_objects_name_prefix:
#         for entry in entries:
#             description = _parse_entry_description(entry)
#             if (
#                 description["workflow_id"]
#                 and description["workflow_id"] == ec2_objects_name_prefix
#             ):
#                 entries_to_remove[entry["Cidr"]] = entry
#
#     if not entries_to_remove:
#         return
#
#     logger.info(f"Removing entries: {entries_to_remove}")
#     _remove_entries(
#         client=boto3_client,
#         entries=list(entries_to_remove.values()),
#         prefix_list_id=prefix_list_id,
#     )


def cleanup_old_ec2_instances_and_related_objects(
    ec2_client,
    ec2_resource,
):
    """
    Cleanup old ec2 instances.
    """


    from agent_build_refactored.tools.aws.ec2 import EC2InstanceWrapper

    aws_settings = AWSSettings.create_from_env()
    from agent_build_refactored.tools.docker.buildx.remote_builder.remote_builder_ami_image import BASE_IMAGE_AMD64

    # instance = EC2InstanceWrapper.create_and_deploy_ec2_instance(
    #     boto3_session=boto3_session,
    #     ec2_image=BASE_IMAGE_AMD64,
    #     name_prefix="arthur_test",
    #     aws_settings=aws_settings,
    # )

    instances = list(ec2_resource.instances.filter(
        Filters=[
            {
                "Name": "tag-key",
                "Values": [COMMON_TAG_NAME]
            },
        ],
    ))

    logger.info("Looking for and deleting old running automated ci/cd instances...")

    instances_to_remove = []

    for instance in instances:
        if instance.state["Name"] == "terminated":
            continue

        if not instance.launch_time:
            continue

        tzinfo = instance.launch_time.tzinfo
        if instance.launch_time >= DELETE_OLD_NODES_THRESHOLD_DT.replace(tzinfo=tzinfo):
            continue

        logger.info(f"Remove ec2 instance {instance.id}")
        instances_to_remove.append(instance)

    terminate_ec2_instances_and_security_groups(
        instances=instances_to_remove,
        ec2_client=ec2_client,
    )


def cleanup_old_volumes(
    ec2_resource,

):
    volumes = list(ec2_resource.volumes.filter(
        Filters=[
            {
                "Name": "tag-key",
                "Values": [COMMON_TAG_NAME]
            },
        ],
    ))

    for volume in volumes:
        if volume.state == "in-use":
            continue

        tzinfo = volume.create_time.tzinfo
        if volume.create_time >= DELETE_OLD_NODES_THRESHOLD_DT.replace(tzinfo=tzinfo):
            continue

        logger.info(f"Deleting volume with name: {volume.name}")
        volume.remove()


def cleanup_old_ami_images(
    ec2_resource,
):

    images_checksums_to_keep = set()

    for image in REMOTE_DOCKER_ENGINE_IMAGES.values():
        images_checksums_to_keep.add(image.checksum)

    all_images = list(ec2_resource.images.filter(
        Filters=[
            {
                "Name": "tag-key",
                "Values": [COMMON_TAG_NAME],
            },
        ]
    ))

    for image in all_images:
        for tag in image.tags:
            if tag["Key"] != "checksum":
                continue
            if tag["Value"] in images_checksums_to_keep:
                continue

            creation_time = datetime.strptime(
                image.creation_date, "%Y-%m-%dT%H:%M:%S.%fZ"
            )

            if creation_time > DELETE_OLD_AMI_IMAGES_THRESHOLD_DT:
                continue

            image.deregister()
            logger.info(f"AMI image {image.id} has been de-registered.")


def cleanup_old_security_groups(
    ec2_resource,

):
    security_groups = list(ec2_resource.security_groups.filter(
        Filters=[
            {
                "Name": "tag-key",
                "Values": [COMMON_TAG_NAME]
            },
        ],
    ))

    security_groups_to_remove = []
    for security_group in security_groups:
        tags = {t["Key"]: t["Value"] for t in security_group.tags}

        creation_time_str = tags.get("CreationTime")

        if not creation_time_str:
            security_groups_to_remove.append(security_group)
            continue

        try:
            creation_time = datetime.fromisoformat(creation_time_str)
        except ValueError:
            security_groups_to_remove.append(security_group)
            continue

        if creation_time > DELETE_OLD_NODES_THRESHOLD_DT:
            continue

        security_groups_to_remove.append(security_group)

    for security_group in security_groups_to_remove:
        logger.info(f"Delete security group: '{security_group.id}'")
        security_group.delete()


def main():
    aws_settings = AWSSettings.create_from_env()
    boto3_session = aws_settings.create_boto3_session()

    ec2_resource = boto3_session.resource("ec2")
    ec2_client = boto3_session.client("ec2")

    cleanup_old_ec2_instances_and_related_objects(
        ec2_client=ec2_client,
        ec2_resource=ec2_resource,
    )

    cleanup_old_security_groups(
        ec2_resource=ec2_resource,
    )

    cleanup_old_volumes(
        ec2_resource=ec2_resource,
    )

    cleanup_old_ami_images(
        ec2_resource=ec2_resource,
    )


if __name__ == "__main__":
    main()

