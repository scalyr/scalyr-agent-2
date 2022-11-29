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
from agent_build_refactored.managed_packages.managed_packages_builders import ALL_MANAGED_PACKAGE_BUILDERS, PREPARE_TOOLSET_GLIBC_X86_64
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


_TEST_APT_REPO_CONF = """
Origin: test_repo
Label: test_repo
Codename: trusty
Architectures: amd64 source
Components: main
Description: example repo
"""


class RepoBuilder(Runner):
    """
    This runner class is responsible for creating deb/rpm repositories from provided packages.
    The result repo is used as a mock repository for testing.
    """
    BASE_ENVIRONMENT = PREPARE_TOOLSET_GLIBC_X86_64

    def build(
        self,
        package_type: str,
        packages_dir_path: pl.Path,
    ):

        self.run_required()

        if self.runs_in_docker:
            self.run_in_docker(
                command_args=[
                    "--package-type",
                    package_type,
                    "--packages-dir",
                    RunnerMappedPath(packages_dir_path)
                ]
            )
            return

        repo_path = self.output_path

        if package_type == "deb":
            # Create deb repository using 'reprepro'.
            conf_path = repo_path / "conf"
            conf_path.mkdir(parents=True)

            conf_distributions_path = conf_path / "distributions"
            conf_distributions_path.write_text(_TEST_APT_REPO_CONF)

            for package_path in packages_dir_path.glob(f"*.deb"):

                subprocess.check_call([
                    "reprepro",
                    "-b",
                    str(repo_path),
                    "includedeb",
                    "trusty",
                    str(package_path)
                ])

        elif package_type == "rpm":
            # Create rpm repository using 'createrepo_c'.
            for package_path in packages_dir_path.glob(f"*.rpm"):
                shutil.copy(
                    package_path,
                    repo_path
                )
            subprocess.check_call([
                "createrepo_c",
                str(repo_path)
            ])

    @classmethod
    def add_command_line_arguments(cls, parser: argparse.ArgumentParser):
        super(RepoBuilder, cls).add_command_line_arguments(parser)

        parser.add_argument(
            "--package-type",
            dest="package_type",
            required=True
        )
        parser.add_argument(
            "--packages-dir",
            dest="packages_dir",
            required=True,
        )

    @classmethod
    def handle_command_line_arguments(
        cls,
        args,
    ):
        super(RepoBuilder, cls).handle_command_line_arguments(args)
        builder = cls()
        builder.build(
            package_type=args.package_type,
            packages_dir_path=pl.Path(args.packages_dir)
        )


@pytest.fixture(scope="session")
def repo_dir(package_builder_name, package_builder, request, tmp_path_factory):

    """
    Fixture with directory where tested packages are stored.
    Depending on provided tests arguments, it may a directory with ready repo, or just a directory
    with packages. In the second case repo is built inplace.
    """
    packages_dir = None
    repo_dir = None

    package_source = request.config.option.packages_source

    if package_source is not None:
        packages_source_type = request.config.option.packages_source_type

        if packages_source_type == "repo":
            repo_dir = pl.Path(package_source)
        elif packages_source_type == "dir":
            packages_dir = pl.Path(package_source)
        else:
            raise Exception(f"Unknown package source type {packages_source_type}")

    if repo_dir:
        # packages are already in for of repo.
        if repo_dir.is_file():
            with tarfile.open(repo_dir) as tf:
                repo_dir = tmp_path_factory.mktemp("repo")
                tf.extractall(repo_dir)

        return repo_dir

    # No repo provided, look for packages to build repo.

    if packages_dir is None:
        # packages are also not provided, build the now.
        packages_dir = tmp_path_factory.mktemp("packages")
        builder_cls = ALL_MANAGED_PACKAGE_BUILDERS[package_builder_name]
        builder = builder_cls()
        builder.build_packages()
        shutil.copytree(
            builder.packages_output_path,
            packages_dir,
            dirs_exist_ok=True
        )

    # Build repo from packages.
    repo_builder = RepoBuilder()
    repo_builder.build(
        package_type=package_builder.PACKAGE_TYPE,
        packages_dir_path=packages_dir
    )
    repo_dir = repo_builder.output_path

    return repo_dir


