import argparse
import re
import sys
import time
import pathlib as pl
from typing import Dict

import boto3
import botocore.exceptions

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(pl.Path(__file__).parent.parent.parent.parent))

from tests.end_to_end_tests.run_in_remote_machine.ec2_prefix_lists import get_prefix_list_version

# Age of the prefix entry ofter which it can be cleaned up.
PREFIX_LIST_ENTRY_REMOVE_THRESHOLD = 60 * 7  # Minutes


def _parse_entry_timestamp(entry: Dict):
    return int(
        re.search(r"Creation timestamp: (\d+)", entry["Description"]).group(1)
    )


def main(
    access_key: str,
    secret_key: str,
    prefix_list_id: str,
    region: str,
):

    client = boto3.client(
        "ec2",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region
    )

    resp = client.get_managed_prefix_list_entries(
        PrefixListId=prefix_list_id
    )

    entries = resp["Entries"]

    entries_to_remove = []

    current_time = time.time()
    for entry in entries:
        timestamp = _parse_entry_timestamp(entry)
        if timestamp <= current_time - PREFIX_LIST_ENTRY_REMOVE_THRESHOLD:
            entries_to_remove.append(entry)

    if not entries_to_remove:
        return

    attempts = 10
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
            time.sleep(1)


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
    args = parser.parse_args()

    main(
        access_key=args.access_key,
        secret_key=args.secret_key,
        prefix_list_id=args.prefix_list_id,
        region=args.region
    )

