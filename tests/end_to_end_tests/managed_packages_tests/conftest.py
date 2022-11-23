import pathlib as pl
import shutil

import pytest

from agent_build_refactored.managed_packages.managed_packages_builders import DebManagedPackagesBuilderX86_64, RpmManagedPackagesBuilderx86_64, ALL_MANAGED_PACKAGE_BUILDERS
from tests.end_to_end_tests.managed_packages_tests.portable_pytest_runner import PortablePytestRunnerBuilder, PORTABLE_RUNNER_NAME

def pytest_addoption(parser):
    # parser.addoption(
    #     "--package-type",
    #     dest="package_type",
    #     required=True,
    # )
    #
    # parser.addoption(
    #     "--arch",
    #     dest="arch",
    #     required=True
    # )
    #
    parser.addoption(
        "--builder-name",
        dest="builder_name",
        required=True
    )

    parser.addoption(
        "--package-dir",
        dest="packages_dir",
        required=False,
        help="Directory to packages to test. If not specified, packages will be built inplace."
    )


@pytest.fixture(scope="session")
def managed_packages(request, tmp_path_factory):

    if request.config.option.packages_dir:
        packages_dir_path = pl.Path(request.config.option.packages_dir)
    else:
        builder_cls = ALL_MANAGED_PACKAGE_BUILDERS[request.config.option.builder_name]
        builder = builder_cls()
        builder.build_packages()
        packages_dir_path = tmp_path_factory.mktemp("packages")
        shutil.copytree(
            builder.packages_output_path,
            packages_dir_path,
            dirs_exist_ok=True
        )

    return packages_dir_path


@pytest.fixture(scope="session")
def portable_test_runner(tmp_path_factory):
    builder = PortablePytestRunnerBuilder()
    builder.build()
    tmp_path = tmp_path_factory.mktemp("test_runner")
    shutil.copy(
        builder.output_path / "dist" / PORTABLE_RUNNER_NAME,
        tmp_path
    )

    return tmp_path / PORTABLE_RUNNER_NAME