@pytest.fixture(scope="session")
def repo_url(package_builder_name, package_builder, repo_dir, tmp_path_factory):
    """
    Fixture that starts a web server that serves repo directory.
    """
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=repo_dir, **kwargs)

    with socketserver.TCPServer(("", 0), Handler) as httpd:
        repo_server_thread = threading.Thread(target=httpd.serve_forever)
        repo_server_thread.start()

        time.sleep(1)

        yield f"http://localhost:{httpd.socket.getsockname()[1]}"
        httpd.shutdown()
        repo_server_thread.join()


_YUM_REPO_CONFIG_TEMPLATE = """
[test_repo]
name=test_repo
baseurl={repo_url}
enabled=1
gpgcheck=0"""


@pytest.fixture()
def add_repo(package_builder, distro_name: str):
    """
    Fixture function that configures packages repository.
    :return:
    """
    if package_builder.PACKAGE_TYPE == "deb":
        def add(repo_url):
            repo_file_path = pl.Path("/etc/apt/sources.list.d/test.list")
            repo_file_path.write_text(
                f"deb [ trusted=yes ] {repo_url} trusty main"
            )
            _call_apt(["--allow-unauthenticated", "update"], distro_name=distro_name)
    elif package_builder.PACKAGE_TYPE == "rpm":
        def add(repo_url):
            repo_file_path = pl.Path("/etc/yum.repos.d/test.repo")
            repo_file_path.write_text(
                _YUM_REPO_CONFIG_TEMPLATE.format(repo_url=repo_url)
            )
            if distro_name == "centos6":
                shutil.copy(
                    SOURCE_ROOT / "tests/end_to_end_tests/managed_packages_tests/fixtures/centos6.repo",
                    "/etc/yum.repos.d/CentOS-Base.repo"
                )
            elif distro_name == "centos8":
                def replace_repo_to_vault(repo_file: pl.Path):
                    repo_file.write_text(
                        repo_file.read_text().replace("mirror.centos.org", "vault.centos.org")
                    )
                    repo_file.write_text(
                        repo_file.read_text().replace("#baseurl", "baseurl")
                    )
                    repo_file.write_text(
                        repo_file.read_text().replace("mirrorlist=", "#mirrorlist=")
                    )

                replace_repo_to_vault(pl.Path("/etc/yum.repos.d/CentOS-Linux-BaseOS.repo"))
                replace_repo_to_vault(pl.Path("/etc/yum.repos.d/CentOS-Linux-AppStream.repo"))
    else:
        raise Exception(f"Unknown package type {package_builder.PACKAGE_TYPE}")

    return add


def _call_yum(command: List, distro: str):
    env = {}

    if distro == "centos7":
        # need additional library tweaking for tests that runs from the frozen pytest runner.
        env["LD_LIBRARY_PATH"] = "/lib64"

    subprocess.check_call(
        ["yum", *command],
        env=env
    )


def _call_apt(command: List[str], distro_name: str):
    env = {
        "DEBIAN_FRONTEND": "noninteractive"
    }

    if distro_name in ["ubuntu1804", "ubuntu1604", "ubuntu1404"]:
        # need additional library tweaking for tests that runs from the frozen pytest runner.
        env["PATH"] = f"/usr/sbin:/usr/local/sbin:/sbin:${os.environ['PATH']}"

    subprocess.check_call(
        ["apt", *command],
        env=env
    )


@pytest.fixture()
def install_package(package_builder, distro_name):
    """
    Fixture function that install package from the repository.
    :param package_builder: class of the package builder that build tested packages.
    :param distro_name: Name of the tested distribution.
    :return:
    """
    if package_builder.PACKAGE_TYPE == "deb":
        def install(package_name: str):
            _call_apt(
                ["install", "-y", "--allow-unauthenticated", package_name],
                distro_name=distro_name
            )
    elif package_builder.PACKAGE_TYPE == "rpm":
        def install(package_name: str):
            _call_yum(["install", "-y", package_name], distro=distro_name)
    else:
        raise Exception(f"Unknown package type {package_builder.PACKAGE_TYPE}")

    return install
