import argparse
import json
import random
import re
import sys
import time
import pathlib as pl
from typing import Dict, List

import boto3
import botocore.exceptions

"""
This script is used by the Github Actions to cleanup the ec2 prefix list after ec2 ent to end tests.
"""

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(pl.Path(__file__).parent.parent.parent.parent))

from tests.end_to_end_tests.run_in_remote_machine.ec2_prefix_lists import get_prefix_list_version

# Age of the prefix entry ofter which it can be cleaned up.
PREFIX_LIST_ENTRY_REMOVE_THRESHOLD = 60 * 7  # Minutes


def _parse_entry_description(entry: Dict):
    return json.loads(entry["Description"])


def _parse_entry_timestamp(entry: Dict):
    return _parse_entry_description(entry)["time"]


def _remove_entries(
        client,
        entries: List,
        prefix_list_id: str
):
    """
    Remove specified entries from prefix list.
    :param client: boto3 client.
    :param entries: List of entries to remove.
    :param prefix_list_id: Prefix list ID.
    :return:
    """
    attempts = 10
    # Since there may be multiple running ec2 tests, we have to add the retry
    # logic to overcome the prefix list concurrent access issues.
    while True:
        try:
            version = get_prefix_list_version(
                client=client,
                prefix_list_id=prefix_list_id
            )
            client.modify_managed_prefix_list(
                PrefixListId=prefix_list_id,
                CurrentVersion=version,
                RemoveEntries=[{"Cidr": e["Cidr"]} for e in entries]
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


def main(
    client,
    prefix_list_id: str,
    workflow_id: str = None
):
    resp = boto_client.get_managed_prefix_list_entries(
        PrefixListId=args.prefix_list_id
    )
    entries = resp["Entries"]

    entries_to_remove = {}

    current_time = time.time()

    # Remove old prfix list entries.
    for entry in entries:
        timestamp = _parse_entry_timestamp(entry)
        if timestamp <= current_time - PREFIX_LIST_ENTRY_REMOVE_THRESHOLD:
            entries_to_remove[entry["Cidr"]] = entry

    # If workflow provided, then we also remove entries that have matching workflow_id field in
    # their Description field.
    if workflow_id:
        for entry in entries:
            description = _parse_entry_description(entry)
            if description["workflow_id"] and description["workflow_id"] == workflow_id:
                entries_to_remove[entry["Cidr"]] = entry

    if not entries_to_remove:
        return

    print(f"Removing entries: {entries_to_remove}")
    _remove_entries(
        client=client,
        entries=list(entries_to_remove.values()),
        prefix_list_id=prefix_list_id
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--access-key",
        required=True
    )
    parser.add_argument(
        "--secret-key",
        required=True
    )
    parser.add_argument(
        "--prefix-list-id",
        required=True
    )
    parser.add_argument(
        "--region",
        required=True
    )
    parser.add_argument(
        "--workflow-id",
        required=False
    )
    args = parser.parse_args()

    boto_client = boto3.client(
        "ec2",
        aws_access_key_id=args.access_key,
        aws_secret_access_key=args.secret_key,
        region_name=args.region
    )

    main(
        client=boto_client,
        prefix_list_id=args.prefix_list_id,
        workflow_id=args.workflow_id
    )

