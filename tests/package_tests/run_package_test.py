import argparse
import json
import pathlib as pl
import logging
import sys
import os
import tempfile
import shutil
from typing import Union, Type

__SOURCE_ROOT__ = pl.Path(__file__).parent.parent.parent.absolute()

sys.path.append(str(__SOURCE_ROOT__))

from tests.package_tests import current_test_specifications
from agent_build import package_builders
from tests.package_tests import current_test_specifications
from agent_build.tools import constants


_TEST_CONFIG_PATH = pl.Path(__file__).parent / "credentials.json"

if _TEST_CONFIG_PATH.exists():
    config = json.loads(_TEST_CONFIG_PATH.read_text())
else:
    config = {}


def get_option(name: str, default: str = None, type_: Union[Type[str], Type[list]] = str, ):
    global config

    name = name.lower()

    env_variable_name = name.upper()
    value = os.environ.get(env_variable_name, None)
    print(f"{env_variable_name}:{value}")
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



def test_package(
        package_test: current_test_specifications.PackageTest,
        build_dir_path: pl.Path,
        scalyr_api_key: str,
        package_path: Union[str, pl.Path] = None,
        frozen_package_test_runner_path: Union[str, pl.Path] = None
):

    if not build_dir_path:
        build_dir_path = pl.Path(tempfile.mkdtemp())
    else:
        build_dir_path = pl.Path(build_dir_path)

    if not package_path:
        package_output_dir_path = build_dir_path / "package"

        if package_output_dir_path.exists():
            shutil.rmtree(package_output_dir_path)
        package_output_dir_path.mkdir(parents=True)

        package_builder = package_test.package_builder

        package_builder.build(
            output_path=package_output_dir_path
        )
        package_path = list(
            package_output_dir_path.glob(package_test.package_builder.filename_glob)
        )[0]
    else:
        package_path = pl.Path(package_path)

    if isinstance(package_test, current_test_specifications.RemoteMachinePackageTest):

        if not frozen_package_test_runner_path:

            frozen_test_runner_build_dir_path = build_dir_path / "frozen_test_runner"
            if frozen_test_runner_build_dir_path.exists():
                shutil.rmtree(frozen_test_runner_build_dir_path)

            frozen_test_runner_build_dir_path.mkdir(parents=True)

            package_test.deployment.deploy()

            test_runner_filename = "frozen_test_runner"

            build_test_runner_frozen_binary.build_test_runner_frozen_binary(
                output_path=frozen_test_runner_build_dir_path,
                filename=test_runner_filename,
                deployment_name=package_test.deployment.name
            )

            frozen_package_test_runner_path = frozen_test_runner_build_dir_path / test_runner_filename
        else:
            frozen_package_test_runner_path = pl.Path(frozen_package_test_runner_path)

        if isinstance(package_test, current_test_specifications.DockerBasedPackageTest):
            package_test.run_in_docker(
                package_path=package_path,
                test_runner_frozen_binary_path=frozen_package_test_runner_path,
                scalyr_api_key=scalyr_api_key,
            )
        if isinstance(package_test, current_test_specifications.DockerImagePackageTest):
            package_test.run(
                scalyr_api_key=scalyr_api_key,
            )
        elif isinstance(package_test, current_test_specifications.Ec2BasedPackageTest):
            package_test.run_in_ec2(
                package_path=package_path,
                test_runner_frozen_binary_path=frozen_package_test_runner_path,
                scalyr_api_key=scalyr_api_key,
                aws_access_key=get_option("aws_access_key"),
                aws_secret_key = get_option("aws_secret_key"),
                aws_keypair_name = get_option("aws_keypair_name"),
                aws_private_key_path = get_option("aws_private_key_path"),
                aws_security_groups = get_option("aws_security_groups", type_=list),
                aws_region=get_option("aws_region"),
            )
    else:
        package_test.run_test_locally(
            package_path=package_path,
            scalyr_api_key=scalyr_api_key
        )





if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s][%(module)s] %(message)s")

    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest="command", required=True)
    list_command_parser = subparsers.add_parser("list")

    package_test_parser = subparsers.add_parser("run-package-test")
    package_test_parser.add_argument("test_name", choices=current_test_specifications.ALL_PACKAGE_TESTS.keys())

    package_test_parser.add_argument("--build-dir-path", dest="build_dir_path", required=False)
    package_test_parser.add_argument("--package-path", dest="package_path", required=False)
    package_test_parser.add_argument(
        "--frozen-package-test-runner-path",
        dest="frozen_package_test_runner_path",
        required=False
    )
    package_test_parser.add_argument("--scalyr-api-key", dest="scalyr_api_key", required=False)

    get_tests_github_matrix_parser = subparsers.add_parser("get-package-builder-tests-github-matrix")
    get_tests_github_matrix_parser.add_argument("package_name")

    args = parser.parse_args()

    if args.command == "list":
        names = [t.unique_name for t in current_test_specifications.ALL_PACKAGE_TESTS.values()]
        for test_name in sorted(names):
            print(test_name)

    if args.command == "run-package-test":

        scalyr_api_key = get_option("scalyr_api_key", args.scalyr_api_key)

        package_test = current_test_specifications.ALL_PACKAGE_TESTS[args.test_name]

        if isinstance(package_test, current_test_specifications.DockerImagePackageTest):
            package_test.run_test(
                scalyr_api_key=scalyr_api_key
            )
        else:
            test_package(
                package_test=package_test,
                build_dir_path=args.build_dir_path,
                package_path=args.package_path,
                scalyr_api_key=scalyr_api_key,
                frozen_package_test_runner_path=args.frozen_package_test_runner_path
            )
        exit(0)

    if args.command == "get-package-builder-tests-github-matrix":
        package_builder = package_builders.ALL_PACKAGE_BUILDERS[args.package_name]
        package_tests = current_test_specifications.PACKAGE_BUILDER_TESTS[package_builder]
        test_specs_names = [s.unique_name for s in package_tests]
        test_specs_deployment_names = [s.deployment.name for s in package_tests]
        package_filename_globs = [package_builder.filename_glob for s in package_tests]

        matrix = {
            "include": []
        }

        for package_test in package_tests:
            runner_os = "ubuntu-20.04"
            if package_test.package_builder.PACKAGE_TYPE == constants.PackageType.MSI:
                if not isinstance(package_test, current_test_specifications.Ec2BasedPackageTest):
                    runner_os = "windows-2019"

            test_json = {
                "test-name": package_test.unique_name,
                "package-filename-glob": package_builder.filename_glob,
                "deployment-name": package_test.deployment.name,
                "os": runner_os
            }
            matrix["include"].append(test_json)

        print(matrix)
        exit(0)

