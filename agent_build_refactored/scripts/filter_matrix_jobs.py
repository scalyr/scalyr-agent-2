import argparse
import json
import os
import sys

DEFAULT_OS = os.environ["DEFAULT_OS"]
DEFAULT_PYTHON_VERSION = os.environ["DEFAULT_PYTHON_VERSION"]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--is-master-run",
        required=True
    )

    args = parser.parse_args()
    matrix = json.loads(sys.stdin.read())

    is_master_run = args.is_master_run == "true"

    run_type_name = "master" if is_master_run else "non-master"
    print(
        f"Doing {run_type_name} workflow run.",
        file=sys.stderr
    )

    result_matrix = {"include": []}
    for job in matrix:
        # If this is non-master run, skip jobs which are not supposed to be in it.
        if job.get("master_run_only", True) and not is_master_run:
            continue
        # Set default valued for some essential matrix values, if not specified.
        if "os" not in job:
            job["os"] = DEFAULT_OS
        if "python-version" not in job:
            job["python-version"] = DEFAULT_PYTHON_VERSION

        result_matrix["include"].append(job)

    print(json.dumps(result_matrix))


if __name__ == "__main__":
    main()
