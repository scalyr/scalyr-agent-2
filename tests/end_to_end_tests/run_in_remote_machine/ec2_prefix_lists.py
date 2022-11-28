import json
import random
import re
import time
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


MAX_PREFIX_LIST_UPDATE_ATTEMPTS = 10
PREFIX_LIST_ENTRY_REMOVE_THRESHOLD = 60 * 1  # 1 hour.


def _search_for_old_entries(entries: List):
    # Filter out old entries

    result = []
    for entry in entries:
        timestamp = _parse_entry_timestamp(entry)
        if timestamp <= PREFIX_LIST_ENTRY_REMOVE_THRESHOLD:
            result.append(entry)

    return result


def get_prefix_list_version(client, prefix_list_id: str):
    resp = client.describe_managed_prefix_lists(
        Filters=[
            {
                "Name": "prefix-list-id",
                "Values": [prefix_list_id]
            },
        ],
    )
    found = resp["PrefixLists"]
    assert len(found) == 1, f"Number of found prefix lists has to be 1, got {len(found)}"
    prefix_list = found[0]
    return int(prefix_list["Version"])


def _parse_entry_timestamp(entry: Dict):
    return int(
        re.search(r"Creation timestamp: (\d+)", entry["Description"]).group(1)
    )


def add_new_entry(
        client,
        cidr: str, prefix_list_id: str,
        workflow_id: str = None

):
    version = get_prefix_list_version(
        client=client,
        prefix_list_id=prefix_list_id
    )
    client.modify_managed_prefix_list(
        PrefixListId=prefix_list_id,
        CurrentVersion=version,
        AddEntries=[
            {
                'Cidr': cidr,
                'Description': json.dumps({
                    "time": int(time.time()),
                    "workflow_id": workflow_id
                })
            },
        ]
    )


def remove_prefix_list_entries(client, entries: List, prefix_list_id: str):
    import botocore.exceptions

    attempts = 10
    while True:
        try:
            version = _get_prefix_list_version(
                client=client,
                prefix_list_id=prefix_list_id
            )
            client.modify_managed_prefix_list(
                PrefixListId=prefix_list_id,
                CurrentVersion=version,
                RemoveEntries=[{"Cidr":e["Cidr"]} for e in entries]
            )
            break
        except botocore.exceptions.ClientError as e:
            if "The prefix list has the incorrect version number" in str(e):
                continue

            if "The request cannot be completed while the prefix" in str(e):
                continue

            if attempts == 0:
                raise

            attempts -= 1
            time.sleep(1)


def add_current_ip_to_prefix_list(
    client,
    prefix_list_id: str,
    workflow_id: str = None
):
    import botocore.exceptions
    import requests

    # Get current public IP.
    with requests.Session() as s:
        resp = s.get("https://api.ipify.org")
        resp.raise_for_status()

    public_ip = resp.content.decode()

    new_cidr = f'{public_ip}/32'

    attempts = 0
    while True:
        try:
            add_new_entry(
                client=client,
                cidr=new_cidr,
                prefix_list_id=prefix_list_id,
                workflow_id=workflow_id
            )
            break
        except botocore.exceptions.ClientError as e:
            if attempts >= MAX_PREFIX_LIST_UPDATE_ATTEMPTS:
                logger.exception(f"Can not add new entry to the prefix list {prefix_list_id}")
                raise e

            attempts += 1
            print(f"Can not modify prefix list, retry. Reason: {str(e)}")
            time.sleep(random.randint(1, 5))

    return new_cidr


def remove_prefix_list_entry(
        client,
        prefix_list_id: str,
        cidr: str
):
    remove_prefix_list_entries(
        client=client,
        prefix_list_id=prefix_list_id,
        entries=[{"Cidr": cidr}]
    )

