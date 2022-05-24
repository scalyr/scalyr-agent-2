import argparse
import datetime
import json
import pathlib as pl
import logging
import sys
import os
from typing import Union, Type

__SOURCE_ROOT__ = pl.Path(__file__).parent.parent.parent.absolute()

sys.path.append(str(__SOURCE_ROOT__))

from tests.package_tests.all_package_tests import DOCKER_IMAGE_TESTS
from agent_build.tools.common import init_logging, AGENT_BUILD_OUTPUT

_TEST_CONFIG_PATH = pl.Path(__file__).parent / "credentials.json"

if _TEST_CONFIG_PATH.exists():
    config = json.loads(_TEST_CONFIG_PATH.read_text())
else:
    config = {}


def get_option(
    name: str,
    default: str = None,
    type_: Union[Type[str], Type[list]] = str,
):
    global config

    name = name.lower()

    env_variable_name = name.upper()
    value = os.environ.get(env_variable_name, None)
    if value is not None:
        if type_ == list:
            value = value.split(",")
        else:
            value = type_(value)
        return value

    value = config.get(name, None)
    if value:
        return value

    if default:
        return default

    raise ValueError(
        f"Can't find config option '{name}' "
        f"Provide it through '{env_variable_name}' env. variable or by "
        f"specifying it in the test config file - {_TEST_CONFIG_PATH}."
    )


if __name__ == "__main__":
    init_logging()

    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest="command", required=True)
    list_command_parser = subparsers.add_parser("list")

    package_test_parser = subparsers.add_parser("package-test")
    package_test_subparsers = package_test_parser.add_subparsers(
        dest="package_test_name", required=True
    )

    all_tests = DOCKER_IMAGE_TESTS.copy()

    for test_name, package_test in all_tests.items():

        run_package_test_parser = package_test_subparsers.add_parser(test_name)

        run_package_test_parser.add_argument(
            "--build-root-dir", dest="build_root_dir", required=False
        )
        run_package_test_parser.add_argument(
            "--package-path", dest="package_path", required=False
        )
        run_package_test_parser.add_argument(
            "--frozen-package-test-runner-path",
            dest="frozen_package_test_runner_path",
            required=False,
        )
        run_package_test_parser.add_argument(
            "--scalyr-api-key", dest="scalyr_api_key", required=False
        )
        run_package_test_parser.add_argument(
            "--name-suffix",
            dest="name_suffix",
            help="Additional suffix for the name of the agent instances.",
        )

        run_package_test_parser.add_argument(
            "--show-all-used-steps-ids",
            dest="show_all_used_steps_ids",
            action="store_true"
        )

    get_tests_github_matrix_parser = subparsers.add_parser(
        "get-package-builder-tests-github-matrix"
    )
    get_tests_github_matrix_parser.add_argument("package_name")

    args = parser.parse_args()

    if args.command == "list":
        names = [t.unique_name for t in all_tests.values()]
        for test_name in sorted(names):
            print(test_name)

    if args.command == "package-test":
        scalyr_api_key = get_option("scalyr_api_key", args.scalyr_api_key)
        package_test_cls = all_tests[args.package_test_name]
        if args.build_root_dir:
            build_root_path = pl.Path(args.build_root_dir)
        else:
            build_root_path = AGENT_BUILD_OUTPUT

        if args.package_test_name in DOCKER_IMAGE_TESTS:

            package_test = package_test_cls(
                scalyr_api_key=scalyr_api_key,
                name_suffix=get_option(
                    "name_suffix", default=str(datetime.datetime.now().timestamp())
                ),
            )

            if args.show_all_used_steps_ids:
                print(json.dumps(package_test.all_used_cacheable_steps_ids))
                exit(0)

            package_test.run(
                build_root=build_root_path
            )
        exit(0)
