from http import HTTPStatus
from typing import Callable

import requests
import time
import os
import sys


def scalyr_query(token: str, filter: str, time_start: str, retries: int):
    def post_request():
        return requests.post(
            "https://app.scalyr.com/api/query",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={
                "startTime": time_start,
                "filter": filter
            },
            timeout=10
        )

    return query(post_request, retries)


def power_query(token: str, query_str: str, time_start: str, retries: int):
    def post_request():
        return requests.post(
            "https://app.scalyr.com/api/powerQuery",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={
                "startTime": time_start,
                "query": query_str
            },
            timeout=10
        )

    return query(post_request, retries)


def query(post_request: Callable, retries: int):
    def retry_request():
        retries_left = retries
        response = post_request()

        while response.status_code == HTTPStatus.TOO_MANY_REQUESTS and retries_left > 0:
            print(f"Rate limited. Retrying in 10 seconds. Retries left: {retries_left}")
            time.sleep(10)
            response = post_request()
            retries_left -= 1

        return response

    response = retry_request()

    if not response.ok:
        raise Exception(f"Query failed: {response.status_code}: {response.text}")

    content = response.json()

    if content["status"] != "success":
        print(f"ERROR: Query failed: {content}")
        raise Exception(f"Query failed: {content}")

    return content


def assert_env_non_empty(name):
    if not os.environ.get(name):
        print(f"ERROR: Environment variable {name} is not set or empty.")
        sys.exit(1)
