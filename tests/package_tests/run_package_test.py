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

from tests.package_tests import all_package_tests


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
    logging.basicConfig(
        level=logging.INFO, format="[%(levelname)s][%(module)s] %(message)s"
    )

    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest="command", required=True)
    list_command_parser = subparsers.add_parser("list")

    package_test_parser = subparsers.add_parser("package-test")
    package_test_subparsers = package_test_parser.add_subparsers(dest="package_test_name", required=True)

    for test_name, package_test in all_package_tests.ALL_PACKAGE_TESTS.items():

        run_package_test_parser = package_test_subparsers.add_parser(test_name)

        run_package_test_parser.add_argument(
            "--build-dir-path", dest="build_dir_path", required=False
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

        if isinstance(package_test, all_package_tests.DockerImagePackageTest):
            run_package_test_parser.add_argument(
                "--cache-from-dir",
            )
            run_package_test_parser.add_argument(
                "--cache-to-dir",
            )

    get_tests_github_matrix_parser = subparsers.add_parser(
        "get-package-builder-tests-github-matrix"
    )
    get_tests_github_matrix_parser.add_argument("package_name")

    args = parser.parse_args()

    if args.command == "list":
        names = [t.unique_name for t in all_package_tests.ALL_PACKAGE_TESTS.values()]
        for test_name in sorted(names):
            print(test_name)

    if args.command == "package-test":
        package_test = all_package_tests.ALL_PACKAGE_TESTS[args.package_test_name]
        scalyr_api_key = get_option("scalyr_api_key", args.scalyr_api_key)

        if isinstance(package_test, all_package_tests.DockerImagePackageTest):
            package_test.run_test(
                scalyr_api_key=scalyr_api_key,
                name_suffix=get_option(
                    "name_suffix", default=str(datetime.datetime.now().timestamp())
                ),
                cache_from_path=args.cache_from_dir,
                cache_to_path=args.cache_to_dir,
            )
        exit(0)
