#!/usr/bin/env -S python3 -u
# Copyright 2024 Scalyr Inc.
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

import os
import time
from typing import Dict, Set

from kubernetes import client, config
from tabulate import tabulate

from common.scalyr_query import scalyr_query, assert_env_non_empty

ENV_TOKENS = [
    "SCALYR_API_KEY_READ_TEAM_1",
    "SCALYR_API_KEY_READ_TEAM_2",
    "SCALYR_API_KEY_READ_TEAM_3",
    "SCALYR_API_KEY_READ_TEAM_4",
    "SCALYR_API_KEY_READ_TEAM_5",
    "SCALYR_API_KEY_READ_TEAM_6",
    "SCALYR_API_KEY_READ_TEAM_7"
]

ENV_ACCOUNT_NAME_MAPPING = {
    "SCALYR_API_KEY_READ_TEAM_1": "ACCOUNT_NAME_1",
    "SCALYR_API_KEY_READ_TEAM_2": "ACCOUNT_NAME_2",
    "SCALYR_API_KEY_READ_TEAM_3": "ACCOUNT_NAME_3",
    "SCALYR_API_KEY_READ_TEAM_4": "ACCOUNT_NAME_4",
    "SCALYR_API_KEY_READ_TEAM_5": "ACCOUNT_NAME_5",
    "SCALYR_API_KEY_READ_TEAM_6": "ACCOUNT_NAME_6",
    "SCALYR_API_KEY_READ_TEAM_7": "ACCOUNT_NAME_7"
}


def validate_env():
    for token in ENV_TOKENS:
        assert_env_non_empty(token)

    for account_name in ENV_ACCOUNT_NAME_MAPPING.values():
        assert_env_non_empty(account_name)

    assert_env_non_empty("SERVER_HOST")


def get_container_ingested_map(tokens: Dict[str, str], server_host: str, time_start: str, retries=10) -> Dict[str, Set[str]]:
    filter = f"app=\"multi-account-test\" serverHost=\"{server_host}\""

    return {
        token_name: set(
            match["message"].replace("MULTIPLE_ACCOUNT_TEST_CONTAINER_NAME:", "").strip()
            for match in scalyr_query(token, filter, time_start, retries)["matches"]
        )
        for token_name, token in tokens.items()
    }


