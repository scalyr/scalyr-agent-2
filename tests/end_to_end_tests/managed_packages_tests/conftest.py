import dataclasses
import os
import pathlib as pl
import shutil
import subprocess
import argparse
import http.server
import socketserver
import tarfile
import threading
import time
from typing import List

import pytest

from agent_build_refactored.tools.constants import SOURCE_ROOT
from agent_build_refactored.tools.runner import Runner, RunnerMappedPath
from agent_build_refactored.managed_packages.managed_packages_builders import ALL_MANAGED_PACKAGE_BUILDERS, PREPARE_TOOLSET_GLIBC_X86_64, PYTHON_PACKAGE_NAME, AGENT_LIBS_PACKAGE_NAME
from tests.end_to_end_tests.run_in_remote_machine import DISTROS


def pytest_addoption(parser):
    parser.addoption(
        "--builder-name",
        dest="builder_name",
        required=True
    )

    parser.addoption(
        "--packages-source",
        dest="packages_source",
        required=False,
        help="Directory to packages to test. If not specified, packages will be built inplace."
    )

    parser.addoption(
        "--packages-source-type",
        dest="packages_source_type",
        choices=["dir", "repo"],
        required=False
    )

    all_distros = []

    for distro_name, types in DISTROS.items():
        for t in types:
            all_distros.append(f"{t}:{distro_name}")

    parser.addoption(
        "--distro",
        dest="distro",
        required=True,
        choices=all_distros,
        help="Distribution to test. It has to have format <type>:<distro_name>, "
             "for example: ec2:ubuntu2004, docker:centos6"
    )

    parser.addoption(
        "--aws-access-key",
        required=False,
        help="ID of an access key of an AWS account. Required for testing in ec2 instances."
    )
    parser.addoption(
        "--aws-secret-key",
        required=False,
        help="Secret key of an AWS account. Required for testing in ec2 instances.",
    )
    parser.addoption(
        "--aws-private-key-path",
        required=False,
        help="Path to a private key file. Required for testing in ec2 instances."
    )
    parser.addoption(
        "--aws-private-key-name",
        required=False,
        help="Name to a private key file. Required for testing in ec2 instances."
    )
    parser.addoption(
        "--aws-region",
        required=False,
        help="Name of a AWS region. Required for testing in ec2 instances."
    )
    parser.addoption(
        "--aws-security-group",
        required=False,
        help="Name of an AWS security group. Required for testing in ec2 instances."
    )
    parser.addoption(
        "--aws-security-groups-prefix-list-id",
        required=False,
        help="ID of the prefix list of the security group. Required for testing in ec2 instances."
    )
    parser.addoption(
        "--workflow-id",
        required=False,
        help="Identifier of the current workflow if it runs in CI/CD."
    )


@pytest.fixture(scope="session")
def package_builder_name(request):
    """Name of the builder that build tested packages."""
    return request.config.option.builder_name


@pytest.fixture(scope="session")
def package_builder(package_builder_name):
    """Builder class that builds tested packges."""
    return ALL_MANAGED_PACKAGE_BUILDERS[package_builder_name]


@pytest.fixture(scope="session")
def remote_machine_type(request):
    """
    Fixture with time of the remote machine where tests can run. For now that's ec2 or docker.
    """
    if ":" not in request.config.option.distro:
        return None

    return request.config.option.distro.split(":")[0]


@pytest.fixture(scope="session")
def distro_name(remote_machine_type, request):

    if remote_machine_type is None:
        return request.config.option.distro

    return request.config.option.distro.split(":")[1]


@pytest.fixture(scope="session")
def package_source_type(request):
    if request.config.option.packages_source is None:
        return "dir"

    return request.config.option.packages_source_type


@pytest.fixture(scope="session")
def package_source(package_source_type, package_builder_name, tmp_path_factory, request):
    if package_source_type != "dir":
        return request.config.option.packages_source

    if request.config.option.packages_source is not None:
        packages_dir = pl.Path(request.config.option.packages_source)
        # If packages are specified in the form of tarball, extract it first.
        if packages_dir.is_dir():
            return str(packages_dir)

        with tarfile.open(packages_dir) as tf:
            tmp_dir = tmp_path_factory.mktemp("packages")
            tf.extractall(tmp_dir)
        return str(tmp_dir)

    # packages are also not provided, build them now.
    packages_dir = tmp_path_factory.mktemp("packages")
    builder_cls = ALL_MANAGED_PACKAGE_BUILDERS[package_builder_name]
    builder = builder_cls()
    builder.build_packages()
    shutil.copytree(
        builder.packages_output_path,
        packages_dir,
        dirs_exist_ok=True
    )
    return packages_dir


@pytest.fixture(scope="session")
def python_package_path(package_source_type, package_source, package_builder):
    if package_source_type != "dir":
        return None

    packages_dir = pl.Path(package_source)
    found = list(packages_dir.rglob(f"{PYTHON_PACKAGE_NAME}*.{package_builder.PACKAGE_TYPE}"))
    assert len(found) == 1
    return found[0]


@pytest.fixture(scope="session")
def agent_libs_package_path(package_source_type, package_source, package_builder):
    if package_source_type != "dir":
        return None

    packages_dir = pl.Path(package_source)
    found = list(packages_dir.rglob(f"{AGENT_LIBS_PACKAGE_NAME}*.{package_builder.PACKAGE_TYPE}"))
    assert len(found) == 1
    return found[0]






