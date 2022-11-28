import re
import time
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


MAX_PREFIX_LIST_UPDATE_ATTEMPTS = 3
PREFIX_LIST_ENTRY_REMOVE_THRESHOLD = 60 * 1  # 1 hour.


def _search_for_old_entries(entries: List):
    # Filter out old entries

    result = []
    for entry in entries:
        timestamp = _parse_entry_timestamp(entry)
        if timestamp <= PREFIX_LIST_ENTRY_REMOVE_THRESHOLD:
            result.append(entry)

    return result


def _get_prefix_list_version(client, prefix_list_id: str):
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


def add_new_entry(client, cidr: str, prefix_list_id:str):
    version = _get_prefix_list_version(
        client=client,
        prefix_list_id=prefix_list_id
    )
    client.modify_managed_prefix_list(
        PrefixListId=prefix_list_id,
        CurrentVersion=version,
        AddEntries=[
            {
                'Cidr': cidr,
                'Description': f"Creation timestamp: {int(time.time())}"
            },
        ]
    )


def remove_prefix_list_entries(client, entries: List, prefix_list_id: str):
    version = _get_prefix_list_version(
        client=client,
        prefix_list_id=prefix_list_id
    )
    client.modify_managed_prefix_list(
        PrefixListId=prefix_list_id,
        CurrentVersion=version,
        RemoveEntries=[{"Cidr":e["Cidr"]} for e in entries]
    )


def prepare_aws_prefix_list(
    client,
    prefix_list_id: str,
):
    import botocore.exceptions
    import requests

    # Get current public IP.
    with requests.Session() as s:
        resp = s.get("https://api.ipify.org")
        resp.raise_for_status()

    public_ip = resp.content.decode()

    resp = client.get_managed_prefix_list_entries(
        PrefixListId=prefix_list_id
    )

    entries = resp["Entries"]

    sorted_entries = sorted(
        entries, key=lambda entry: _parse_entry_timestamp(entry)
    )

    entries_ro_remove = _search_for_old_entries(sorted_entries)

    if entries_ro_remove:
        remove_prefix_list_entries(
            client=client,
            entries=entries_ro_remove,
            prefix_list_id=prefix_list_id
        )

    new_cidr = f'{public_ip}/32'

    attempts = 0
    while True:
        try:
            add_new_entry(
                client=client,
                cidr=new_cidr,
                prefix_list_id=prefix_list_id
            )
            break
        except botocore.exceptions.ClientError as e:
            if "You've reached the maximum number of entries for the prefix list" in str(e):
                logger.info("Removing oldest entries from prefix list to add new IP.")
                remove_prefix_list_entries(
                    client=client,
                    entries=[sorted_entries[0]],
                    prefix_list_id=prefix_list_id,
                )

            if attempts >= MAX_PREFIX_LIST_UPDATE_ATTEMPTS:
                logger.exception(f"Can not add new entry to the prefix list {prefix_list_id}")
                raise e

            time.sleep(1)

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

