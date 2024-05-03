#!/usr/bin/env python3

import os

from common.scalyr_query import assert_env_non_empty, power_query, scalyr_query

def validate_env():
    assert_env_non_empty("SERVER_HOST")
    assert_env_non_empty("SCALYR_API_KEY_READ")


def main():
    print("---------------------------------------")
    print("Testing label filtering ...")
    print()

    validate_env()
    SERVER_HOST = os.environ["SERVER_HOST"]
    API_KEY = os.environ["SCALYR_API_KEY_READ"]

    result = scalyr_query(API_KEY, filter = f"app=\"pods-with-labels-app\" serverHost=\"{SERVER_HOST}\"", time_start="20m", retries=10)
    power_result = power_query(API_KEY, query_str=f"app=\"pods-with-labels-app\" serverHost=\"{SERVER_HOST}\" | columns k8s-labels", time_start="20m", retries=10)

    INCLUDED_POD_LABELS = {
        "include_this_label": "include_this_value",
        "pod_include_this_label": "pod_include_this_value",
        "wanted_label": "wanted_value"
    }

    EXCLUDED_POD_LABELS = {
        "pod_label_1": "pod_value_1",  # Not matching include glob
        "pod_label_2": "pod_value_2",  # Not matching include glob
        "pod_label_unwanted_label": "unwanted_value",  # Not matching include glob,
        "pod_include_this_label_exclude": "pod_include_this_value",  # Matching exclude glob
        "pod_include_this_label_garbage": "random_value",  # Matching exclude glob
        "pod_include_this_label_garbage_xxx": "random_value_2",  # Matching exclude glob
        "garbage_pod_include_this_label": "random_value_2",  # Matching exclude glob
        "unwanted_label": "unwanted_value"  # Not matching include glob
    }

    INCLUDED_CONTROLLER_LABELS = ",".join(
        f"{label}={value}"
        for label, value in {
            "controller_include_this_label": "controller_include_this_value",
            "include_this_label": "include_this_value",
            "wanted_label": "wanted_value"
        }.items()
    )

    assert len(result["matches"]) > 0, "No matches found"

    attributes = result["matches"][0]["attributes"]

    for label, value in INCLUDED_POD_LABELS.items():
        assert attributes.get(label) == value, f"Pod label {label} does not match."

    for label, value in EXCLUDED_POD_LABELS.items():
        assert label not in attributes, f"Pod label {label} should not be present."


    def sort_string_dict(s):
        return ",".join(sorted(s.split(",")))

    k8s_labels = sort_string_dict(power_result["values"][0][0])

    assert k8s_labels == INCLUDED_CONTROLLER_LABELS, f"Controller labels do not match. Expected: {INCLUDED_CONTROLLER_LABELS}, got: {k8s_labels}"


if __name__ == "__main__":
    main()