def main():

    print("---------------------------------------")
    print("Testing multi-account log ingestion ...")
    print()

    validate_env()
    TOKENS = {
        token_name:os.environ[token_name]
        for token_name in ENV_TOKENS
    }

    SERVER_HOST = os.environ["SERVER_HOST"]
    ACCOUNT_NAME_MAPPING = {
        token_name: os.environ[account_name]
        for token_name, account_name in ENV_ACCOUNT_NAME_MAPPING.items()
    }


    print(f"SERVER_HOST={SERVER_HOST}")
    print()

    # namespaces-1 annotations:
    # log.config.scalyr.com/teams.1.secret: scalyr-api-key-team-2

    # namespaces-2 annotations:
    # None

    # workload-pod-1 annotations:
    # log.config.scalyr.com/teams.1.secret: "scalyr-api-key-team-3"
    # log.config.scalyr.com/teams.5.secret: "scalyr-api-key-team-4"
    # log.config.scalyr.com/workload-pod-1-container-1.teams.1.secret: "scalyr-api-key-team-5"
    # log.config.scalyr.com/workload-pod-1-container-2.teams.1.secret: "scalyr-api-key-team-6"
    # log.config.scalyr.com/workload-pod-1-container-2.teams.2.secret: "scalyr-api-key-team-7"

    # | Container Name             | API keys used to ingest logs                             | Note                        |
    # | -------------------------- |----------------------------------------------------------|-----------------------------|
    # | workload-pod-1-container-1 | SCALYR_API_KEY_READ_TEAM_5                               | Container specific api keys |
    # | workload-pod-1-container-2 | SCALYR_API_KEY_READ_TEAM_6, SCALYR_API_KEY_READ_TEAM_7   | Container specific api keys |
    # | workload-pod-1-container-3 | SCALYR_API_KEY_READ_TEAM_3, SCALYR_API_KEY_READ_TEAM_4   | Pod default api keys        |
    # | workload-pod-2-container-1 | SCALYR_API_KEY_READ_TEAM_2                               | Namespace default api key   |
    # | workload-pod-3-container-1 | SCALYR_API_KEY_READ_TEAM_1                               | Agent default api key       |

    def print_container_ingested_map(container_ingested_map):
        print(tabulate(
            [
                (token_name, ACCOUNT_NAME_MAPPING[token_name], ", ".join(container_names))
                for token_name, container_names in container_ingested_map.items()
            ],
            headers=["API KEY NAME", "Account Name", "Containers"],
            tablefmt="fancy_grid"
        ))

    def assert_dicts_equal(expected_dict, actual_dict):
        if expected_dict != actual_dict:
            print("Expected:")
            print_container_ingested_map(expected_dict)
            print("Actual:")
            print_container_ingested_map(actual_dict)

            return False
        return True

    def retry_assert_expected_container_map_ingested(expected_container_ingested_map, time_start):
        def __get_container_ingested_map():
            return get_container_ingested_map(TOKENS, SERVER_HOST, time_start)

        container_ingested_map = __get_container_ingested_map()

        retries_left = 10

        while not assert_dicts_equal(expected_container_ingested_map, container_ingested_map) and retries_left > 0:
            print("Retrying ...")
            time.sleep(30)
            container_ingested_map = __get_container_ingested_map()
            retries_left -= 1

        if not assert_dicts_equal(expected_container_ingested_map, __get_container_ingested_map()):
           raise Exception("Failed to assert expected container map ingested.")


    retry_assert_expected_container_map_ingested(
        {
            "SCALYR_API_KEY_READ_TEAM_1": {"workload-pod-3-container-1"},
            "SCALYR_API_KEY_READ_TEAM_2": {"workload-pod-2-container-1"},
            "SCALYR_API_KEY_READ_TEAM_3": {"workload-pod-1-container-3"},
            "SCALYR_API_KEY_READ_TEAM_4": {"workload-pod-1-container-3"},
            "SCALYR_API_KEY_READ_TEAM_5": {"workload-pod-1-container-1"},
            "SCALYR_API_KEY_READ_TEAM_6": {"workload-pod-1-container-2"},
            "SCALYR_API_KEY_READ_TEAM_7": {"workload-pod-1-container-2"},
        },
        "20m"
    )

    # Configuration Change & Reload Test - Change only

    config.load_kube_config()
    v1 = client.CoreV1Api()

    v1.patch_namespace(
        name="workload-namespace-2",
        body={
            "metadata": {
                "annotations": {
                    "log.config.scalyr.com/teams.66.secret": "scalyr-api-key-team-4"
                }
            }
        }
    )

    # Wait for configuration to be reloaded and 1 minute for logs to be ingested
    print("Change namespace annotations.")
    print("Wait 30s for configuration to be reloaded and 1 minute for logs to be ingested ...")
    time.sleep(30 + 90)

    retry_assert_expected_container_map_ingested(
        {
            "SCALYR_API_KEY_READ_TEAM_1": set(),
            "SCALYR_API_KEY_READ_TEAM_2": {"workload-pod-2-container-1"},
            "SCALYR_API_KEY_READ_TEAM_3": {"workload-pod-1-container-3"},
            "SCALYR_API_KEY_READ_TEAM_4": {"workload-pod-1-container-3", "workload-pod-3-container-1"},
            "SCALYR_API_KEY_READ_TEAM_5": {"workload-pod-1-container-1"},
            "SCALYR_API_KEY_READ_TEAM_6": {"workload-pod-1-container-2"},
            "SCALYR_API_KEY_READ_TEAM_7": {"workload-pod-1-container-2"},
        },
        "1m"
    )

    # Now change pods and namespace annotations

    v1.patch_namespaced_pod(
        name="workload-pod-1",
        namespace="workload-namespace-1",
        body={
            "metadata": {
                "annotations": {
                    "log.config.scalyr.com/teams.1.secret": None,
                    "log.config.scalyr.com/teams.5.secret": None,
                    "log.config.scalyr.com/workload-pod-1-container-2.teams.1.secret": None,
                    "log.config.scalyr.com/workload-pod-1-container-2.teams.11.secret": "scalyr-api-key-team-3",
                }
            }
        }
    )

    v1.patch_namespace(
        name="workload-namespace-1",
        body={
            "metadata": {
                "annotations": {
                    "log.config.scalyr.com/teams.1.secret": "scalyr-api-key-team-3"
                }
            }
        }
    )

    # Wait for configuration to be reloaded and 1 minute for logs to be ingested
    print("Change pods and namespace annotations.")
    print("Wait 30s for configuration to be reloaded and 1 minute for logs to be ingested ...")
    time.sleep(30 + 90)

    retry_assert_expected_container_map_ingested(
        {
            "SCALYR_API_KEY_READ_TEAM_1": set(),
            "SCALYR_API_KEY_READ_TEAM_2": set(),
            "SCALYR_API_KEY_READ_TEAM_3": {"workload-pod-1-container-2", "workload-pod-1-container-3", "workload-pod-2-container-1"},
            "SCALYR_API_KEY_READ_TEAM_4": {"workload-pod-3-container-1"},
            "SCALYR_API_KEY_READ_TEAM_5": {"workload-pod-1-container-1"},
            "SCALYR_API_KEY_READ_TEAM_6": set(),
            "SCALYR_API_KEY_READ_TEAM_7": {"workload-pod-1-container-2"},
        },
        "1m"
    )


if __name__ == "__main__":
    main()




