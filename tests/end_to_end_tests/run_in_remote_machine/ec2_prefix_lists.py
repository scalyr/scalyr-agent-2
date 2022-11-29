import json
import random
import time
import logging

"""
This module is responsible for manipulating AWS ec2 prefix lists.
It's mostly used by the ent to end tests that we run in ec2 instances.
"""

logger = logging.getLogger(__name__)

MAX_PREFIX_LIST_UPDATE_ATTEMPTS = 10


def get_prefix_list_version(client, prefix_list_id: str):
    """
    Get version of the prefix list.
    :param client: ec2 boto3 client.
    :param prefix_list_id: ID of the prefix list.
    """
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


def add_current_ip_to_prefix_list(
    client,
    prefix_list_id: str,
    workflow_id: str = None
):
    """
    Add new CIDR entry with current public IP in to the prefix list. We also additionally store json object in the
        Description of the prefix list entry. This json object has required field called 'time' with timestamp
        which is used by the cleanup script to remove old prefix lists.
    :param client: ec2 boto3 client.
    :param prefix_list_id: ID of the prefix list.
    :param workflow_id: Optional filed to add to the json object that is stored in the Description
        filed of the entry.
    """

    import botocore.exceptions
    import requests

    # Get current public IP.
    with requests.Session() as s:
        resp = s.get("https://api.ipify.org")
        resp.raise_for_status()

    public_ip = resp.content.decode()

    new_cidr = f'{public_ip}/32'

    version = get_prefix_list_version(
        client=client,
        prefix_list_id=prefix_list_id
    )

    attempts = 0
    # Since there may be multiple running ec2 tests, we have to add the retry
    # logic to overcome the prefix list concurrent access issues.
    while True:
        try:
            client.modify_managed_prefix_list(
                PrefixListId=prefix_list_id,
                CurrentVersion=version,
                AddEntries=[
                    {
                        'Cidr': new_cidr,
                        'Description': json.dumps({
                            "time": int(time.time()),
                            "workflow_id": workflow_id
                        })
                    },
                ]
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

